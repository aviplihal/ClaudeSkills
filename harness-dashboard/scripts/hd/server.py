"""hd.server - local-only authenticated HTTP server for the dashboard (127.0.0.1, random port, bearer token).

Security behavior: token in URL fragment only, bearer on every /api call, constant-time compare,
Host and Origin checks, fixed headers on every response, no CORS, 15-minute idle expiry.
Static assets are identical public code with no data, so they are served without the token.
"""
import argparse
import hmac
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import state as hdstate

IDLE_EXPIRY_S = 900
MAX_BODY = 4096
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
          "/static/style.css": ("style.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self'; base-uri 'none'; frame-ancestors 'none'")


class Provider:
    """Builds /api/state payloads, caching the slow wall, approval and screening lookups."""

    def __init__(self, cfg, clock=time.monotonic, overrides=None):
        """Remember the config and optional injected lookups (used by tests)."""
        self.cfg, self.clock, self.over = cfg, clock, overrides or {}
        self.cache = {}

    def _cached(self, key, ttl, fn):
        """Return a cached value for ttl seconds; failures give None."""
        if key in self.over:
            return self.over[key]
        ent = self.cache.get(key)
        if ent and self.clock() - ent[0] < ttl:
            return ent[1]
        try:
            val = fn()
        except Exception:
            val = None
        self.cache[key] = (self.clock(), val)
        return val

    def state(self):
        """Build the current state payload."""
        cfg = self.cfg

        def wall():
            from . import wall as w
            return w.check(cfg)

        def approval():
            from . import approval as a
            return a.status(cfg)

        def changed():
            from . import screening, records
            return screening.changed_since(cfg, records.Records(cfg["state_dir"]))
        return hdstate.build(cfg, wall=self._cached("wall", 30, wall),
                             approval=self._cached("approval", 10, approval),
                             changed_since=self._cached("changed", 30, changed))


def _default_actions(cfg):
    """Default action handlers backed by the hd modules (lazy imports)."""
    def records():
        from . import records as r
        return r.Records(cfg["state_dir"])

    def screening():
        from . import screening as s
        s.confirm(cfg)

    def approve():
        from . import approval as a
        a.approve(cfg)

    def release():
        records().retention_hold(False, "released from dashboard by user")

    def mode_switch(old, new, confirmed):
        records().mode_switch(old, new, confirmed)
    return {"screening_confirm": screening, "approve": approve, "hold_release": release,
            "mode_switch": mode_switch}


class App:
    """Shared server state: config, token, idle clock, provider and action handlers."""

    def __init__(self, cfg, config_path=None, clock=time.monotonic, actions=None, overrides=None, token=None):
        """Create the app with a fresh random token."""
        self.cfg, self.config_path, self.clock = cfg, config_path or cfg.get("config_path"), clock
        self.token = token or secrets.token_urlsafe(32)
        self.last_auth = clock()
        self.expired = False
        self.lock = threading.Lock()
        self.provider = Provider(cfg, clock, overrides)
        self.actions = dict(_default_actions(cfg), **(actions or {}))
        self.port = None

    def authenticate(self, header):
        """Check the bearer header and idle expiry; return 'ok', 'expired' or 'denied'."""
        with self.lock:
            if self.expired:
                return "expired"
            if self.clock() - self.last_auth > IDLE_EXPIRY_S:
                self.expired = True
                self.token = None
                return "expired"
            if not header or not header.startswith("Bearer "):
                return "denied"
            given = header[7:].strip().encode()
            if not hmac.compare_digest(given, self.token.encode()):
                return "denied"
            self.last_auth = self.clock()
            return "ok"

    def mapping_text(self):
        """Appendix A as plain text from references/control-mapping.md, with a short fallback."""
        for cand in (os.path.normpath(os.path.join(STATIC_DIR, "..", "..", "..", "references", "control-mapping.md")),):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                continue
        return "Control mapping page not found in this install."

    def set_mode(self, new, confirm):
        """Switch mode; Strict to Standard (or unset to Standard) needs confirm. Returns (code, body)."""
        if new not in ("strict", "standard"):
            return 400, {"error": "mode must be strict or standard"}
        old, _ = hdstate.effective_mode(self.cfg)
        if new == "standard" and old == "strict" and confirm is not True:
            return 400, {"error": "switching Strict to Standard needs confirm: true"}
        self.actions["mode_switch"](old, new, bool(confirm))
        self.cfg["mode"] = new
        if self.config_path:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                raw["mode"] = new
                self._write(self.config_path, json.dumps(raw, indent=2))
            except (OSError, ValueError):
                pass
        return 200, {"ok": True, "mode": new}

    @staticmethod
    def _write(path, text):
        """Write a file with mode 0600 (via hd.util when available)."""
        try:
            from . import util
            util.secure_write(path, text)
        except Exception:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)


