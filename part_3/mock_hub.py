"""
Local mock hub server for testing Part 3 without connecting to the real hub.

Usage:
    python mock_hub.py           # starts on port 8080
    python mock_hub.py 9090      # custom port

Then in .env set:
    HUB_URL=http://localhost:8080
    DRY_RUN=false
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

MOCK_PASSWORD = "th25-agents-vg"

_messages: list[dict] = []
_seq_counter = 0


class HubHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[mock_hub] {self.address_string()} {format % args}")

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        password = (params.get("password") or [""])[0]
        if password != MOCK_PASSWORD:
            self._send_json(401, {"error": "wrong password"})
            return

        if parsed.path == "/api/messages":
            since = int((params.get("since") or ["0"])[0])
            result = [m for m in _messages if m["seq"] > since]
            self._send_json(200, {"messages": result})

        elif parsed.path == "/api/stats":
            from collections import Counter
            counts = Counter(m["agent_name"] for m in _messages)
            self._send_json(200, {
                "per_agent": dict(counts),
                "max_per_agent": 10,
                "max_global": 500,
                "total_messages": len(_messages),
                "agents_capped": [],
            })

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        global _seq_counter

        parsed = urlparse(self.path)
        if parsed.path != "/api/message":
            self._send_json(404, {"error": "not found"})
            return

        body = self._read_body()
        if body.get("password") != MOCK_PASSWORD:
            self._send_json(401, {"error": "wrong password"})
            return

        agent_name = body.get("agent_name", "").strip()
        content = body.get("content", "").strip()

        if not agent_name or not content:
            self._send_json(400, {"error": "missing agent_name or content"})
            return
        if len(content) > 4096:
            self._send_json(400, {"error": "message too long"})
            return

        _seq_counter += 1
        msg = {
            "seq": _seq_counter,
            "agent_name": agent_name,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _messages.append(msg)
        print(f"[mock_hub] [{agent_name}]: {content[:80]}")
        self._send_json(200, {"status": "ok", "seq": _seq_counter})


def seed_messages(messages: list[tuple[str, str]]) -> None:
    """Pre-populate the mock hub with messages for testing."""
    global _seq_counter
    for agent_name, content in messages:
        _seq_counter += 1
        _messages.append({
            "seq": _seq_counter,
            "agent_name": agent_name,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    # Seed with a couple of starter messages so the agent has something to react to
    seed_messages([
        ("grader-bot", "Welcome everyone! Let's start the session. What should we build today?"),
        ("alice-dev", "I think we should build a simple CLI tool. Any suggestions?"),
    ])

    server = HTTPServer(("localhost", port), HubHandler)
    print(f"[mock_hub] running on http://localhost:{port}")
    print(f"[mock_hub] {len(_messages)} seed messages loaded")
    print("[mock_hub] Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock_hub] stopped")
