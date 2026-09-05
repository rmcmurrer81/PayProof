from __future__ import annotations

import io
import unittest

from tools.ai_conversation_eval import (
    EvaluationResult,
    print_report,
    run_evaluation,
    sanitize_for_report,
)


class AIConversationEvaluationTests(unittest.TestCase):
    """Multi-turn release checks over an isolated Flask/SQLite application.

    The suite includes a regression assertion proving that an unassisted
    same-session follow-up uses persisted conversation focus while answering.
    """

    result: EvaluationResult

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_evaluation()

    def assert_checks_pass(self, *prefixes: str) -> None:
        selected = [
            item for item in self.result.checks
            if any(item.name.startswith(prefix) for prefix in prefixes)
        ]
        self.assertTrue(selected, f"No checks matched {prefixes!r}")
        failures = [f"{item.name}: {item.detail}" for item in selected if not item.passed]
        self.assertEqual(failures, [])

    def check_named(self, name: str):
        matches = [item for item in self.result.checks if item.name == name]
        self.assertEqual(len(matches), 1, f"Expected exactly one check named {name}")
        return matches[0]

    def test_financial_and_spending_math_are_database_grounded(self) -> None:
        self.assert_checks_pass("harness.", "finance.", "spending.")

    def test_bank_email_and_intake_matching_are_grounded(self) -> None:
        self.assert_checks_pass("email.", "intake.", "reconciliation.")

    def test_security_unknown_claim_and_injection_guards(self) -> None:
        self.assert_checks_pass("security.", "safety.")

    def test_correction_history_and_company_isolation(self) -> None:
        self.assert_checks_pass("correction.", "memory.", "isolation.")

    def test_repeatability_and_client_assisted_follow_up(self) -> None:
        for name in (
            "conversation.deterministic_consistency",
            "conversation.follow_up_uses_selected_context",
        ):
            check = self.check_named(name)
            self.assertTrue(check.passed, check.detail)

    def test_unassisted_same_session_follow_up_retains_context(self) -> None:
        """Persisted session focus must make a bare follow-up conversational."""

        check = self.check_named("conversation.unassisted_history_follow_up")
        self.assertTrue(check.passed, check.detail)

    def test_qualitative_rubric_is_bounded_and_honestly_labeled(self) -> None:
        self.assertEqual(self.result.rubric_maximum, 10)
        self.assertGreaterEqual(self.result.rubric_score, 8)
        self.assertEqual(
            {item.name for item in self.result.rubric},
            {
                "Naturalness and readability",
                "Follow-up relevance",
                "Epistemic calibration",
                "Consistency and state awareness",
                "Concise and actionable",
            },
        )
        follow_up = next(
            item for item in self.result.rubric if item.name == "Follow-up relevance"
        )
        self.assertIn(follow_up.score, {1, 2})

    def test_report_is_concise_and_redacts_secrets(self) -> None:
        output = io.StringIO()
        print_report(self.result, output)
        report = output.getvalue()
        self.assertIn("not a scientifically valid Turing test", report)
        self.assertIn("no claim of consciousness", report)
        self.assertIn("Machine-check verdicts", report)
        self.assertIn("Qualitative rubric (heuristic)", report)
        self.assertIn(
            f"Release gate: {'PASS' if self.result.passed else 'FAIL'}", report
        )
        self.assertLess(len(report), 12_000)
        self.assertLess(len(report.splitlines()), 90)

        redacted = sanitize_for_report(
            "api_key=super-secret Authorization:Bearer abc.def.ghi password=hunter2"
        )
        self.assertNotIn("super-secret", redacted)
        self.assertNotIn("abc.def.ghi", redacted)
        self.assertNotIn("hunter2", redacted)
        self.assertGreaterEqual(redacted.count("[REDACTED]"), 3)


if __name__ == "__main__":
    unittest.main()
