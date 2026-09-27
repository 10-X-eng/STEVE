"""Bundled-runtime jobs with a local inference fixture; no paid calls or Fusion edits."""
import json
from pathlib import Path
import tempfile
import sys
import traceback
import unittest
from unittest.mock import patch

from test_core import eventually
from test_grok_runtime import HAS_RUNTIME, Stream
from steve.controller import Controller, CONTEXT_PREFIX
from steve.debug_log import DebugLog
from steve.grok_transport import GrokGateway, GrokTransport
from steve.preferences import ProviderChoice


@unittest.skipUnless(HAS_RUNTIME, "Fetch the bundled runtime first")
class JobRuntimeTests(unittest.TestCase):
    def test_budget_continuation_pause_resume_completion_and_persistence(self):
        requests, events = [], []
        phase = ["budget"]
        completed_tool = [False]
        class Fusion:
            pending = None
            def submit(self, tool, args, complete, cancelled):
                if phase[0] == "pause":
                    self.pending = (complete, cancelled)
                else:
                    self.assert_active = not cancelled()
                    complete({"ok": True, "name": "Fixture bracket", "document_id": "fixture"})
        fusion = Fusion()
        def upstream(request, timeout):
            body = json.loads(request.data)
            requests.append(body)
            index = len(requests)
            if index == 1 or phase[0] == "pause":
                item = {"type": "function_call", "name": "fusion_inspect_document", "arguments": "{}"}
            elif phase[0] == "complete" and not completed_tool[0]:
                completed_tool[0] = True
                item = {"type": "function_call", "name": "update_goal", "arguments": '{"status":"complete"}'}
            else:
                item = {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": "Verified fixture step.", "annotations": []}]}
            item.update(id=f"item_{index}", status="completed")
            if item["type"] == "function_call":
                item["call_id"] = f"call_{index}"
            response = {"id": f"resp_{index}", "object": "response", "status": "completed", "model": "grok-4.6",
                        "output": [item], "usage": {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}}
            packets = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                       {"type": "response.output_item.added", "output_index": 0, "item": item},
                       {"type": "response.output_item.done", "output_index": 0, "item": item},
                       {"type": "response.completed", "response": response}]
            return Stream("".join("data: " + json.dumps(packet) + "\n\n" for packet in packets).encode())
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            ProviderChoice(home).save("grok")
            def factory(notify):
                def event(method, params):
                    events.append((method, params))
                    notify(method, params)
                client = GrokTransport(event, home=home)
                client.auth.access_token = lambda force=False: "fixture-token"
                client.auth.account = lambda refresh=False: {"type": "grok", "id": "fixture", "email": "Fixture"}
                client.auth.models = lambda: {"data": [{"id": "grok-4.6", "isDefault": True, "displayName": "Fixture",
                    "defaultReasoningEffort": "high", "supportedReasoningEfforts": [{"reasoningEffort": "high"}]}]}
                return client
            def connect():
                controller = Controller(lambda _: None, grok_factory=factory, debug_log=DebugLog(home), fusion_tools=fusion)
                controller.dispatch("connect")
                try:
                    # Allow the transport's initialization deadline to finish.
                    eventually(lambda: bool(controller.state["models"] or controller.state["error"]), 35)
                    self.assertTrue(controller.state["models"], controller.state["error"])
                except BaseException as error:
                    state = {key: controller.state[key] for key in
                             ("provider", "connection", "accountChecked", "status", "error", "models", "busy")}
                    frame = sys._current_frames().get(controller._worker.ident)
                    stack = "".join(traceback.format_stack(frame)) if frame else "Worker exited"
                    controller.close()
                    controller._worker.join(5)
                    raise AssertionError(f"Runtime fixture did not connect: {state}\n{stack}") from error
                return controller
            def idle(controller, status):
                eventually(lambda: controller.state["job"] and controller.state["job"]["status"] == status
                           and not controller.state["busy"] and not controller.state["jobBusy"], 15)
                self.assertFalse(controller.state["error"], controller.state["error"])
            with patch("steve.grok_transport.GrokGateway", side_effect=lambda auth: GrokGateway(auth, opener=upstream)):
                controller = connect()
                try:
                    controller.dispatch("job", {"command": "set", "objective": "Inspect the fixture", "tokenBudget": 100},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture bracket", "task_key": "fixture-key"})
                    idle(controller, "budgetLimited")
                    self.assertEqual(len(requests), 4)
                    self.assertTrue(fusion.assert_active)
                    self.assertGreaterEqual(sum(m == "turn/started" for m, _ in events), 3)
                    tools = {t.get("name") for t in requests[0]["tools"]}
                    self.assertTrue({"create_goal", "get_goal", "update_goal"} <= tools)
                    self.assertIn(CONTEXT_PREFIX, json.dumps(requests[0]).replace("\\n", "\n"))
                    self.assertTrue(all(r.get("reasoning", {}).get("effort") == "high" for r in requests))
                    phase[0] = "pause"
                    controller.dispatch("job", {"command": "resume", "tokenBudget": None},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture bracket", "task_key": "fixture-key"})
                    eventually(lambda: fusion.pending is not None and not controller.state["jobBusy"], 10)
                    # Pause only the goal, leaving a real dynamic-tool call in flight.
                    controller._job_rpc('set', {'status':'paused'})
                    turn = controller.turn_id
                    request_count = len(requests)
                    event_count = sum(m == 'turn/started' for m, _ in events)
                    controller.dispatch('job', {'command':'resume'},
                        capture_context=lambda _: self.fail('Mid-turn resume must not rebind Fusion'))
                    eventually(lambda: not controller.state['jobBusy'], 10)
                    self.assertEqual(controller.state['job']['status'], 'active')
                    self.assertEqual(controller.turn_id, turn)
                    self.assertEqual(len(requests), request_count)
                    self.assertEqual(sum(m == 'turn/started' for m, _ in events), event_count)
                    self.assertFalse(fusion.pending[1]())
                    controller.dispatch("stop")
                    idle(controller, "paused")
                    self.assertIsNone(controller.state["job"]["tokenBudget"])
                    complete, cancelled = fusion.pending
                    self.assertTrue(cancelled())
                    complete({"ok": False, "error": "Stopped fixture"})
                    phase[0] = "complete"
                    controller.dispatch("job", {"command": "resume"},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture bracket", "task_key": "fixture-key"})
                    idle(controller, "complete")
                    thread = controller.thread_id
                    self.assertTrue(completed_tool[0])
                finally:
                    controller.close()
                    controller._worker.join(5)
                controller = connect()
                try:
                    eventually(lambda: any(t["id"] == thread for t in controller.state["history"]), 10)
                    controller.dispatch("openHistory", {"threadId": thread})
                    eventually(lambda: controller.thread_id == thread and not controller.state["busy"], 10)
                    self.assertEqual(controller.state["job"]["status"], "complete")
                    self.assertEqual(controller.state["job"]["objective"], "Inspect the fixture")
                    controller.dispatch("job", {"command": "set", "objective": "Verify revised fixture", "tokenBudget": 75},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture bracket", "task_key": "fixture-key"})
                    idle(controller, "budgetLimited")
                    self.assertEqual(controller.state["job"]["tokensUsed"], 75,
                        [(m, p) for m, p in events if m == "thread/goal/updated"][-7:])
                    self.assertIn("Verify revised fixture", json.dumps(requests[-1]))
                    self.assertIn("Inspect the fixture", json.dumps(requests[-1]))
                    count = len(requests)
                    controller.dispatch("job", {"command": "clear"})
                    eventually(lambda: controller.state["job"] is None and not controller.state["jobBusy"])
                    self.assertEqual(len(requests), count)
                    # Leave an active job on disk, as after an app shutdown.
                    phase[0] = "pause"
                    fusion.pending = None
                    controller.dispatch("job", {"command": "set", "objective": "Check saved active job"},
                        capture_context=lambda _: {"document_id": "fixture", "name": "Fixture bracket", "task_key": "fixture-key"})
                    eventually(lambda: fusion.pending is not None and not controller.state["jobBusy"], 10)
                finally:
                    controller.close()
                    controller._worker.join(5)
                count = len(requests)
                controller = connect()
                try:
                    eventually(lambda: any(t["id"] == thread for t in controller.state["history"]), 10)
                    controller.dispatch("openHistory", {"threadId": thread})
                    eventually(lambda: controller.thread_id == thread and not controller.state["busy"], 10)
                    self.assertEqual(controller.state["job"]["status"], "paused")
                    self.assertEqual(len(requests), count)
                    self.assertFalse(controller.state["jobHasTarget"])
                finally:
                    controller.close()
                    controller._worker.join(5)


if __name__ == "__main__":
    unittest.main()
