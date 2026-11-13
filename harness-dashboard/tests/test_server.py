# test_server.py - tests for hd.server security behavior: token, Host/Origin, headers, idle expiry, mode switch.
import atexit
import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from hd import server  # noqa: E402

REQUIRED = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


class Clock:
    """A settable fake clock."""

    def __init__(self):
        """Start at zero."""
        self.t = 0.0

    def __call__(self):
        """Current fake time."""
        return self.t


class ServerCase(unittest.TestCase):
    """Starts a server on port 0 in a thread for each test."""

    def setUp(self):
        """Create state dir, config file, server and thread."""
        self.sd = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, self.sd, True)
        self.cfg_path = os.path.join(self.sd, "harness.json")
        self.cfg = {"name": "t", "mode": "strict", "state_dir": self.sd, "wall": {"tier": "none"}, "data_sources": [], "middle": {"panels": []}}
        with open(self.cfg_path, "w") as f:
            json.dump(self.cfg, f)
        self.clock = Clock()
        self.switches = []
        self.srv = server.make_server(self.cfg, 0, config_path=self.cfg_path, clock=self.clock,
                                      actions={"mode_switch": lambda o, n, c: self.switches.append((o, n, c)),
                                               "approve": lambda: self.switches.append("approve")},
                                      overrides={"wall": None, "approval": None, "changed": None})
        self.port = self.srv.server_address[1]
        self.token = self.srv.app.token
        self.thread = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        """Shut the server down."""
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, token="good", host="default", origin=None, body=None):
        """Issue a request; returns (status, headers dict, body bytes)."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": self.host() if host == "default" else host}
        if token == "good":
            h["Authorization"] = "Bearer " + self.token
        elif token:
            h["Authorization"] = "Bearer " + token
        if origin:
            h["Origin"] = origin
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def host(self):
        """The correct Host header value."""
        return "127.0.0.1:%d" % self.port


class SecurityTests(ServerCase):
    """Auth, Host, Origin, headers, expiry."""

    def test_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_no_token_401(self):
        self.assertEqual(self.req("GET", "/api/state", token=None)[0], 401)

    def test_wrong_token_401(self):
        self.assertEqual(self.req("GET", "/api/state", token="nope")[0], 401)

    def test_good_token_serves_state(self):
        s, _, b = self.req("GET", "/api/state")
        self.assertEqual(s, 200)
        self.assertIn("verdict", json.loads(b))

    def test_bad_host_403(self):
        self.assertEqual(self.req("GET", "/api/state", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.req("GET", "/", host="evil.example")[0], 403)

    def test_localhost_host_ok(self):
        self.assertEqual(self.req("GET", "/api/state", host="localhost:%d" % self.port)[0], 200)

    def test_bad_origin_403(self):
        self.assertEqual(self.req("GET", "/api/state", origin="http://evil.example")[0], 403)
        self.assertEqual(self.req("POST", "/api/mode", origin="http://evil.example", body={"mode": "strict"})[0], 403)

    def test_matching_origin_ok(self):
        self.assertEqual(self.req("GET", "/api/state", origin="http://" + self.host())[0], 200)

    def test_headers_on_every_response(self):
        cases = [self.req("GET", "/api/state"), self.req("GET", "/api/state", token=None),
                 self.req("GET", "/api/state", host="bad"), self.req("GET", "/nothing"),
                 self.req("GET", "/"), self.req("PUT", "/api/state"), self.req("GET", "/static/app.js")]
        for s, h, _ in cases:
            for k, v in REQUIRED.items():
                self.assertEqual(h.get(k), v, (s, k))
            self.assertIn("default-src 'none'", h.get("Content-Security-Policy", ""))
            self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
            self.assertFalse([k for k in h if k.lower().startswith("access-control")])

    def test_idle_expiry(self):
        self.assertEqual(self.req("GET", "/api/state")[0], 200)
        self.clock.t += 899
        self.assertEqual(self.req("GET", "/api/state")[0], 200)     # activity resets the idle timer
        self.clock.t += 901
        s, _, b = self.req("GET", "/api/state")
        self.assertEqual(s, 401); self.assertEqual(json.loads(b)["error"], "expired")
        self.clock.t = 0
        self.assertEqual(self.req("GET", "/api/state")[0], 401)      # stays dead

    def test_unauthenticated_does_not_extend_idle(self):
        self.clock.t += 800
        self.req("GET", "/api/state", token=None)
        self.clock.t += 200
        self.assertEqual(self.req("GET", "/api/state")[0], 401)

    def test_assets_have_no_data_and_unknown_paths_404(self):
        s, _, b = self.req("GET", "/", token=None)
        self.assertEqual(s, 200); self.assertNotIn(self.token.encode(), b)
        self.assertEqual(self.req("GET", "/static/../server.py", token=None)[0], 404)
        self.assertEqual(self.req("GET", "/nothing")[0], 404)

    def test_log_does_not_print_token_or_query(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.req("GET", "/api/state?t=" + self.token)
            self.req("GET", "/api/state", token="secret-wrong-token")
        self.assertNotIn(self.token, buf.getvalue()); self.assertNotIn("secret-wrong-token", buf.getvalue())
        self.assertNotIn("?t=", buf.getvalue())

    def test_mapping_is_text(self):
        s, h, _ = self.req("GET", "/api/mapping")
        self.assertEqual(s, 200); self.assertTrue(h["Content-Type"].startswith("text/plain"))


class ActionTests(ServerCase):
    """Mode switching and confirmed actions."""

    def test_strict_to_standard_needs_confirm(self):
        s, _, _ = self.req("POST", "/api/mode", body={"mode": "standard"})
        self.assertEqual(s, 400); self.assertEqual(self.switches, [])
        s, _, _ = self.req("POST", "/api/mode", body={"mode": "standard", "confirm": False})
        self.assertEqual(s, 400)
        s, _, _ = self.req("POST", "/api/mode", body={"mode": "standard", "confirm": True})
        self.assertEqual(s, 200)
        self.assertEqual(self.switches, [("strict", "standard", True)])
        with open(self.cfg_path) as f:
            self.assertEqual(json.load(f)["mode"], "standard")
        self.assertEqual(oct(os.stat(self.cfg_path).st_mode & 0o777), "0o600")

    def test_standard_to_strict_recorded_without_confirm(self):
        self.srv.app.cfg["mode"] = "standard"
        self.assertEqual(self.req("POST", "/api/mode", body={"mode": "strict"})[0], 200)
        self.assertEqual(self.switches, [("standard", "strict", False)])

    def test_bad_mode_and_bad_body(self):
        self.assertEqual(self.req("POST", "/api/mode", body={"mode": "wild", "confirm": True})[0], 400)
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", "/api/mode", body=b"not json", headers={"Host": self.host(), "Authorization": "Bearer " + self.token})
        self.assertEqual(c.getresponse().status, 400)

    def test_approve_needs_confirm(self):
        self.assertEqual(self.req("POST", "/api/approve", body={})[0], 400)
        self.assertEqual(self.switches, [])
        self.assertEqual(self.req("POST", "/api/approve", body={"confirm": True})[0], 200)
        self.assertEqual(self.switches, ["approve"])

    def test_post_requires_token(self):
        self.assertEqual(self.req("POST", "/api/mode", token=None, body={"mode": "standard", "confirm": True})[0], 401)


if __name__ == "__main__":
    unittest.main()
