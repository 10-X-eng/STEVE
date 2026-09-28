"""Real bundled Codex -> loopback OpenAI-compatible fixture -> STEVE tool -> response, without inference."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addin/STEVE"))
from steve.controller import thread_start_params
from steve.openai_compat_transport import OpenAICompatSettings, OpenAICompatTransport
from steve.transport import runtime_command, RuntimeUnavailable
from test_openai_compat import MemoryStore

try:
    runtime_command()
    HAS_RUNTIME = True
except RuntimeUnavailable:
    HAS_RUNTIME = False

KEY = "sk-fixture-openai-compat"


@unittest.skipUnless(HAS_RUNTIME, "Fetch the bundled runtime first")
class OpenAICompatRuntimeTests(unittest.TestCase):
    def test_real_runtime_sends_the_key_from_env_and_completes_a_tool_turn(self):
        requests, auth = [], []
        class Handler(BaseHTTPRequestHandler):
            def send(self, status, body, kind="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                auth.append(self.headers.get("Authorization"))
                self.send(200, json.dumps({"data": [{"id": "fixture-model", "context_length": 65536}]}).encode())
            def do_POST(self):
                auth.append(self.headers.get("Authorization"))
                if self.path != "/v1/responses" or self.headers.get("Authorization") != "Bearer " + KEY:
                    self.send(401, b'{"error":{"message":"bad key"}}')
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                item = ({"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "fusion_inspect_document",
                         "arguments": "{}", "status": "completed"} if len(requests) == 1 else
                        {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                         "content": [{"type": "output_text", "text": "Inspected.", "annotations": []}]})
                response = {"id": f"resp_{len(requests)}", "object": "response", "status": "completed", "model": body["model"],
                            "output": [item], "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}
                packets = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                           {"type": "response.output_item.added", "output_index": 0, "item": item},
                           {"type": "response.output_item.done", "output_index": 0, "item": item},
                           {"type": "response.completed", "response": response}]
                self.send(200, "".join("data: " + json.dumps(p) + "\n\n" for p in packets).encode(), "text/event-stream")
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        events, tools, done = [], [], threading.Event()
        def notify(method, params):
            events.append((method, params))
            if method == "turn/completed":
                done.set()
        with tempfile.TemporaryDirectory() as folder:
            settings = OpenAICompatSettings(folder, store=MemoryStore())
            settings.save(f"http://127.0.0.1:{server.server_port}/v1", KEY)
            client = OpenAICompatTransport(notify, home=folder)
            client.use(settings)
            client.on_request = lambda request_id, method, params: (tools.append(params), client.reply(
                request_id, {"success": True, "contentItems": [{"type": "inputText", "text": "Fixture bracket"}]}))
            try:
                client.start()
                self.assertEqual(client.request("account/read")["account"]["type"], "openai")
                thread = client.request("thread/start", thread_start_params(client.home, "openai"))["thread"]["id"]
                client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": "Inspect"}]})
                self.assertTrue(done.wait(20), str(events[-5:]))
                self.assertFalse([params for method, params in events if method == "error"])
                self.assertEqual([call["tool"] for call in tools], ["fusion_inspect_document"])
                self.assertEqual([body["model"] for body in requests], ["fixture-model", "fixture-model"])
                self.assertEqual(set(auth), {"Bearer " + KEY})
                self.assertIn(thread, [t["id"] for t in client.request("thread/list", {"cwd": str(client.home / "workspace")})["data"]])
                # Checked while the runtime runs: shell snapshots would hold the child environment.
                leaked = [p for p in Path(folder).rglob("*") if p.is_file() and KEY.encode() in p.read_bytes()]
                self.assertEqual(leaked, [])
            finally:
                client.close()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
