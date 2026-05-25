"""
Mock hub server with web dashboard for local multi-agent demo.
GET /          — live chat UI (open in browser)
POST /api/message — send a message
GET /api/messages — fetch messages since seq N
GET /api/stats    — hub stats
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MOCK_PASSWORD = "th25-agents-vg"

_messages: list[dict] = []
_seq_counter = 0
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hell's Agents Hub — Local Demo</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    height: 100vh;
    display: flex;
    flex-direction: column;
  }
  header {
    background: #1a1d27;
    border-bottom: 1px solid #2d3148;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }
  header h1 { font-size: 16px; font-weight: 600; color: #a78bfa; }
  #status { font-size: 12px; color: #64748b; margin-left: auto; }
  #status.live { color: #4ade80; }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .msg {
    background: #1a1d27;
    border: 1px solid #2d3148;
    border-radius: 10px;
    padding: 10px 14px;
    max-width: 820px;
    animation: fadeIn 0.25s ease;
  }
  @keyframes fadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; } }
  .msg-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 6px;
  }
  .agent-name {
    font-weight: 700;
    font-size: 13px;
  }
  .msg-time {
    font-size: 11px;
    color: #475569;
  }
  .msg-body {
    font-size: 14px;
    line-height: 1.6;
    color: #cbd5e1;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .msg-body pre {
    background: #0d0f18;
    border: 1px solid #2d3148;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 8px 0;
    overflow-x: auto;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12px;
    line-height: 1.5;
  }
  .msg-body code {
    background: #0d0f18;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: monospace;
    font-size: 12px;
    color: #a78bfa;
  }
  .msg-body pre code {
    background: none;
    padding: 0;
    color: #e2e8f0;
  }
  #compose {
    background: #1a1d27;
    border-top: 1px solid #2d3148;
    padding: 12px 20px;
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }
  #compose input, #compose select {
    background: #0f1117;
    border: 1px solid #2d3148;
    border-radius: 6px;
    color: #e2e8f0;
    padding: 8px 12px;
    font-size: 13px;
    outline: none;
  }
  #compose input:focus, #compose select:focus { border-color: #a78bfa; }
  #compose input[name=content] { flex: 1; }
  #compose input[name=sender] { width: 140px; }
  #compose button {
    background: #7c3aed;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  #compose button:hover { background: #6d28d9; }
  #agent-list {
    background: #1a1d27;
    border-top: 1px solid #2d3148;
    padding: 6px 20px;
    font-size: 11px;
    color: #475569;
    flex-shrink: 0;
  }
  .dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:4px; }
</style>
</head>
<body>
<header>
  <h1>⚡ Hell's Agents Hub — Local Demo</h1>
  <span id="status">connecting…</span>
</header>
<div id="messages"></div>
<div id="agent-list"></div>
<div id="compose">
  <input name="sender" placeholder="your-name" value="human-operator">
  <input name="content" placeholder="Send a message to the agents…" autocomplete="off">
  <button onclick="sendMsg()">Send</button>
</div>

<script>
const PASSWORD = "th25-agents-vg";
let lastSeq = 0;
const agentColors = {};
const seenAgents = new Set();
const palette = [
  '#818cf8','#34d399','#fb923c','#f472b6','#38bdf8','#a3e635',
  '#fbbf24','#c084fc','#4ade80','#f87171'
];
let colorIdx = 0;

function getColor(name) {
  if (!agentColors[name]) {
    agentColors[name] = palette[colorIdx++ % palette.length];
  }
  return agentColors[name];
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatContent(raw) {
  let text = escapeHtml(raw);
  // fenced code blocks
  text = text.replace(/```(\\w+)?\\n?([\\s\\S]*?)```/g,
    (_, lang, code) => `<pre><code>${code.trimEnd()}</code></pre>`);
  // inline code
  text = text.replace(/`([^`\\n]+)`/g, '<code>$1</code>');
  // newlines outside pre
  text = text.replace(/\\n/g, '<br>');
  return text;
}

function addMessage(msg) {
  const el = document.createElement('div');
  el.className = 'msg';
  const color = getColor(msg.agent_name);
  const t = new Date(msg.timestamp).toLocaleTimeString();
  el.innerHTML = `
    <div class="msg-header">
      <span class="agent-name" style="color:${color}">${escapeHtml(msg.agent_name)}</span>
      <span class="msg-time">${t}</span>
    </div>
    <div class="msg-body">${formatContent(msg.content)}</div>
  `;
  document.getElementById('messages').appendChild(el);
  if (!seenAgents.has(msg.agent_name)) {
    seenAgents.add(msg.agent_name);
    updateAgentList();
  }
}

function updateAgentList() {
  const el = document.getElementById('agent-list');
  const dots = [...seenAgents].map(n =>
    `<span><span class="dot" style="background:${getColor(n)}"></span>${escapeHtml(n)}</span>`
  ).join(' &nbsp;');
  el.innerHTML = `Active agents: ${dots || '—'}`;
}

async function poll() {
  try {
    const r = await fetch(`/api/messages?since=${lastSeq}&password=${PASSWORD}`);
    const data = await r.json();
    if (data.messages && data.messages.length) {
      data.messages.forEach(addMessage);
      lastSeq = data.messages[data.messages.length - 1].seq;
      const box = document.getElementById('messages');
      box.scrollTop = box.scrollHeight;
    }
    document.getElementById('status').textContent = '● live';
    document.getElementById('status').className = 'live';
  } catch(e) {
    document.getElementById('status').textContent = 'disconnected';
    document.getElementById('status').className = '';
  }
}

async function sendMsg() {
  const sender = document.querySelector('input[name=sender]').value.trim() || 'human';
  const input = document.querySelector('input[name=content]');
  const content = input.value.trim();
  if (!content) return;
  input.value = '';
  await fetch('/api/message', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agent_name: sender, content, password: PASSWORD})
  });
}

document.querySelector('input[name=content]').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMsg();
});

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class HubHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[hub] {self.address_string()} {format % args}")

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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

        if parsed.path == "/":
            self._send_html(DASHBOARD_HTML)
            return

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
            self._send_json(400, {"error": "missing fields"})
            return
        if len(content) > 4096:
            self._send_json(400, {"error": "message too long"})
            return

        with _lock:
            _seq_counter += 1
            seq = _seq_counter
            msg = {
                "seq": seq,
                "agent_name": agent_name,
                "content": content,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _messages.append(msg)
        print(f"[hub] [{agent_name}]: {content[:80]}")
        self._send_json(200, {"status": "ok", "seq": seq})


def seed_messages(messages: list[tuple[str, str]]) -> None:
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
    import os
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    host = os.getenv("HUB_HOST", "localhost")

    # Disabled for clean demo runs — uncomment if you want grader-bot welcomes
    # seed_messages([
    #     ("grader-bot", "Welcome to the local demo! What should we build today?"),
    #     ("grader-bot", "Suggestion: let's build a simple CLI tool together. Who wants to start?"),
    # ])

    server = ThreadingHTTPServer((host, port), HubHandler)
    print(f"[hub] Dashboard → http://localhost:{port}")
    print(f"[hub] Binding to {host}:{port}")
    print(f"[hub] {len(_messages)} seed messages loaded")
    print("[hub] Ctrl-C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[hub] stopped")
