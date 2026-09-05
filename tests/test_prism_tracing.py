from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


class _FakeResponse:
    def __init__(self, body: dict[str, object]):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._body


class PrismTraceTests(unittest.TestCase):
    def setUp(self):
        self.test_directory = tempfile.TemporaryDirectory(prefix="payproof-prism-tests-")
        root = Path(self.test_directory.name)
        self.patchers = [
            patch.object(core, "RUNTIME_DIR", root / "runtime"),
            patch.object(core, "DB_PATH", root / "runtime" / "payproof.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", root / "runtime" / "prism_queue.jsonl"),
            patch.object(core, "BANK_CONNECTIONS_PATH", root / "runtime" / "bank-connections.json"),
            patch.object(core, "USER_INTAKE_DIR", root / "intake"),
        ]
        for patcher in self.patchers:
            patcher.start()
        core.initialize_database(reset=True)

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.test_directory.cleanup()

    @staticmethod
    def _sensitive_result() -> core.ChatResult:
        return core.ChatResult(
            "Maya Chen paid Amazon $43.57 with account ****4242; "
            "email maya@example.com and password=hunter2.",
            ["EMAIL-DEMO-007", "BANK-DEMO-P-002"],
            ["transaction:TX-AMZ-4357"],
        )

    def test_direct_delivery_uses_actual_model_and_redacts_trace_content(self):
        captured: dict[str, object] = {}

        def fake_open(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _FakeResponse({"id": "remote-trace-id"})

        question = (
            "Ask Maya Chen about Amazon $43.57, maya@example.com, account ****4242; "
            "Authorization: Bearer super-secret-token and client_secret=hunter2 "
            "using tvly-secretvalue."
        )
        environment = {
            "PRISMTRACE_PROJECT_ID": "test-project",
            "PRISMTRACE_API_KEY": "pt-sk-unit-test-secret",
            "PRISMTRACE_HOST": "https://prism.test",
        }
        with patch.dict(os.environ, environment, clear=False), \
                patch.object(core, "_prism_workspace_terms", return_value=(["Maya Chen"], ["Amazon"])), \
                patch.object(core.urllib.request, "urlopen", side_effect=fake_open):
            outcome = core.send_prism_trace(
                question,
                self._sensitive_result(),
                "session-123",
                17,
                "personal",
                {"state": "live_model", "model": "demo-live-model"},
            )

        self.assertEqual(outcome, {"state": "accepted", "trace_id": "remote-trace-id"})
        self.assertEqual(captured["timeout"], 4)
        request = captured["request"]
        payload = json.loads(request.data.decode("utf-8"))
        serialized = json.dumps(payload)
        self.assertEqual(payload["model"], "demo-live-model")
        self.assertEqual(payload["metadata"]["engine"], "live_model")
        self.assertEqual(payload["metadata"]["answer_source"], "live_model")
        self.assertTrue(payload["metadata"]["synthetic_demo"])
        self.assertEqual(payload["metadata"]["content_policy"], "minimized_and_redacted_v1")
        for secret in (
            "Maya Chen", "Amazon", "$43.57", "maya@example.com", "****4242",
            "super-secret-token", "hunter2", "tvly-secretvalue", "pt-sk-unit-test-secret",
        ):
            self.assertNotIn(secret, serialized)
        for marker in ("[EMPLOYEE]", "[VENDOR]", "[AMOUNT]", "[EMAIL]", "[ACCOUNT]", "[REDACTED_SECRET]"):
            self.assertIn(marker, serialized)
        self.assertEqual(request.get_header("X-prismtrace-key"), "pt-sk-unit-test-secret")

    def test_failed_delivery_queues_only_sanitized_payload(self):
        environment = {
            "PRISMTRACE_PROJECT_ID": "test-project",
            "PRISMTRACE_API_KEY": "pt-sk-unit-test-secret",
        }
        with patch.dict(os.environ, environment, clear=False), \
                patch.object(core, "_prism_workspace_terms", return_value=(["Maya Chen"], ["Amazon"])), \
                patch.object(core.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            outcome = core.send_prism_trace(
                "Maya Chen bought from Amazon for $43.57; access_token=access-sandbox-secretvalue",
                self._sensitive_result(),
                "session-123",
                17,
                "personal",
                {"state": "live_model", "model": "demo-live-model"},
            )

        self.assertEqual(outcome["state"], "queued")
        queued_lines = core.TRACE_QUEUE_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(queued_lines), 1)
        payload = json.loads(queued_lines[0])
        serialized = json.dumps(payload)
        self.assertEqual(payload["model"], "demo-live-model")
        self.assertEqual(payload["trace_id"], outcome["trace_id"])
        for secret in ("Maya Chen", "Amazon", "$43.57", "hunter2", "access-sandbox-secretvalue"):
            self.assertNotIn(secret, serialized)

    def test_async_submission_returns_before_network_delivery_finishes(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        captured: dict[str, object] = {}

        def slow_send(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            started.set()
            release.wait(timeout=2)
            finished.set()
            return {"state": "accepted", "trace_id": kwargs["trace_id"]}

        environment = {
            "PRISMTRACE_PROJECT_ID": "test-project",
            "PRISMTRACE_API_KEY": "pt-sk-unit-test-secret",
        }
        model_status = {"state": "live_model", "model": "demo-live-model"}
        with patch.dict(os.environ, environment, clear=False), patch.object(core, "send_prism_trace", side_effect=slow_send):
            began = time.perf_counter()
            outcome = core.trace_chat_async(
                "What changed?", core.ChatResult("Nothing.", [], []),
                "session-123", 11, "business", model_status,
            )
            elapsed = time.perf_counter() - began
            self.assertTrue(started.wait(timeout=1))
            self.assertFalse(finished.is_set())
            release.set()
            self.assertTrue(finished.wait(timeout=1))

        self.assertLess(elapsed, 0.5)
        self.assertEqual(outcome["state"], "submitted")
        self.assertFalse(outcome["accepted"])
        self.assertEqual(outcome["delivery"], "background")
        self.assertEqual(captured["args"][5], model_status)
        self.assertEqual(captured["kwargs"]["trace_id"], outcome["trace_id"])

    def test_unconfigured_async_trace_starts_no_worker(self):
        environment = {"PRISMTRACE_PROJECT_ID": "", "PRISMTRACE_API_KEY": ""}
        with patch.dict(os.environ, environment, clear=False), patch.object(core.threading, "Thread") as thread:
            outcome = core.trace_chat_async(
                "Question", core.ChatResult("Answer", [], []),
                "session-123", 4, "business",
            )
        self.assertEqual(outcome["state"], "not_configured")
        self.assertFalse(outcome["accepted"])
        thread.assert_not_called()

    def test_chat_route_passes_model_status_to_async_trace(self):
        client = app_module.app.test_client()
        deterministic = core.ChatResult(
            "The latest transaction is TX-1.", ["SRC-1"], ["transaction:TX-1"],
        )
        rewritten = core.ChatResult(
            "Your latest transaction is TX-1.", ["SRC-1"], ["transaction:TX-1"],
        )
        model_status = {"state": "live_model", "model": "demo-live-model"}
        trace_status = {
            "state": "submitted", "trace_id": "trace-1",
            "accepted": False, "delivery": "background",
        }
        with patch.object(app_module, "answer_question", return_value=deterministic), \
                patch.object(app_module, "explain_with_runtime_model", return_value=(rewritten, model_status)), \
                patch.object(app_module, "record_chat_turn") as record, \
                patch.object(app_module, "trace_chat_async", return_value=trace_status) as trace:
            response = client.post("/api/chat", json={
                "workspace": "business",
                "session_id": "session-123",
                "question": "What was the latest transaction?",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["trace"], trace_status)
        record.assert_called_once_with("session-123", "business", "What was the latest transaction?", rewritten)
        trace.assert_called_once()
        self.assertEqual(trace.call_args.args[5], model_status)


if __name__ == "__main__":
    unittest.main()
