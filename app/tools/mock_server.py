#!/usr/bin/env python3
"""Stand-in for the two gate endpoints, so the app can be tested on real
phones before the FastAPI backend exists. Run on a laptop on the same Wi-Fi
as the phones.

    python tools/make_test_passes.py   # once
    python tools/mock_server.py        # then open http://<laptop-ip>:8787/

Pages:
  /          setup QR (scan it in the app) and links
  /passes    test QR passes, one per gate outcome
  /status    what the server has received
  /revoke?id=<pass id>   cancel a pass (shows red on the next refresh)

Debug builds of the app accept http:// and the test key from the setup QR.
Release builds need https and the key compiled in.
"""
import base64
import io
import json
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import qrcode

DATA = Path(__file__).resolve().parent / "test_data"
PORT = 8787
TOKEN = "test-device-token"

lock = threading.Lock()
seq = 0
passes = {}      # id -> (seq, record)
checkins = []    # (seq, record)


def next_seq():
    global seq
    seq += 1
    return seq


def load():
    for p in json.loads((DATA / "manifest.json").read_text())["passes"]:
        passes[p["id"]] = (next_seq(), p)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def qr_data_uri(text, box=8):
    img = qrcode.make(text, box_size=box, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
 body{{font:16px system-ui,sans-serif;margin:24px;background:#f6f4ef;color:#14161a}}
 h1{{font-size:22px}} a{{color:#b34f00}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}}
 .card{{background:#fff;border:1px solid #e2ded5;border-radius:14px;padding:14px;text-align:center}}
 .card img{{width:200px;height:200px;image-rendering:pixelated}}
 .green{{border-top:6px solid #0e8a3e}} .red{{border-top:6px solid #c62828}}
 code{{background:#fff;padding:2px 6px;border-radius:6px}}
</style>
<h1>{title}</h1>{body}"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        print(f"{self.address_string()} {fmt % a}")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, title, body):
        out = PAGE.format(title=title, body=body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(out)

    def _authed(self):
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._json(401, {"detail": "bad device token"})
            return False
        return True

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/gate/manifest":
            if not self._authed():
                return
            since = int(q.get("since", ["0"])[0] or 0)
            limit = min(int(q.get("limit", ["1000"])[0]), 2000)
            with lock:
                rows = sorted((s, p) for s, p in passes.values() if s > since)
                page = rows[:limit]
                self._json(200, {
                    "passes": [p for _, p in page],
                    "next_cursor": str(page[-1][0]) if page else str(since),
                    "has_more": len(rows) > limit,
                    "total": len(passes) if since == 0 else None,
                })
            return
        if url.path == "/":
            base = f"http://{lan_ip()}:{PORT}"
            setup = json.dumps({"t": "moksha-gate-setup", "url": base, "token": TOKEN,
                                "gate": "Test gate", "day": 1,
                                "key": json.loads((DATA / "test_key.json").read_text())["public"]})
            self._html("Moksha Gate mock server", f"""
              <p>Server address: <code>{base}</code> · device token: <code>{TOKEN}</code></p>
              <div class=card style="max-width:320px"><img src="{qr_data_uri(setup)}">
              <p><b>Setup code</b><br>Scan this from the app's setup screen
              (debug build).</p></div>
              <p><a href=/passes>Test passes</a> · <a href=/status>Server status</a></p>""")
            return
        if url.path == "/passes":
            cards = []
            for s in json.loads((DATA / "scenarios.json").read_text()):
                cards.append(f"""<div class="card {s['kind']}"><img src="{qr_data_uri(s['token'], 6)}">
                  <p><b>{s['label']}</b><br>{s['name']}</p></div>""")
            self._html("Test passes", "<p>Scan these from the laptop screen. Phone set to Day 1.</p>"
                       f"<div class=grid>{''.join(cards)}</div>")
            return
        if url.path == "/status":
            with lock:
                rows = "".join(
                    f"<tr><td>{c['scanned_at']}</td><td>{c['gate']}</td><td>{c['result']}</td>"
                    f"<td>{c.get('reason') or ''}</td><td>{passes.get(c['pass_id'], (0, {'name': '?'}))[1]['name']}</td></tr>"
                    for _, c in reversed(checkins[-200:]))
            self._html("Server status", f"<p>{len(passes)} passes · {len(checkins)} check-ins</p>"
                       "<table cellpadding=6><tr><th>Time (UTC)<th>Gate<th>Result<th>Reason<th>Name</tr>"
                       f"{rows}</table>")
            return
        if url.path == "/revoke":
            pid = q.get("id", [""])[0]
            with lock:
                if pid not in passes:
                    return self._json(404, {"detail": "no such pass"})
                rec = dict(passes[pid][1], revoked=True,
                           updated_at=datetime.now(timezone.utc).isoformat())
                passes[pid] = (next_seq(), rec)
            return self._json(200, {"revoked": pid})
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/gate/checkins":
            return self._json(404, {"detail": "not found"})
        if not self._authed():
            return
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        device, gate = body.get("device_id", "?"), body.get("gate", "?")
        since = int(body.get("since") or 0)
        accepted, conflicts = [], []
        with lock:
            known = {c["id"] for _, c in checkins}
            for c in body.get("checkins", []):
                if c["id"] not in known:
                    if c["result"] == "admitted":
                        earlier = [x for _, x in checkins
                                   if x["pass_id"] == c["pass_id"] and x["day"] == c["day"]
                                   and x["result"] == "admitted"
                                   and x["device_id"] != device]
                        if earlier:
                            conflicts.append(c["id"])
                    checkins.append((next_seq(), dict(c, device_id=device, gate=gate)))
                accepted.append(c["id"])
            remote = [c for s, c in checkins if s > since and c["device_id"] != device]
            self._json(200, {"accepted": accepted, "conflicts": conflicts,
                             "remote": remote, "next_since": str(seq)})


if __name__ == "__main__":
    if not (DATA / "manifest.json").exists():
        raise SystemExit("Run tools/make_test_passes.py first.")
    load()
    print(f"Mock gate server on http://{lan_ip()}:{PORT}/  ({len(passes)} passes)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
