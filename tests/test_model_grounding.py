from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.core as core


class RuntimeModelGroundingAcceptanceTests(unittest.TestCase):
    """Acceptance boundary for optional model rewording of deterministic facts.

    The endpoint is configured only with inert test values and every call to
    ``urlopen`` is mocked. Mutable paths are also redirected to a temporary
    directory in case future validation adds local audit output.
    """

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory(prefix="payproof-model-grounding-")
        self.temp_root = Path(self.temp_directory.name).resolve()
        self.runtime_dir = self.temp_root / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.path_patchers = [
            patch.object(core, "RUNTIME_DIR", self.runtime_dir),
            patch.object(core, "DB_PATH", self.runtime_dir / "model-grounding.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", self.runtime_dir / "prism-queue.jsonl"),
        ]
        for patcher in self.path_patchers:
            patcher.start()
        self.environment_patch = patch.dict(
            os.environ,
            {
                "PAYPROOF_MODEL_BASE_URL": "https://model.invalid/v1",
                "PAYPROOF_MODEL_API_KEY": "test-only-key",
                "PAYPROOF_MODEL": "grounding-test-model",
            },
            clear=False,
        )
        self.environment_patch.start()

    def tearDown(self) -> None:
        self.environment_patch.stop()
        for patcher in reversed(self.path_patchers):
            patcher.stop()
        self.temp_directory.cleanup()

    @staticmethod
    def partial_control_result() -> core.ChatResult:
        return core.ChatResult(
            answer=(
                "Partially. Policy requires MFA, but 16 of 18 production identities are enrolled; "
                "two service accounts are exempt. Confidence: 96%. Evidence conflict or gap: "
                "the written requirement and observed enrollment do not fully agree. "
                "Evidence: SEC-POL-001 and SEC-INF-001."
            ),
            evidence_ids=["SEC-POL-001", "SEC-INF-001"],
            focus_ids=["control:CTRL-MFA", "security:SEC-POL-001", "security:SEC-INF-001"],
            calculation={
                "control_id": "CTRL-MFA",
                "status": "partial",
                "confidence": 96,
                "enrolled": 16,
                "identities": 18,
                "exempt_service_accounts": 2,
                "evidence_count": 2,
            },
        )

    @staticmethod
    def unknown_result() -> core.ChatResult:
        return core.ChatResult(
            answer=(
                "Unknown. The loaded evidence does not establish SOC 2 compliance. "
                "The available report SEC-AUDIT-001 expired on 2026-08-31, so confidence is 70%."
            ),
            evidence_ids=["SEC-AUDIT-001"],
            focus_ids=["security:SEC-AUDIT-001"],
            calculation={
                "status": "unknown",
                "confidence": 70,
                "report_expired_on": "2026-08-31",
                "evidence_count": 1,
            },
        )

    @staticmethod
    def response_with_content(content) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")
        return response

    def call_model(self, deterministic: core.ChatResult, content):
        response = self.response_with_content(content)
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            rewritten, status = core.explain_with_runtime_model("Explain this result", deterministic)
        urlopen.assert_called_once()
        return rewritten, status

    def assert_validation_fallback(
        self,
        deterministic: core.ChatResult,
        rewritten: core.ChatResult,
        status: dict,
    ) -> None:
        self.assertEqual(rewritten, deterministic)
        self.assertNotEqual(status["state"], "live_model")

    def test_rejects_new_numbers_even_when_authoritative_facts_are_retained(self) -> None:
        deterministic = self.partial_control_result()
        malicious = (
            "Partially. Policy requires MFA, but 16 of 18 production identities are enrolled; "
            "two service accounts are exempt. Confidence remains 96%. The written requirement "
            "and observed enrollment conflict. Evidence: SEC-POL-001 and SEC-INF-001. "
            "Remediation will take 30 days and raise coverage to 99%."
        )
        rewritten, status = self.call_model(deterministic, malicious)
        self.assert_validation_fallback(deterministic, rewritten, status)

    def test_rejects_unsupported_compliance_claim(self) -> None:
        deterministic = self.unknown_result()
        malicious = (
            "SOC 2 compliant. SEC-AUDIT-001 expired on 2026-08-31, and confidence is 70%. "
            "The organization nevertheless meets the certification standard."
        )
        rewritten, status = self.call_model(deterministic, malicious)
        self.assert_validation_fallback(deterministic, rewritten, status)

    def test_rejects_loss_of_unknown_or_conflict_uncertainty(self) -> None:
        cases = [
            (
                self.unknown_result(),
                "The organization is not SOC 2 certified. SEC-AUDIT-001 expired on 2026-08-31; confidence is 70%.",
                "unknown converted to a definitive negative",
            ),
            (
                self.partial_control_result(),
                "MFA is enabled for 16 of 18 production identities with 96% confidence. "
                "Evidence: SEC-POL-001 and SEC-INF-001.",
                "partial status and evidence conflict omitted",
            ),
        ]
        for deterministic, unsafe_output, label in cases:
            with self.subTest(label=label):
                rewritten, status = self.call_model(deterministic, unsafe_output)
                self.assert_validation_fallback(deterministic, rewritten, status)

    def test_model_text_cannot_override_status_calculation_or_evidence_ids(self) -> None:
        deterministic = self.partial_control_result()
        original_evidence = deepcopy(deterministic.evidence_ids)
        original_focus = deepcopy(deterministic.focus_ids)
        original_calculation = deepcopy(deterministic.calculation)
        structured_override = json.dumps({
            "answer": "Fully compliant",
            "status": "verified",
            "evidence_ids": ["SEC-FAKE-999"],
            "focus_ids": ["control:CTRL-FAKE"],
            "calculation": {"status": "compliant", "confidence": 100, "evidence_count": 99},
        })

        rewritten, status = self.call_model(deterministic, structured_override)

        self.assert_validation_fallback(deterministic, rewritten, status)
        self.assertEqual(rewritten.evidence_ids, original_evidence)
        self.assertEqual(rewritten.focus_ids, original_focus)
        self.assertEqual(rewritten.calculation, original_calculation)

    def test_rejects_malformed_or_oversized_model_output(self) -> None:
        deterministic = self.partial_control_result()
        malformed_values = [
            None,
            {"answer": deterministic.answer},
            [deterministic.answer],
            "```json\n{\"answer\": \"verified\"}\n```",
            "X" * 12_000,
        ]
        for output in malformed_values:
            with self.subTest(output_type=type(output).__name__, size=len(output) if isinstance(output, str) else None):
                rewritten, status = self.call_model(deterministic, output)
                self.assert_validation_fallback(deterministic, rewritten, status)

        malformed_response = MagicMock()
        malformed_response.__enter__.return_value.read.return_value = b"not-json"
        with patch("urllib.request.urlopen", return_value=malformed_response):
            rewritten, status = core.explain_with_runtime_model("Explain this result", deterministic)
        self.assertEqual(rewritten, deterministic)
        self.assertEqual(status["state"], "fallback_after_error")

    def test_accepts_bounded_rewording_only_when_authoritative_facts_remain(self) -> None:
        deterministic = self.unknown_result()
        grounded = (
            "Unknown: the loaded evidence does not establish SOC 2 compliance. "
            "SEC-AUDIT-001 expired on 2026-08-31, so confidence remains 70%."
        )

        rewritten, status = self.call_model(deterministic, grounded)

        self.assertEqual(status["state"], "live_model")
        self.assertEqual(rewritten.answer, grounded)
        self.assertEqual(rewritten.evidence_ids, deterministic.evidence_ids)
        self.assertEqual(rewritten.focus_ids, deterministic.focus_ids)
        self.assertEqual(rewritten.calculation, deterministic.calculation)

    def test_timeout_and_network_failure_use_exact_deterministic_fallback(self) -> None:
        deterministic = self.partial_control_result()
        failures = [TimeoutError("model timed out"), urllib.error.URLError("offline")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch("urllib.request.urlopen", side_effect=failure) as urlopen:
                    rewritten, status = core.explain_with_runtime_model("Explain this result", deterministic)
                urlopen.assert_called_once()
                self.assertEqual(rewritten, deterministic)
                self.assertEqual(status["state"], "fallback_after_error")
                self.assertEqual(status["error"], type(failure).__name__)

    def test_unconfigured_runtime_never_attempts_network(self) -> None:
        deterministic = self.partial_control_result()
        with patch.dict(
            os.environ,
            {"PAYPROOF_MODEL_BASE_URL": "", "PAYPROOF_MODEL_API_KEY": "", "PAYPROOF_MODEL": ""},
            clear=False,
        ), patch("urllib.request.urlopen") as urlopen:
            rewritten, status = core.explain_with_runtime_model("Explain this result", deterministic)
        urlopen.assert_not_called()
        self.assertEqual(rewritten, deterministic)
        self.assertEqual(status["state"], "deterministic_fallback")


if __name__ == "__main__":
    unittest.main(verbosity=2)