class Handler(BaseHTTPRequestHandler):
    """Request handler: Host/Origin checks, bearer auth, routing, fixed security headers."""

    server_version = "hd"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        """Log only the method and path without query or headers; never the token."""
        sys.stderr.write("hd: %s %s\n" % (getattr(self, "command", "?"), (getattr(self, "path", "") or "").split("?")[0].split("#")[0][:80]))

    def end_headers(self):
        """Add the fixed security headers to every response, errors included."""
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _send(self, code, body, ctype="application/json"):
        """Send a complete response."""
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _guard(self):
        """Host and Origin checks; returns False after sending 403."""
        port = self.server.server_address[1]
        ok_hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
        if self.headers.get("Host") not in ok_hosts:
            self._send(403, {"error": "bad host"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + h for h in ok_hosts}:
            self._send(403, {"error": "bad origin"})
            return False
        return True

    def _route(self, method):
        """Common request flow for GET and POST."""
        if not self._guard():
            return
        path = self.path.split("?")[0]
        app = self.server.app
        if method == "GET" and path in ASSETS:
            name, ctype = ASSETS[path]
            try:
                with open(os.path.join(STATIC_DIR, name), "rb") as f:
                    return self._send(200, f.read(), ctype)
            except OSError:
                return self._send(404, {"error": "not found"})
        if not path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        auth = app.authenticate(self.headers.get("Authorization"))
        if auth != "ok":
            return self._send(401, {"error": auth})
        body = {}
        if method == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._send(400, {"error": "bad body size"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "body must be a JSON object"})
        try:
            self._api(method, path, body, app)
        except Exception:
            self._send(500, {"error": "internal error"})

    def _api(self, method, path, body, app):
        """Dispatch an authenticated /api call."""
        if method == "GET" and path == "/api/state":
            return self._send(200, app.provider.state())
        if method == "GET" and path == "/api/mapping":
            return self._send(200, app.mapping_text().encode(), "text/plain; charset=utf-8")
        if method == "POST" and path == "/api/mode":
            code, out = app.set_mode(body.get("mode"), body.get("confirm"))
            return self._send(code, out)
        action = {"/api/screening/confirm": "screening_confirm", "/api/hold/release": "hold_release",
                  "/api/approve": "approve"}.get(path)
        if method == "POST" and action:
            if body.get("confirm") is not True:
                return self._send(400, {"error": "confirm: true required"})
            app.actions[action]()
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})

    def do_GET(self):
        """Handle GET."""
        self._route("GET")

    def do_POST(self):
        """Handle POST."""
        self._route("POST")

    def _other(self):
        """Reject any other method."""
        self._send(405, {"error": "method not allowed"})
    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _other


def make_server(cfg, port=0, **kw):
    """Create (not start) the HTTP server bound to 127.0.0.1; returns the server with .app attached."""
    app = App(cfg, **kw)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    srv.app = app
    app.port = srv.server_address[1]
    return srv


def main(argv=None):
    """CLI entry: load the config, start the server, print the one-time URL."""
    ap = argparse.ArgumentParser(prog="hd.server")
    ap.add_argument("--config", required=True)
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args(argv)
    from . import config
    cfg = config.load(a.config)
    srv = make_server(cfg, a.port, config_path=cfg.get("config_path"))
    print("http://127.0.0.1:%d/#t=%s" % (srv.app.port, srv.app.token), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
