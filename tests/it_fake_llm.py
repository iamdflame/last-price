"""A local fake OpenAI-compatible endpoint. Logs every chat request (JSON lines) to argv[2]."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
LOG = sys.argv[2]
REPLY = "Hi! I'm the seller's assistant. It's $420; I can do $410 if you like."


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json({"object": "list", "data": [{"id": "fake-model", "object": "model",
                                                           "context_length": 128000}]})
        return self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json({"error": "nope"}, 404)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "messages": req.get("messages", [])}) + "\n")
        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            base = {"id": "c1", "object": "chat.completion.chunk", "created": int(time.time()), "model": "fake-model"}
            for chunk in (
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": REPLY}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}},
            ):
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        return self._json({"id": "c1", "object": "chat.completion", "created": int(time.time()), "model": "fake-model",
                           "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY},
                                        "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
