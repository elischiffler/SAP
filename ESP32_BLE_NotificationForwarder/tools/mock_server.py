#!/usr/bin/env python3
"""Tiny mock server for the ANCS forwarder: prints every JSON POST to /notifications.

    python3 tools/mock_server.py            # listens on 0.0.0.0:8080
    python3 tools/mock_server.py 9000       # custom port

Set SERVER_URL in include/config.h to http://<this computer's LAN IP>:8080
Add --fail N to answer the first N POSTs with HTTP 503 (tests the retry queue).
"""
import argparse
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

fail_left = 0
count = 0


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global fail_left, count
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if self.path != "/notifications":
            self.send_response(404)
            self.end_headers()
            return
        if fail_left > 0:
            fail_left -= 1
            print(f"[{stamp}] simulating failure ({fail_left} left)", flush=True)
            self.send_response(503)
            self.end_headers()
            return
        try:
            data = json.loads(body)
        except ValueError as e:
            print(f"[{stamp}] INVALID JSON ({e}): {body!r}", flush=True)
            self.send_response(400)
            self.end_headers()
            return
        count += 1
        print(f"[{stamp}] #{count} from {self.client_address[0]}\n{json.dumps(data, indent=2, ensure_ascii=False)}\n", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # silence default access log
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=8080)
    ap.add_argument("--fail", type=int, default=0, metavar="N", help="reply 503 to the first N requests")
    args = ap.parse_args()
    fail_left = args.fail
    print(f"Listening on 0.0.0.0:{args.port}  (POST /notifications)", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
