"""Job lifecycle at STEVE's controller boundary, including automatic turns."""
import copy
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_core import FakeClient, ROOT, eventually
from steve.controller import Controller, thread_start_params, CONTEXT_PREFIX
from steve.debug_log import DebugLog
from steve.jobs import job_command, validate_job


class JobClient(FakeClient):
    def __init__(self, notify):
        super().__init__(notify)
        self.job = None
        self.turn_number = 0
        self.turn_active = False

    def start_job_turn(self):
        self.turn_active = True
        self.turn_number += 1
        self.notify("turn/started", {"threadId": "thread-1", "turn": {"id": f"job-turn-{self.turn_number}"}})

    def complete(self, status="completed"):
        self.turn_active = False
        self.notify("turn/completed", {"threadId": "thread-1", "turn": {
            "id": f"job-turn-{self.turn_number}", "status": status}})

    def request(self, method, params=None, **kwargs):
        if not method.startswith("thread/goal/"):
            return super().request(method, params, **kwargs)
        self.calls.append((method, copy.deepcopy(params)))
        if method == self.fail_method:
            raise RuntimeError("Job service unavailable")
        if method == "thread/goal/get":
            return {"goal": copy.deepcopy(self.job)}
        if method == "thread/goal/clear":
            self.job = None
            self.notify("thread/goal/cleared", {"threadId": params["threadId"]})
            return {}
        if "objective" in params:
            self.job = {"threadId": params["threadId"], "objective": params["objective"],
                         "status": "paused", "tokensUsed": 0, "timeUsedSeconds": 0, "tokenBudget": None}
        self.job.update({k: v for k, v in params.items() if k in ("status", "tokenBudget")})
        result = copy.deepcopy(self.job)
        self.notify("thread/goal/updated", {"threadId": params["threadId"], "goal": copy.deepcopy(self.job)})
        if self.job["status"] == "active" and not self.turn_active:
            self.start_job_turn()
        return {"goal": result}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller(lambda s: None, transport_factory=JobClient,
            debug_log=DebugLog(ROOT / ".cache" / "job-tests" / str(uuid4())))
        self.controller.dispatch("connect")
        eventually(lambda: bool(self.controller.snapshot()["models"]))
        self.client = self.controller.client
        self.captures = []

    def tearDown(self):
        self.controller.close()
        self.controller._worker.join(2)

    def capture(self, action):
        self.captures.append(action)
        return {"document_id": "doc-a", "name": "Bracket", "task_key": "binding-a", "selectionCount": 2}

    def create(self):
        self.controller.dispatch("send", {"text": "/jobs Make a bracket and verify its dimensions"}, capture_context=self.capture)
        eventually(lambda: self.controller.turn_id == "job-turn-1" and not self.controller.state["jobBusy"])

    def pause_goal_without_interrupting(self):
        self.client.job['status'] = 'paused'
        self.client.notify('thread/goal/updated', {'threadId':'thread-1','goal':copy.deepcopy(self.client.job)})

    def test_resume_running_tool_activates_goal_without_rebinding_or_new_turn(self):
        self.create()
        self.pause_goal_without_interrupting()
        pending = []
        class Fusion:
            def submit(self, tool, args, complete, cancelled):
                pending.append((complete, cancelled))
        self.controller.fusion_tools = Fusion()
        self.client.on_request('tool', 'item/tool/call', {'threadId':'thread-1','turnId':'job-turn-1',
            'tool':'fusion_inspect_document','arguments':{}})
        context = copy.deepcopy(self.controller._task_context)
        start = len(self.client.calls)
        self.controller.dispatch('steer', {'text':'/jobs resume'}, capture_context=lambda _: self.fail('Must not rebind a running tool'))
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertEqual(self.client.job['status'], 'active')
        self.assertEqual(self.controller.turn_id, 'job-turn-1')
        self.assertEqual(self.controller._task_context, context)
        self.assertFalse(pending[0][1]())
        self.assertEqual([m for m, _ in self.client.calls[start:]], ['thread/goal/set'])
        pending[0][0]({'ok':True})
        self.client.complete()
        self.assertTrue(self.controller.state['busy'])
        self.client.start_job_turn()
        self.assertEqual(self.controller.turn_id, 'job-turn-2')

    def test_resume_different_target_waits_then_restores_original_binding_and_budget(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._task_context = {'task_key':'binding-b','document_id':'doc-b'}
        self.controller.state['taskDocument'] = {'id':'doc-b','name':'Other'}
        self.controller.dispatch('job', {'command':'resume','tokenBudget':1200}, capture_context=self.capture)
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertTrue(self.controller.state['jobResumePending'])
        self.controller.resume_pending_job(self.capture)
        self.assertEqual(self.captures, ['send'])
        self.assertEqual(self.controller._task_context['task_key'], 'binding-b')
        self.assertEqual(self.client.job['status'], 'paused')
        self.client.complete()
        self.controller.resume_pending_job(self.capture)
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertEqual(self.controller.turn_id, 'job-turn-2')
        self.assertEqual(self.captures, ['send', 'resume:binding-a'])
        self.assertEqual(self.controller.state['taskDocument']['id'], 'doc-a')
        self.assertEqual(self.client.job['tokenBudget'], 1200)
        self.assertFalse(self.controller.state['jobResumePending'])

    def test_resume_while_stopping_preserves_cancellation_until_idle(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._cancel = True
        self.controller.dispatch('job', {'command':'resume'}, capture_context=self.capture)
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertTrue(self.controller._cancel)
        self.assertTrue(self.controller.state['jobResumePending'])
        self.client.complete('interrupted')
        self.controller.resume_pending_job(self.capture)
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertFalse(self.controller._cancel)
        self.assertEqual(self.client.job['status'], 'active')

    def test_stop_cancels_deferred_resume(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._task_context = {'task_key':'binding-b'}
        self.controller.dispatch('job', {'command':'resume'})
        eventually(lambda: not self.controller.state['jobBusy'])
        self.controller.dispatch('stop')
        eventually(lambda: not self.controller.state['busy'])
        self.controller.resume_pending_job(self.capture)
        self.assertFalse(self.controller.state['jobResumePending'])
        self.assertEqual(self.client.job['status'], 'paused')
        self.assertEqual(self.client.turn_number, 1)

    def test_deferred_resume_closed_target_reports_error_without_activation(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._task_context = {'task_key':'binding-b'}
        self.controller.dispatch('job', {'command':'resume'})
        eventually(lambda: not self.controller.state['jobBusy'])
        self.client.complete()
        def closed(_):
            raise ValueError('The original document is closed')
        self.controller.resume_pending_job(closed)
        self.assertIn('original document is closed', self.controller.state['error'])
        self.assertEqual(self.client.job['status'], 'paused')
        self.assertFalse(self.controller.state['jobResumePending'])

    def test_failed_active_resume_preserves_turn_and_paused_job(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.client.fail_method = 'thread/goal/set'
        self.controller.dispatch('job', {'command':'resume'})
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertEqual(self.controller.turn_id, 'job-turn-1')
        self.assertTrue(self.controller.state['busy'])
        self.assertFalse(self.controller._cancel)
        self.assertEqual(self.client.job['status'], 'paused')
        self.assertIn('Job service unavailable', self.controller.state['error'])

    def test_stop_supersedes_a_resume_waiting_on_the_controller_worker(self):
        self.create()
        self.pause_goal_without_interrupting()
        entered, release = threading.Event(), threading.Event()
        original = self.controller._job_action
        def held(payload):
            entered.set()
            release.wait(2)
            return original(payload)
        start = len(self.client.calls)
        with patch.object(self.controller, '_job_action', side_effect=held):
            self.controller.dispatch('job', {'command':'resume'})
            self.assertTrue(entered.wait(1))
            self.controller.dispatch('stop')
            release.set()
            eventually(lambda: not self.controller.state['jobBusy'] and not self.controller.state['busy'])
        self.assertFalse(any(m == 'thread/goal/set' and p.get('status') == 'active' for m, p in self.client.calls[start:]))
        self.assertEqual(self.client.job['status'], 'paused')

    def test_fusion_state_event_delivers_deferred_resume_even_with_palette_closed(self):
        from test_clipboard_bridge import load_entry
        from types import SimpleNamespace
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._task_context = {'task_key':'binding-b'}
        self.controller.dispatch('job', {'command':'resume'})
        eventually(lambda: not self.controller.state['jobBusy'])
        self.client.complete()
        entry = load_entry()
        entry._controller = self.controller
        entry._fusion_tools = SimpleNamespace(message_context=self.capture)
        entry._pending_state = self.controller.snapshot()
        entry.StateEvent().notify(None)
        eventually(lambda: not self.controller.state['jobBusy'])
        self.assertEqual(self.captures[-1], 'resume:binding-a')
        self.assertEqual(self.controller.turn_id, 'job-turn-2')

    def test_disconnect_drops_pending_resume(self):
        self.create()
        self.pause_goal_without_interrupting()
        self.controller._task_context = {'task_key':'binding-b'}
        self.controller.dispatch('job', {'command':'resume'})
        eventually(lambda: not self.controller.state['jobBusy'])
        self.client.notify('steve/disconnected', {'message':'Fixture disconnected'})
        self.assertFalse(self.controller.state['jobResumePending'])
        self.assertIsNone(self.controller._pending_job_resume)

    def test_commands_and_validation(self):
        for word in ("pause", "resume", "clear", "edit", "help", "status"):
            self.assertEqual(job_command("/jobs " + word), {"command": word})
        self.assertEqual(job_command("/jobs"), {"command": "status"})
        self.assertEqual(job_command("/jobs edit Revised job"), {"command": "set", "objective": "Revised job"})
        self.assertIsNone(job_command("Explain /jobs"))
        self.assertIsNone(job_command("/jobskeeper"))
        for invalid in ("", "x" * 4001):
            with self.assertRaises(ValueError):
                validate_job({"command": "set", "objective": invalid})
        for budget in (0, -1, True, "200", 1.5, 2**53):
            with self.assertRaises(ValueError):
                validate_job({"command": "resume", "tokenBudget": budget})
        self.assertTrue(thread_start_params(ROOT)["config"]["features.goals"])

    def test_creation_injects_context_before_activation_and_continues_on_original_target(self):
        self.create()
        methods = [m for m, _ in self.client.calls]
        self.assertNotIn("turn/start", methods)  # Codex starts the job turn itself.
        injection = next(p for m, p in self.client.calls if m == "thread/inject_items")
        self.assertTrue(injection["items"][0]["content"][1]["text"].startswith(CONTEXT_PREFIX))
        self.assertEqual(self.captures, ["send"])
        self.assertEqual(self.controller.state["taskDocument"]["id"], "doc-a")
        self.client.complete()
        self.assertTrue(self.controller.state["busy"])
        self.assertFalse(self.controller.snapshot()["canSteer"])
        self.client.start_job_turn()
        self.assertTrue(self.controller.snapshot()["canSteer"])
        self.assertEqual(self.controller.state["taskDocument"]["id"], "doc-a")
        calls = []
        class Fusion:
            def submit(self, tool, args, complete, cancelled):
                calls.append(cancelled())
                complete({"ok": True})
        self.controller.fusion_tools = Fusion()
        self.client.on_request("inspect", "item/tool/call", {"threadId": "thread-1", "turnId": "job-turn-2",
            "tool": "fusion_inspect_document", "arguments": {}})
        self.assertEqual(calls, [False])

    def test_pause_resume_clear_and_stop_use_native_job_state(self):
        self.create()
        self.controller.dispatch("steer", {"text": "/jobs pause"})
        eventually(lambda: not self.controller.state["jobBusy"] and not self.controller.state["busy"])
        self.assertEqual(self.client.job["status"], "paused")
        self.assertLess(next(i for i, (m,p) in enumerate(self.client.calls) if m == "thread/goal/set" and p.get("status") == "paused"),
                        next(i for i, (m,_) in enumerate(self.client.calls) if m == "turn/interrupt"))
        self.controller.dispatch("job", {"command": "resume", "tokenBudget": 1000}, capture_context=self.capture)
        eventually(lambda: self.controller.turn_id == "job-turn-2" and not self.controller.state["jobBusy"])
        self.assertEqual(self.captures[-1], "resume:binding-a")
        self.assertEqual(self.client.job["tokenBudget"], 1000)
        self.controller.dispatch("stop")
        eventually(lambda: self.client.job["status"] == "paused" and not self.controller.state["busy"])
        messages = copy.deepcopy(self.controller.state["messages"])
        self.controller.dispatch("job", {"command": "clear"})
        eventually(lambda: self.controller.state["job"] is None and not self.controller.state["jobBusy"])
        self.assertEqual(messages, self.controller.state["messages"])

    def test_stop_between_turns_and_stale_notifications_cannot_restart_work(self):
        self.create()
        self.client.complete()
        self.controller.dispatch("stop")
        self.client.start_job_turn()  # A continuation was already queued at the runtime.
        eventually(lambda: self.client.job["status"] == "paused" and not self.controller.state["busy"])
        job = copy.deepcopy(self.controller.state["job"])
        self.client.notify("thread/goal/cleared", {"threadId": "another-thread"})
        self.assertEqual(self.controller.state["job"], job)

    def test_stop_during_job_startup_never_activates_it(self):
        self.client.block_thread = True
        self.controller.dispatch("job", {"command": "set", "objective": "Build a fixture"}, capture_context=self.capture)
        self.assertTrue(self.client.entered_thread.wait(1))
        self.controller.dispatch("stop")
        self.client.release_thread.set()
        eventually(lambda: not self.controller.state["jobBusy"] and self.controller.state["job"] is not None)
        self.assertEqual(self.client.job["status"], "paused")
        self.assertFalse(any(m == "thread/goal/set" and p.get("status") == "active" for m, p in self.client.calls))

    def test_paused_job_pin_is_not_overwritten_by_a_different_chat_context(self):
        self.create()
        self.controller.dispatch("job", {"command": "pause"})
        eventually(lambda: not self.controller.state["jobBusy"] and not self.controller.state["busy"])
        self.controller._task_context = {"document_id": "doc-b", "name": "Other", "task_key": "binding-b"}
        self.client.notify("thread/goal/updated", {"threadId": "thread-1", "goal": copy.deepcopy(self.client.job)})
        self.controller.dispatch("job", {"command": "resume"}, capture_context=self.capture)
        eventually(lambda: not self.controller.state["jobBusy"] and self.controller.state["busy"])
        self.assertEqual(self.captures[-1], "resume:binding-a")

    def test_job_rpc_failure_does_not_end_running_turn_and_pause_still_interrupts(self):
        self.create()
        self.client.fail_method = "thread/goal/get"
        self.controller.dispatch("job", {"command": "status"})
        eventually(lambda: not self.controller.state["jobBusy"])
        self.assertTrue(self.controller.state["busy"])
        self.client.fail_method = "thread/goal/set"
        self.controller.dispatch("job", {"command": "pause"})
        eventually(lambda: not self.controller.state["jobBusy"] and not self.controller.state["busy"])
        self.assertTrue(self.controller._cancel)

    def test_clear_without_a_job_does_not_stop_an_ordinary_chat(self):
        self.controller.dispatch("send", {"text": "Explain a sketch"})
        eventually(lambda: self.controller.turn_id is not None)
        self.controller.dispatch("job", {"command": "clear"})
        eventually(lambda: not self.controller.state["jobBusy"])
        self.assertFalse(self.controller._cancel)
        self.assertTrue(self.controller.state["busy"])
        self.assertFalse(any(m == "turn/interrupt" for m, _ in self.client.calls))

    def test_history_pauses_saved_job_before_resuming_thread(self):
        self.client.job = {"threadId": "saved-thread", "objective": "Saved job", "status": "active"}
        self.controller.state["history"] = [{"id": "saved-thread"}]
        self.controller.dispatch("openHistory", {"threadId": "saved-thread"})
        eventually(lambda: self.controller.thread_id == "saved-thread")
        methods = [m for m, _ in self.client.calls]
        self.assertLess(methods.index("thread/goal/set"), methods.index("thread/resume"))
        self.assertEqual(self.controller.state["job"]["status"], "paused")
        self.assertFalse(self.controller.state["jobHasTarget"])

    def test_paused_job_becomes_resumable_on_idle_even_without_turn_completed(self):
        for idle_first in (False, True):
            with self.subTest(idle_first=idle_first):
                self.client.job = None
                self.controller.state['job'] = None
                self.controller.state['busy'] = False
                self.controller.turn_id = None
                self.client.turn_number = 0
                self.client.turn_active = False
                self.create()
                def idle():
                    self.client.turn_active = False
                    self.client.notify('thread/status/changed', {'threadId':'thread-1','status':{'type':'idle'}})
                if idle_first:
                    idle()
                    self.assertTrue(self.controller.state['busy'])  # Active jobs still continue.
                self.client.job['status'] = 'paused'
                self.client.notify('thread/goal/updated', {'threadId':'thread-1','goal':copy.deepcopy(self.client.job)})
                if not idle_first:
                    self.assertTrue(self.controller.state['busy'])  # Pause is not proof the turn ended.
                    idle()
                self.assertFalse(self.controller.state['busy'])
                self.assertIsNone(self.controller.turn_id)
                self.controller.dispatch('job', {'command':'resume'}, capture_context=self.capture)
                eventually(lambda: self.controller.turn_id == 'job-turn-2' and not self.controller.state['jobBusy'])
                self.assertEqual(self.captures[-1], 'resume:binding-a')

    def test_open_job_refresh_recovers_idle_state_and_ignores_racing_new_turn(self):
        self.create()
        self.client.job['status'] = 'paused'
        self.client.notify('thread/goal/updated', {'threadId':'thread-1','goal':copy.deepcopy(self.client.job)})
        request = self.client.request
        def read(method, params=None, **kwargs):
            if method == 'thread/read':
                self.assertFalse(params['includeTurns'])
                return {'thread':{'status':{'type':'idle'}}}
            return request(method, params, **kwargs)
        with patch.object(self.client, 'request', side_effect=read):
            self.controller.dispatch('job', {'command':'status'})
            eventually(lambda: not self.controller.state['jobBusy'])
        self.assertFalse(self.controller.state['busy'])
        self.client.start_job_turn()
        def racing_read(method, params=None, **kwargs):
            if method == 'thread/read':
                self.client.start_job_turn()
                return {'thread':{'status':{'type':'idle'}}}
            return request(method, params, **kwargs)
        with patch.object(self.client, 'request', side_effect=racing_read):
            self.controller.dispatch('job', {'command':'status'})
            eventually(lambda: not self.controller.state['jobBusy'])
        self.assertTrue(self.controller.state['busy'])
        self.assertEqual(self.controller.turn_id, 'job-turn-3')

    def test_idle_notification_never_releases_running_fusion_work_or_other_thread(self):
        self.create()
        self.client.job['status'] = 'paused'
        self.client.notify('thread/goal/updated', {'threadId':'thread-1','goal':copy.deepcopy(self.client.job)})
        self.client.notify('thread/status/changed', {'threadId':'other','status':{'type':'idle'}})
        self.assertTrue(self.controller.state['busy'])
        self.controller._active_tools['fixture'] = (self.client, self.controller.thread_id, self.controller.turn_id, {'label':'Fixture tool'})
        self.client.notify('thread/status/changed', {'threadId':'thread-1','status':{'type':'idle'}})
        self.assertTrue(self.controller.state['busy'])
        self.assertEqual(self.controller.turn_id, 'job-turn-1')
        self.controller._active_tools.clear()


if __name__ == "__main__":
    unittest.main()
