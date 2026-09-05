from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


class EmailBankEnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="payproof-email-bank-"
        )
        root = Path(self.temporary_directory.name).resolve()
        runtime = root / "runtime"
        runtime.mkdir()
        self.environment_patcher = patch.dict(
            os.environ,
            {
                "PAYPROOF_MODEL_BASE_URL": "",
                "PAYPROOF_MODEL_API_KEY": "",
                "PAYPROOF_MODEL": "",
                "PLAID_CLIENT_ID": "",
                "PLAID_SECRET": "",
            },
            clear=False,
        )
        self.environment_patcher.start()
        self.patchers = [
            patch.object(core, "PROJECT_ROOT", root),
            patch.object(core, "RUNTIME_DIR", runtime),
            patch.object(core, "DB_PATH", runtime / "payproof.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", runtime / "prism_queue.jsonl"),
            patch.object(core, "BANK_CONNECTIONS_PATH", runtime / "bank-connections.json"),
            patch.object(core, "DEMO_INTAKE_DIR", root / "no-demo-intake"),
            patch.object(core, "USER_INTAKE_DIR", root / "no-user-intake"),
            patch.object(core, "SECURITY_EVIDENCE_DIR", root / "no-security"),
            patch.object(core, "SECURITY_QUESTIONNAIRE_PATH", root / "no-questionnaire.json"),
            patch.object(app_module, "PROJECT_ROOT", root),
        ]
        for patcher in self.patchers:
            patcher.start()
        app_module.app.config.update(TESTING=True)
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.environment_patcher.stop()
        self.temporary_directory.cleanup()

    def test_demo_amazon_bank_row_is_enriched_only_from_explicit_email_items(self) -> None:
        payload = core.get_reconciliation_summary("personal")
        row = next(
            item for item in payload["rows"]
            if item["bank_transaction"]["id"] == "BANK-DEMO-P-002"
        )
        self.assertEqual(row["match_state"], "high_confidence")
        self.assertFalse(row["ambiguous"])
        self.assertTrue(row["review_required"])
        email_match = next(item for item in row["matches"] if item["type"] == "email")
        self.assertEqual(email_match["confidence"], 100)
        self.assertEqual(
            email_match["context"]["itemization"],
            ["coffee filters", "sparkling water"],
        )
        self.assertTrue(email_match["context"]["untrusted_document_text"])
        self.assertIn("same calendar date", email_match["basis"])
        self.assertEqual(email_match["status"], "suggested")

    def test_chat_explains_itemized_match_with_both_evidence_sources(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "workspace": "personal",
                "session_id": "email-bank-items",
                "question": "What did the $43.57 Amazon bank transaction buy?",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()
        answer = result["answer"].lower()
        self.assertIn("coffee filters", answer)
        self.assertIn("sparkling water", answer)
        self.assertIn("suggested match", answer)
        self.assertIn("not an automatically confirmed", answer)
        self.assertEqual(result["calculation"]["items"], ["coffee filters", "sparkling water"])
        self.assertTrue(result["calculation"]["confirmation_required"])
        self.assertFalse(result["calculation"]["score_is_probability"])
        self.assertIn("BANK-DEMO:SRC-P-002", result["evidence_ids"])
        self.assertIn("EMAIL-DEMO-007", result["evidence_ids"])

    def test_equal_top_email_candidates_are_reported_as_ambiguous(self) -> None:
        imported = core.import_gmail_metadata(
            [{
                "id": "same-amazon-order-copy",
                "sender": "orders@amazon.example.invalid",
                "subject": "Amazon receipt TX-AMZ-4357 copy",
                "received_at": "Tue, 25 Aug 2026 15:42:00 +0000",
                "snippet": (
                    "Amazon order total $43.57. Items: coffee filters; "
                    "sparkling water. Order reference: TX-AMZ-4357."
                ),
            }],
            "personal",
        )
        self.assertEqual(imported, {"accepted": 1, "skipped": 0})
        row = next(
            item for item in core.get_reconciliation_summary("personal")["rows"]
            if item["bank_transaction"]["id"] == "BANK-DEMO-P-002"
        )
        self.assertEqual(row["match_state"], "ambiguous")
        self.assertTrue(row["ambiguous"])
        response = self.client.post(
            "/api/chat",
            json={
                "workspace": "personal",
                "session_id": "ambiguous-email-bank",
                "question": "What items were in the $43.57 Amazon transaction?",
            },
        )
        result = response.get_json()
        self.assertEqual(result["calculation"]["status"], "ambiguous")
        self.assertIn("unknown which email", result["answer"].lower())
        self.assertNotIn("coffee filters", result["answer"].lower())

    def test_amount_substring_and_wrong_currency_do_not_create_email_match(self) -> None:
        company = core.create_company_workspace("Currency Boundary LLC")["id"]
        core.import_gmail_metadata(
            [{
                "id": "wrong-amount-currency",
                "sender": "orders@amazon.example.invalid",
                "subject": "Amazon order",
                "received_at": "2026-08-25T12:00:00Z",
                "snippet": "Amazon charged $143.57. Items: unrelated item.",
            }],
            company,
        )
        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-08-25,Amazon Marketplace,43.57,debit,EUR,3131,,ROW-1\n"
        )
        preview = core.preview_bank_statement(company, "currency.csv", statement)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["accepted"][0]["matches"], [])

    def test_email_itemization_does_not_cross_company_boundary(self) -> None:
        other = core.create_company_workspace("Other Buyer Books")["id"]
        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-08-25,Amazon Marketplace,43.57,debit,USD,3131,TX-AMZ-4357,ROW-1\n"
        )
        preview = core.preview_bank_statement(other, "other.csv", statement)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["accepted"][0]["matches"], [])


if __name__ == "__main__":
    unittest.main()
