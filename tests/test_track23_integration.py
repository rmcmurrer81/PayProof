from __future__ import annotations

import importlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.core as core


class Track23IsolatedIntegrationTests(unittest.TestCase):
    """End-to-end checks for bank, reconciliation, intake, reset, and chat safety.

    Every mutable Core and Gmail path is redirected before ``app`` is imported,
    so this suite never initializes or writes PayProof's real runtime database.
    """

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory(prefix="payproof-track23-")
        self.temp_root = Path(self.temp_directory.name).resolve()
        self.runtime_dir = self.temp_root / "runtime"
        self.demo_intake_dir = self.temp_root / "demo-intake"
        self.user_intake_dir = self.temp_root / "intake"
        for directory in (self.runtime_dir, self.demo_intake_dir, self.user_intake_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self.environment_patch = patch.dict(
            os.environ,
            {
                "PAYPROOF_MODEL_BASE_URL": "",
                "PAYPROOF_MODEL_API_KEY": "",
                "PAYPROOF_MODEL": "",
                "PRISMTRACE_PROJECT_ID": "",
                "PRISMTRACE_API_KEY": "",
                "PLAID_CLIENT_ID": "",
                "PLAID_SECRET": "",
                "PAYPROOF_PLAID_CLIENT_ID": "",
                "PAYPROOF_PLAID_SECRET": "",
            },
            clear=False,
        )
        self.environment_patch.start()

        self.core_patchers = [
            patch.object(core, "RUNTIME_DIR", self.runtime_dir),
            patch.object(core, "DB_PATH", self.runtime_dir / "track23.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", self.runtime_dir / "prism-queue.jsonl"),
            patch.object(core, "BANK_CONNECTIONS_PATH", self.runtime_dir / "bank-connections.json"),
            patch.object(core, "DEMO_INTAKE_DIR", self.demo_intake_dir),
            patch.object(core, "USER_INTAKE_DIR", self.user_intake_dir),
        ]
        for patcher in self.core_patchers:
            patcher.start()

        # Importing app is intentionally side-effect free; paths are still patched
        # first so later endpoint calls cannot escape the temporary test root.
        self.app_module = importlib.import_module("app")
        self.app_root_patcher = patch.object(self.app_module, "PROJECT_ROOT", self.temp_root)
        self.app_root_patcher.start()
        self.app_module.BANK_PREVIEWS.clear()
        self.app_module.OCR_PREVIEWS.clear()
        self.app_module.OAUTH_STATE.clear()
        self.app_module.SOURCE_REMOVAL_PREVIEWS.clear()
        self.app_module.BANK_DISCONNECT_PREVIEWS.clear()
        self.app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        self.app_module.app.config.update(TESTING=True)

        core.initialize_database(reset=True)
        self.client = self.app_module.app.test_client()
        self.assertEqual(core.DB_PATH.resolve().parent, self.runtime_dir)
        self.assertEqual(
            self.app_module._gmail_paths("business")[1],
            self.temp_root / "data" / "runtime" / "gmail-business-token.dpapi.json",
        )

    def tearDown(self) -> None:
        self.app_module.BANK_PREVIEWS.clear()
        self.app_module.OCR_PREVIEWS.clear()
        self.app_module.OAUTH_STATE.clear()
        self.app_module.SOURCE_REMOVAL_PREVIEWS.clear()
        self.app_module.BANK_DISCONNECT_PREVIEWS.clear()
        self.app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        self.app_root_patcher.stop()
        for patcher in reversed(self.core_patchers):
            patcher.stop()
        self.environment_patch.stop()
        self.temp_directory.cleanup()

    def write_intake(
        self,
        expense_id: str,
        *,
        filename: str | None = None,
        merchant: str = "Track 23 Cafe",
        amount: str = "321.09",
        currency: str = "USD",
        spent_on: str = "2026-09-01",
        purpose: str = "Team working session",
    ) -> Path:
        payload = {
            "id": expense_id,
            "document_type": "employee_expense_report",
            "employee": "Test Operator",
            "department": "Quality",
            "office": "New York",
            "merchant": merchant,
            "amount": amount,
            "currency": currency,
            "date": spent_on,
            "category": "Meals",
            "purpose": purpose,
            "receipt_status": "missing",
            "approval_status": "needs_review",
        }
        path = self.user_intake_dir / (filename or f"{expense_id.lower()}.json")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def preview_bank(self, content: str, filename: str = "track23-bank.csv"):
        return self.client.post(
            "/api/import/bank/preview",
            data={
                "workspace": "business",
                "file": (io.BytesIO(content.encode("utf-8")), filename),
            },
            content_type="multipart/form-data",
        )

    def commit_bank(self, preview_id: str, workspace: str = "business"):
        return self.client.post(
            "/api/import/bank/commit",
            json={"preview_id": preview_id, "workspace": workspace},
        )

    def test_bank_api_preview_commit_duplicate_and_reconciliation_states(self) -> None:
        self.write_intake("EXP-T23-EXACT")
        scan = core.scan_intake_folder()
        self.assertEqual(scan["accepted"], 1)
        self.assertEqual(scan["errors"], [])

        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-09-01,Track 23 Cafe EXP-T23-EXACT,-321.09,debit,USD,4242,EXP-T23-EXACT,exact\n"
            "2026-08-28,Generic accounts payable,-12840.00,debit,USD,4242,,ambiguous\n"
            "2026-09-02,Unrelated mystery merchant,-777.77,debit,USD,4242,,unmatched\n"
        )
        response = self.preview_bank(statement)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        preview = response.get_json()
        self.assertEqual(len(preview["accepted"]), 3)
        self.assertEqual(preview["rejected"], [])
        self.assertTrue(preview["reconciliation"]["confirmation_required"])

        exact = next(row for row in preview["accepted"] if row["reference"] == "EXP-T23-EXACT")
        exact_matches = [match for match in exact["matches"] if match["id"] == "EXP-T23-EXACT"]
        self.assertEqual(len(exact_matches), 1)
        self.assertEqual(exact_matches[0]["type"], "intake_expense")
        self.assertGreaterEqual(exact_matches[0]["confidence"], 90)

        ambiguous = next(row for row in preview["accepted"] if row["description"] == "Generic accounts payable")
        ambiguous_invoice_ids = {
            match["id"] for match in ambiguous["matches"] if match["type"] == "invoice"
        }
        self.assertEqual(ambiguous_invoice_ids, {"INV-2041", "INV-2041-COPY"})

        unmatched = next(row for row in preview["accepted"] if row["description"] == "Unrelated mystery merchant")
        self.assertEqual(unmatched["matches"], [])

        commit_response = self.commit_bank(preview["preview_id"])
        self.assertEqual(commit_response.status_code, 200, commit_response.get_data(as_text=True))
        committed = commit_response.get_json()
        self.assertTrue(committed["committed"])
        self.assertEqual(committed["accepted"], 3)
        self.assertTrue(committed["reconciliation"]["confirmation_required"])

        reconciliation_response = self.client.get("/api/reconciliation?workspace=business")
        self.assertEqual(reconciliation_response.status_code, 200)
        reconciliation = reconciliation_response.get_json()
        imported_rows = [
            row for row in reconciliation["rows"]
            if row["bank_transaction"]["provider"] == "local_statement"
        ]
        self.assertEqual(len(imported_rows), 3)
        self.assertEqual(
            next(row for row in imported_rows if row["bank_transaction"]["description"] == "Unrelated mystery merchant")["match_state"],
            "unmatched",
        )
        self.assertTrue(reconciliation["confirmation_required"])

        duplicate_preview_response = self.preview_bank(statement)
        self.assertEqual(duplicate_preview_response.status_code, 200)
        duplicate_response = self.commit_bank(duplicate_preview_response.get_json()["preview_id"])
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertIn("already imported", duplicate_response.get_data(as_text=True).lower())

    def test_bank_debit_credit_parsing_and_currency_separation(self) -> None:
        statement = (
            "date,description,debit,credit,currency,account_last4,reference,id\n"
            "2026-09-03,Coffee Shop,12.34,,USD,4242,,debit-row\n"
            "2026-09-04,Client Deposit,,1500.00,USD,4242,,credit-row\n"
            "2026-08-04,Northstar Industrial INV-1006,42100.00,,EUR,4242,INV-1006,eur-row\n"
            "2026-08-04,Northstar Industrial INV-1006,42100.00,,USD,4242,INV-1006,usd-row\n"
        )
        response = self.preview_bank(statement, "debit-credit-currency.csv")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        rows = response.get_json()["accepted"]
        by_description = {}
        for row in rows:
            by_description.setdefault((row["description"], row["currency"]), []).append(row)

        debit = by_description[("Coffee Shop", "USD")][0]
        credit = by_description[("Client Deposit", "USD")][0]
        self.assertEqual((debit["direction"], debit["amount_cents"]), ("debit", 1234))
        self.assertEqual((credit["direction"], credit["amount_cents"]), ("credit", 150000))

        eur = by_description[("Northstar Industrial INV-1006", "EUR")][0]
        usd = by_description[("Northstar Industrial INV-1006", "USD")][0]
        self.assertNotIn("INV-1006", {match["id"] for match in eur["matches"] if match["type"] == "invoice"})
        self.assertIn("INV-1006", {match["id"] for match in usd["matches"] if match["type"] == "invoice"})
        self.assertEqual(eur["amount_cents"], usd["amount_cents"])

    def test_intake_correction_is_audited_and_history_preserves_original(self) -> None:
        source_path = self.write_intake("EXP-T23-EDIT", amount="123.45")
        original_bytes = source_path.read_bytes()
        scan = core.scan_intake_folder()
        self.assertEqual(scan["accepted"], 1)

        response = self.client.patch(
            "/api/intake/expenses/EXP-T23-EDIT",
            json={
                "workspace": "business",
                "changes": {
                    "merchant": "Corrected Track 23 Cafe",
                    "amount": "150.00",
                    "category": "Team meals",
                    "receipt_status": "submitted",
                },
                "reason": "Receipt and card statement reviewed",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        correction = response.get_json()
        self.assertTrue(correction["original_preserved"])
        self.assertEqual(correction["version"], 2)
        self.assertEqual(correction["expense"]["amount_cents"], 15000)
        self.assertEqual(source_path.read_bytes(), original_bytes)

        history_response = self.client.get("/api/intake/expenses/EXP-T23-EDIT/history?workspace=business")
        self.assertEqual(history_response.status_code, 200)
        history = history_response.get_json()
        self.assertTrue(history["original_preserved"])
        self.assertEqual([entry["version"] for entry in history["versions"]], [1, 2])
        self.assertEqual(history["versions"][0]["snapshot"]["amount_cents"], 12345)
        self.assertEqual(history["versions"][1]["snapshot"]["amount_cents"], 15000)
        self.assertEqual(history["versions"][1]["reason"], "Receipt and card statement reviewed")

        audit = core.get_dashboard("business")["audit"]
        event = next(item for item in audit if item["finding_id"] == "EXP-T23-EDIT")
        self.assertEqual(event["action"], "correct_intake")

    def test_changed_same_id_intake_is_rejected_without_overwrite(self) -> None:
        source_path = self.write_intake("EXP-T23-SAME", amount="88.40")
        first_scan = core.scan_intake_folder()
        self.assertEqual(first_scan["accepted"], 1)
        initial_history = core.list_intake_expense_history("business", "EXP-T23-SAME")
        self.assertEqual(len(initial_history["versions"]), 1)

        changed = json.loads(source_path.read_text(encoding="utf-8"))
        changed["amount"] = "999.99"
        changed["purpose"] = "Changed file must not silently replace the first import"
        source_path.write_text(json.dumps(changed, indent=2), encoding="utf-8")
        second_scan = core.scan_intake_folder()

        self.assertEqual(second_scan["accepted"], 0)
        self.assertEqual(len(second_scan["errors"]), 1)
        self.assertIn("audited correction", second_scan["errors"][0]["reason"].lower())
        expense = next(item for item in core.get_dashboard("business")["expenses"] if item["id"] == "EXP-T23-SAME")
        self.assertEqual(expense["amount_cents"], 8840)
        final_history = core.list_intake_expense_history("business", "EXP-T23-SAME")
        self.assertEqual(len(final_history["versions"]), 1)
        self.assertEqual(final_history["versions"][0]["snapshot"]["amount_cents"], 8840)

    def test_scoped_demo_reset_preserves_imported_user_chat_and_audit_data(self) -> None:
        self.write_intake("EXP-T23-RESET", amount="42.75")
        self.assertEqual(core.scan_intake_folder()["accepted"], 1)
        correction = self.client.patch(
            "/api/intake/expenses/EXP-T23-RESET",
            json={
                "workspace": "business",
                "changes": {"purpose": "Corrected purpose for reset preservation"},
                "reason": "Validated with the employee",
            },
        )
        self.assertEqual(correction.status_code, 200, correction.get_data(as_text=True))

        bank_statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-09-05,Reset preservation merchant,-54.32,debit,USD,9090,,reset-bank\n"
        )
        bank_preview = self.preview_bank(bank_statement, "reset-preservation.csv")
        self.assertEqual(bank_preview.status_code, 200)
        bank_commit = self.commit_bank(bank_preview.get_json()["preview_id"])
        self.assertEqual(bank_commit.status_code, 200, bank_commit.get_data(as_text=True))

        gmail_result = core.import_gmail_metadata(
            [{
                "id": "track23-reset",
                "sender": "proof@example.invalid",
                "subject": "Reset preservation evidence",
                "received_at": "2026-09-05T12:00:00Z",
                "snippet": "User-imported evidence must remain after a scoped demo reset.",
            }],
            "business",
        )
        self.assertEqual(gmail_result["accepted"], 1)

        chat_response = self.client.post(
            "/api/chat",
            json={
                "question": "Show money in and money out",
                "workspace": "business",
                "session_id": "track23-reset-session",
            },
        )
        self.assertEqual(chat_response.status_code, 200)
        action_response = self.client.post(
            "/api/actions",
            json={"workspace": "business", "finding_id": "F-ROUTE-001", "action": "hold"},
        )
        self.assertEqual(action_response.status_code, 200)

        imports_before = core.list_import_sources("business")
        chat_before = core.list_chat_history("track23-reset-session", "business")
        history_before = core.list_intake_expense_history("business", "EXP-T23-RESET")
        dashboard_before = core.get_dashboard("business")
        audit_before = [(item["action"], item["finding_id"], item["reason"]) for item in dashboard_before["audit"]]
        bank_before = [
            row["bank_transaction"]["id"]
            for row in core.get_reconciliation_summary("business")["rows"]
            if not row["bank_transaction"]["is_synthetic"]
        ]

        reset_response = self.client.post("/api/reset")
        self.assertEqual(reset_response.status_code, 200)
        reset = reset_response.get_json()
        self.assertEqual(reset["scope"], "synthetic_demo_review_state")
        self.assertEqual(reset["preserved"]["user_bank_records"], 1)
        self.assertGreaterEqual(reset["preserved"]["audit_events"], 2)

        self.assertEqual(core.list_import_sources("business"), imports_before)
        self.assertEqual(core.list_chat_history("track23-reset-session", "business"), chat_before)
        self.assertEqual(core.list_intake_expense_history("business", "EXP-T23-RESET"), history_before)
        dashboard_after = core.get_dashboard("business")
        audit_after = [(item["action"], item["finding_id"], item["reason"]) for item in dashboard_after["audit"]]
        self.assertEqual(audit_after, audit_before)
        self.assertIn(
            core._gmail_evidence_row_id("business", "track23-reset"),
            {email["id"] for email in dashboard_after["emails"]},
        )
        bank_after = [
            row["bank_transaction"]["id"]
            for row in core.get_reconciliation_summary("business")["rows"]
            if not row["bank_transaction"]["is_synthetic"]
        ]
        self.assertEqual(bank_after, bank_before)

    def test_selected_security_control_does_not_hijack_bookkeeping_chat(self) -> None:
        response = self.client.post(
            "/api/chat",
            json={
                "question": "Show money in and money out",
                "workspace": "business",
                "selected_id": "control:CTRL-BACKUP",
                "session_id": "track23-bookkeeping-context",
            },
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertIn("money_in_cents", result["calculation"])
        self.assertIn("money_out_cents", result["calculation"])
        self.assertNotIn("two later jobs failed", result["answer"].lower())

        generic_response = self.client.post(
            "/api/chat",
            json={
                "question": "What data do you have?",
                "workspace": "business",
                "selected_id": "control:CTRL-BACKUP",
                "session_id": "track23-bookkeeping-context",
            },
        )
        self.assertEqual(generic_response.status_code, 200)
        generic = generic_response.get_json()
        self.assertIn("transactions", generic["calculation"])
        self.assertNotIn("backup", generic["answer"].lower())

        contextual_response = self.client.post(
            "/api/chat",
            json={
                "question": "Why?",
                "workspace": "business",
                "selected_id": "control:CTRL-BACKUP",
                "session_id": "track23-bookkeeping-context",
            },
        )
        self.assertEqual(contextual_response.status_code, 200)
        self.assertIn("backup owner", contextual_response.get_json()["answer"].lower())

    def test_missing_credentials_are_reported_truthfully(self) -> None:
        sources_response = self.client.get("/api/sources?workspace=business")
        self.assertEqual(sources_response.status_code, 200)
        sources = sources_response.get_json()
        bank = sources["bank"]
        self.assertEqual(bank["state"], "not_connected")
        self.assertEqual(bank["configuration_state"], "not_configured")
        self.assertIsInstance(bank["connector_implemented"], bool)
        self.assertEqual(
            bank["secure_token_storage"],
            "windows_dpapi" if bank["connector_implemented"] else "unavailable",
        )
        self.assertFalse(bank["credentials_collected_by_payproof"])
        self.assertFalse(bank["secret_values_exposed"])
        self.assertTrue(bank["local_statement_import"]["available"])
        self.assertEqual(bank["local_statement_import"]["formats"], ["CSV", "OFX", "QFX"])

        gmail = sources["gmail"]
        self.assertFalse(gmail["credentials_available"])
        self.assertFalse(gmail["connected"])
        self.assertFalse(gmail["token_stored_locally"])
        credentials_path, token_path = self.app_module._gmail_paths()
        self.assertFalse(credentials_path.exists())
        self.assertFalse(token_path.exists())

        bank_link_response = self.client.post(
            "/api/sources/bank/link-token",
            json={"workspace": "business", "session_id": "track23-no-credentials"},
        )
        self.assertEqual(bank_link_response.status_code, 503)
        bank_link_error = bank_link_response.get_json()
        self.assertFalse(bank_link_error["connected"])
        self.assertIn("not configured", bank_link_error["error"].lower())

        oauth_response = self.client.get("/api/sources/gmail/connect")
        self.assertEqual(oauth_response.status_code, 400)
        self.assertIn("oauth client file is missing", oauth_response.get_data(as_text=True).lower())
        health = self.client.get("/api/health").get_json()
        self.assertEqual(health["prism"]["state"], "not_configured")
        dashboard = self.client.get("/api/dashboard?workspace=business").get_json()
        self.assertEqual(dashboard["ai"]["state"], "deterministic_fallback")


class LauncherContractTests(unittest.TestCase):
    def test_launcher_waits_for_health_before_opening_browser(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        launcher_path = project_root / "Start PayProof.cmd"
        wait_script_path = project_root / "tools" / "open_when_ready.ps1"
        self.assertTrue(launcher_path.is_file(), "Start PayProof.cmd is missing")
        self.assertTrue(wait_script_path.is_file(), "tools/open_when_ready.ps1 is missing")

        launcher = launcher_path.read_text(encoding="utf-8").lower()
        wait_script = wait_script_path.read_text(encoding="utf-8").lower()
        self.assertIn(r"tools\open_when_ready.ps1", launcher)
        self.assertIn("http://127.0.0.1:8765/api/health", launcher)
        self.assertIn("invoke-webrequest", wait_script)
        self.assertIn("statuscode -eq 200", wait_script)
        self.assertIn("start-process", wait_script)
        self.assertLess(wait_script.index("statuscode -eq 200"), wait_script.index("start-process"))
        self.assertIn("/api/health$", wait_script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
