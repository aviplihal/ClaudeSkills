# Tests for the checks module (stdlib unittest only).
import os, sys, json, tempfile, unittest, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from hd import checks, util


class Base(unittest.TestCase):
    """Shared temp dir with a data source folder and a state dir."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = os.path.join(self.d, "src"); os.mkdir(self.src)
        self.state = os.path.join(self.d, "state")
        self.cfg = {"data_sources": [self.src], "state_dir": self.state}
        self.addCleanup(shutil.rmtree, self.d, True)

    def w(self, name, obj):
        """Write a JSON file into the source folder."""
        with open(os.path.join(self.src, name), "w") as f:
            json.dump(obj, f)

    def spec(self, type_, params, **kw):
        """Build an independent spec."""
        s = {"id": "c1", "description": "d", "type": type_, "params": params,
             "independent_because": "reads the original file", "cannot_catch": "x", "how_to_break": "y"}
        s.update(kw)
        return s

    def state_of(self, spec, **kw):
        """Run one check and return its state."""
        return checks.run_check(self.cfg, spec, **kw)["state"]

    def assert_detects(self, spec, setup, brk, **kw):
        """Fault test: passes, then goes red (fail) after break."""
        setup()
        r = checks.fault_test(self.cfg, spec, brk, **kw)
        self.assertEqual(r["baseline"], "pass", r)
        self.assertEqual(r["after_break"], "fail", r)
        self.assertTrue(r["detects_break"])


class TestTypes(Base):
    def test_field_present(self):
        sp = self.spec("field_present", {"file": "o.json", "path": "cars", "fields": ["price"]})
        self.assert_detects(sp, lambda: self.w("o.json", {"cars": [{"price": 5}]}),
                            lambda: self.w("o.json", {"cars": [{"price": None}]}))

    def test_count_in_range(self):
        sp = self.spec("count_in_range", {"file": "o.json", "path": "cars", "min": 2, "max": 5})
        self.assert_detects(sp, lambda: self.w("o.json", {"cars": [1, 2, 3]}),
                            lambda: self.w("o.json", {"cars": []}))

    def test_rederive_json_path(self):
        sp = self.spec("rederive", {"output": {"file": "o.json", "path": "price"},
                                    "source": {"kind": "json_path", "file": "s.json", "path": "p"}})
        self.w("s.json", {"p": "1,200"})
        self.assert_detects(sp, lambda: self.w("o.json", {"price": 1200}),
                            lambda: self.w("o.json", {"price": 999}))

    def test_rederive_http_get_injected_fetcher(self):
        calls = []
        def fetch(url):
            calls.append(url); return "<b>Price: $1,200</b>"
        src = {"kind": "http_get", "url": "https://example.com/x", "regex": r"Price: \$([\d,]+)",
               "allowed_hosts": ["example.com"]}
        sp = self.spec("rederive", {"output": {"file": "o.json", "path": "price"}, "source": src})
        self.w("o.json", {"price": 1200})
        self.assertEqual(self.state_of(sp, fetcher=fetch), "pass")
        self.w("o.json", {"price": 1300})
        self.assertEqual(self.state_of(sp, fetcher=fetch), "fail")

    def test_rederive_rejects_other_host_before_network(self):
        calls = []
        src = {"kind": "http_get", "url": "https://evil.example.net/x", "regex": "(.*)",
               "allowed_hosts": ["example.com"]}
        sp = self.spec("rederive", {"output": {"file": "o.json", "path": "p"}, "source": src})
        self.w("o.json", {"p": 1})
        self.assertEqual(self.state_of(sp, fetcher=lambda u: calls.append(u) or "1"), "could_not_check")
        self.assertEqual(calls, [])
        for bad in ("https://example.com.evil.net/", "https://user@evil.net/", "file:///etc/passwd",
                    "https://example.com@evil.net/"):
            self.assertFalse(checks._host_allowed(bad, ["example.com"]), bad)
        self.assertTrue(checks._host_allowed("https://Example.com:8443/a", ["example.com"]))

    def test_file_hash(self):
        p = os.path.join(self.src, "f.bin")
        sp = self.spec("file_hash", {"file": "f.bin", "min_size": 3, "sha256": checks.hashlib.sha256(b"abcd").hexdigest()})
        def ok(): open(p, "wb").write(b"abcd")
        def brk(): open(p, "wb").write(b"abXd")
        self.assert_detects(sp, ok, brk)

    def test_file_hash_missing_is_fail(self):
        self.assertEqual(self.state_of(self.spec("file_hash", {"file": "nope"})), "fail")

    def test_cross_ref(self):
        sp = self.spec("cross_ref", {"a": {"file": "a.json", "path": "ids"},
                                     "b": {"file": "b.json", "path": "rows", "key": "id"}})
        self.w("b.json", {"rows": [{"id": 1}, {"id": 2}]})
        self.assert_detects(sp, lambda: self.w("a.json", {"ids": [1, 2]}),
                            lambda: self.w("a.json", {"ids": [1, 9]}))

    def test_time_window_mtime_and_field(self):
        p = os.path.join(self.src, "f.txt")
        sp = self.spec("time_window", {"file": "f.txt", "max_age_hours": 1})
        def ok(): open(p, "w").write("x"); os.utime(p, None)
        def brk(): os.utime(p, (1000, 1000))
        self.assert_detects(sp, ok, brk)
        sp2 = self.spec("time_window", {"file": "t.json", "path": "ts", "max_age_hours": 1})
        self.w("t.json", {"ts": util.now()})
        self.assertEqual(self.state_of(sp2), "pass")
        self.w("t.json", {"ts": "2001-01-01T00:00:00Z"})
        self.assertEqual(self.state_of(sp2), "fail")

    def ka(self, params):
        """Build a reviewed known_answer spec (adds the review hash the skill computes at approval)."""
        params = dict(params)
        params["reviewed_hash"] = checks.known_answer_hash(self.cfg, params)
        return self.spec("known_answer", params)

    def test_known_answer(self):
        exp = {"v": "5"}
        sp = self.ka({"command": [sys.executable, "-c", "print(2+3)"], "expected": exp["v"]})
        self.assert_detects(sp, lambda: None, lambda: exp.update(v="6") or sp["params"].update(expected="6"))

    def test_known_answer_runs_in_temp_copy(self):
        self.w("in.json", {"a": 1})
        sp = self.ka({"command": [sys.executable, "-c", "open('in.json','w').write('X');print(1)"],
                      "copy": ["in.json"], "expected": "1"})
        self.assertEqual(self.state_of(sp), "pass")
        self.assertEqual(json.load(open(os.path.join(self.src, "in.json"))), {"a": 1})

    def test_known_answer_timeout_is_could_not_check(self):
        sp = self.ka({"command": [sys.executable, "-c", "import time;time.sleep(5)"],
                      "expected": "", "timeout": 0.3})
        self.assertEqual(self.state_of(sp), "could_not_check")

    def test_known_answer_requires_review_hash(self):
        """No hash, a wrong hash, or a changed argv means 'not reviewed' and the command never runs."""
        marker = os.path.join(self.d, "ran.txt")
        cmd = [sys.executable, "-c", "open(%r,'w').write('x');print(1)" % marker]
        for p in ({"command": cmd, "expected": "1"},
                  {"command": cmd, "expected": "1", "reviewed_hash": "0" * 64}):
            r = checks.run_check(self.cfg, self.spec("known_answer", p))
            self.assertEqual((r["state"], r["detail"]), ("could_not_check", "not reviewed"))
        self.assertFalse(os.path.exists(marker))
        sp = self.ka({"command": cmd, "expected": "1"})
        sp["params"]["command"] = cmd[:2] + ["print(2)"]
        self.assertEqual(self.state_of(sp), "could_not_check")

    def test_known_answer_hash_covers_argv_files(self):
        """Editing a script named in argv changes the review hash."""
        script = os.path.join(self.src, "k.py")
        open(script, "w").write("print(1)")
        p = {"command": [sys.executable, script], "expected": "1"}
        h1 = checks.known_answer_hash(self.cfg, p)
        self.assertEqual(self.state_of(self.ka(p)), "pass")
        open(script, "w").write("print(2)")
        self.assertNotEqual(h1, checks.known_answer_hash(self.cfg, p))
        self.assertEqual(self.state_of(self.spec("known_answer", dict(p, reviewed_hash=h1))), "could_not_check")

    def test_minimal_env_for_known_answer_and_custom(self):
        """Secrets in the parent environment are not visible to the child."""
        os.environ["HD_TEST_SECRET"] = "s3cret"
        self.addCleanup(os.environ.pop, "HD_TEST_SECRET", None)
        out = os.path.join(self.d, "env.txt")
        code = "import os;open(%r,'w').write(','.join(sorted(os.environ)));print(1)" % out
        self.assertEqual(self.state_of(self.ka({"command": [sys.executable, "-c", code], "expected": "1"})), "pass")
        names = set(open(out).read().split(","))
        self.assertNotIn("HD_TEST_SECRET", names)
        self.assertTrue(names <= {"PATH", "HOME", "LANG", "HD_OUTPUTS_DIR", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}, names)


class TestCustom(Base):
    def script(self, body="import sys; sys.exit(0)"):
        """Write a custom script and return (path, sha)."""
        p = os.path.join(self.src, "chk.py"); open(p, "w").write(body)
        return p, checks._sha256_file(p)

    def test_rejected_without_or_with_wrong_hash(self):
        self.script()
        self.assertEqual(self.state_of(self.spec("custom", {"script": "chk.py"})), "could_not_check")
        self.assertEqual(self.state_of(self.spec("custom", {"script": "chk.py", "reviewed_hash": "0" * 64})),
                         "could_not_check")

    def test_pass_then_fail_when_script_exits_nonzero(self):
        p, sha = self.script()
        sp = self.spec("custom", {"script": "chk.py", "reviewed_hash": sha})
        self.assertEqual(self.state_of(sp), "pass")
        p, sha = self.script("import sys; sys.exit(3)")
        sp["params"]["reviewed_hash"] = sha
        self.assertEqual(self.state_of(sp), "fail")

    def test_edited_script_invalidates_review(self):
        p, sha = self.script()
        sp = self.spec("custom", {"script": "chk.py", "reviewed_hash": sha})
        open(p, "a").write("\n# tampered\n")
        self.assertEqual(self.state_of(sp), "could_not_check")

    def test_runs_read_only_on_copy(self):
        self.w("out.json", {"a": 1})
        body = "open('out.json','w').write('X')"   # write attempt must fail (read-only copy)
        p, sha = self.script(body)
        sp = self.spec("custom", {"script": "chk.py", "reviewed_hash": sha, "outputs": ["out.json"]})
        self.assertEqual(self.state_of(sp), "fail" if os.geteuid() != 0 else "pass")
        self.assertEqual(json.load(open(os.path.join(self.src, "out.json"))), {"a": 1})


class TestRunAll(Base):
    def test_agent_claimed_when_no_independent_because(self):
        self.w("o.json", {"x": 1})
        sp = self.spec("field_present", {"file": "o.json", "path": "x"})
        sp["independent_because"] = ""
        r = checks.run_check(self.cfg, sp)
        self.assertEqual(r["state"], "pass")
        self.assertFalse(r["independent"]); self.assertTrue(r["agent_claimed"])
        del sp["independent_because"]
        self.assertFalse(checks.run_check(self.cfg, sp)["independent"])

    def test_fail_distinct_from_could_not_check_and_no_raise(self):
        self.w("o.json", {"x": 1})
        fail = self.spec("field_present", {"file": "o.json", "path": "y"}, id="a")
        cnc = self.spec("nonsense", {}, id="b")
        boom = self.spec("count_in_range", {}, id="c")           # KeyError inside
        self.cfg["signals"] = [fail, cnc, boom, "garbage"]
        res = checks.run_all(self.cfg)
        self.assertEqual([r["state"] for r in res], ["fail", "could_not_check", "could_not_check"])
        self.assertTrue(all(r["ts"].endswith("Z") for r in res))

    def test_detail_never_contains_file_contents(self):
        self.w("o.json", {"secret": "TOPSECRETVALUE"})
        self.w("s.json", {"p": "OTHERSECRET"})
        sp = self.spec("rederive", {"output": {"file": "o.json", "path": "secret"},
                                    "source": {"kind": "json_path", "file": "s.json", "path": "p"}})
        r = checks.run_check(self.cfg, sp)
        self.assertEqual(r["state"], "fail")
        self.assertNotIn("SECRET", r["detail"])

    def test_writes_checks_json_private(self):
        self.w("o.json", {"x": 1})
        self.cfg["signals"] = {"checks": [self.spec("field_present", {"file": "o.json", "path": "x"})]}
        checks.run_all(self.cfg)
        p = os.path.join(self.state, "checks.json")
        self.assertEqual(json.load(open(p))[0]["state"], "pass")
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
