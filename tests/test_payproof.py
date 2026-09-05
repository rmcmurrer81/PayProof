from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


class PayProofCoreTests(unittest.TestCase):
    def setUp(self):
        core.initialize_database(reset=True)

    def test_demo_contains_real_calculated_metrics_and_sources(self):
        dashboard = core.get_dashboard("business")
        self.assertEqual(dashboard["metrics"]["transaction_count"], 105)
        self.assertEqual(dashboard["metrics"]["recorded_spending"], sum(t["amount_cents"] for t in dashboard["transactions"]))
        self.assertEqual(len(dashboard["emails"]), 4)
        self.assertTrue(all(email["is_synthetic"] for email in dashboard["emails"]))
        self.assertEqual(len(dashboard["employees"]), 3)
        self.assertEqual(len(dashboard["expenses"]), 4)
        self.assertEqual(dashboard["metrics"]["employee_spend"], 121094)
        self.assertGreater(dashboard["metrics"]["cash_in"], 0)

    def test_intake_scan_is_idempotent_and_employee_expenses_are_grounded(self):
        result = core.scan_intake_folder()
        self.assertEqual(result["accepted"], 0)
        self.assertGreaterEqual(result["skipped"], 4)
        answer = core.answer_question("Which employee expense reports need review?", "business")
        self.assertEqual(answer.calculation["report_count"], 4)
        self.assertEqual(answer.calculation["needs_review"], 1)
        self.assertIn("Priya Shah", answer.answer)

    def test_money_in_and_out_are_separate(self):
        answer = core.answer_question("Show money in and money out", "business")
        self.assertGreater(answer.calculation["money_in_cents"], 0)
        self.assertGreater(answer.calculation["money_out_cents"], 0)

    def test_destination_change_is_high_risk_and_evidence_grounded(self):
        dashboard = core.get_dashboard("business")
        finding = next(f for f in dashboard["findings"] if f["kind"] == "destination_change")
        self.assertEqual(finding["severity"], "high")
        self.assertIn("SRC-INV-1007", finding["evidence_ids"])
        answer = core.answer_question("Could you explain what changed?", "business")
        self.assertIn("****7284", answer.answer)
        self.assertIn("****9142", answer.answer)
        self.assertIn("not proof of fraud", answer.answer)

    def test_chat_math_and_workspace_separation(self):
        business = core.answer_question("How much did I spend at Amazon?", "business")
        personal = core.answer_question("How much did I spend at Amazon?", "personal")
        self.assertIn("no Amazon", business.answer)
        self.assertGreater(personal.calculation["count"], 0)
        self.assertEqual(personal.calculation["total_cents"], sum(
            t["amount_cents"] for t in core.get_dashboard("personal")["transactions"]
            if core.normalize_merchant(t["merchant_raw"]) == "amazon"
        ))

    def test_csv_preview_commit_duplicate_and_remove(self):
        content = "id,merchant,amount,currency,date,office\nTX-IMPORT-1,Acme Parts,99.95,USD,2026-09-05,New York\n"
        preview = core.import_transactions_csv("business", "sample.csv", content, False)
        self.assertEqual(len(preview["accepted"]), 1)
        self.assertFalse(preview["committed"])
        committed = core.import_transactions_csv("business", "sample.csv", content, True)
        self.assertTrue(committed["committed"])
        duplicate = core.import_transactions_csv("business", "sample.csv", content, True)
        self.assertIn("already imported", duplicate["errors"][0])
        source = next(s for s in core.list_import_sources("business") if s["kind"] == "csv")
        removed = core.remove_source("business", source["id"])
        self.assertEqual(removed["removed"], 1)

    def test_malformed_import_fails_safely(self):
        result = core.import_transactions_csv("business", "bad.csv", "merchant,amount\nX,nope\n", False)
        self.assertIn("Missing columns", result["errors"][0])

    def test_review_action_persists_as_simulated(self):
        result = core.record_action("business", "F-ROUTE-001", "hold")
        self.assertTrue(result["simulated"])
        self.assertEqual(result["status"], "held")
        dashboard = core.get_dashboard("business")
        self.assertEqual(dashboard["audit"][0]["action"], "hold")

    def test_prism_without_credentials_is_truthful(self):
        with patch.dict(os.environ, {"PRISMTRACE_PROJECT_ID": "", "PRISMTRACE_API_KEY": ""}, clear=False):
            result = core.send_prism_trace("test", core.ChatResult("answer", [], []), "session", 3, "business")
        self.assertEqual(result["state"], "not_configured")


class PayProofApiTests(unittest.TestCase):
    def setUp(self):
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()

    def test_judge_startup_endpoints(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        dashboard = self.client.get("/api/dashboard?workspace=business")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["workspace"], "business")

    def test_chat_and_source_status(self):
        response = self.client.post("/api/chat", json={"question": "What data do you have?", "workspace": "business"})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.get_json()["evidence_ids"]), 0)
        sources = self.client.get("/api/sources?workspace=business").get_json()
        self.assertTrue(sources["gmail"]["credentials_available"])
        self.assertTrue(sources["intake_folder"]["available"])
        self.assertEqual(self.client.post("/api/sources/intake/scan").status_code, 200)

    def test_empty_chat_and_bad_action_have_clear_errors(self):
        self.assertEqual(self.client.post("/api/chat", json={"question": ""}).status_code, 400)
        self.assertEqual(self.client.post("/api/actions", json={"finding_id": "F-ROUTE-001", "action": "pay"}).status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
