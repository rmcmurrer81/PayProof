from __future__ import annotations

import io
import importlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


class IsolatedPayProofTestCase(unittest.TestCase):
    def setUp(self):
        self.test_directory = tempfile.TemporaryDirectory(prefix="payproof-tests-")
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
        app_module.BANK_PREVIEWS.clear()
        app_module.SOURCE_REMOVAL_PREVIEWS.clear()
        app_module.BANK_DISCONNECT_PREVIEWS.clear()
        app_module.OAUTH_STATE.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        core.initialize_database(reset=True)

    def tearDown(self):
        app_module.OAUTH_STATE.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.test_directory.cleanup()


class PayProofCoreTests(IsolatedPayProofTestCase):

    def test_app_import_does_not_initialize_or_touch_the_database(self):
        with patch.object(core, "initialize_database") as initialize:
            importlib.reload(app_module)
        initialize.assert_not_called()
        importlib.reload(app_module)

    def test_demo_contains_real_calculated_metrics_and_sources(self):
        dashboard = core.get_dashboard("business")
        self.assertEqual(dashboard["metrics"]["transaction_count"], 105)
        self.assertEqual(dashboard["metrics"]["recorded_spending"], sum(t["amount_cents"] for t in dashboard["transactions"]))
        self.assertEqual(len(dashboard["emails"]), 5)
        self.assertTrue(all(email["is_synthetic"] for email in dashboard["emails"]))
        self.assertEqual(len(dashboard["employees"]), 3)
        self.assertEqual(len(dashboard["expenses"]), 4)
        self.assertEqual(dashboard["metrics"]["employee_spend"], 121094)
        self.assertGreater(dashboard["metrics"]["cash_in"], 0)

    def test_financial_graph_has_bounded_resolvable_transactions_and_receipts(self):
        dashboard = core.get_dashboard("business")
        transaction_nodes = [node for node in dashboard["graph"]["nodes"] if node["type"] == "transaction"]
        receipt_nodes = [node for node in dashboard["graph"]["nodes"] if node["type"] == "receipt"]
        self.assertGreater(len(transaction_nodes), 0)
        self.assertLessEqual(len(transaction_nodes), 18)
        self.assertGreater(len(receipt_nodes), 0)
        self.assertLessEqual(len(receipt_nodes), 12)
        for node in transaction_nodes[:2] + receipt_nodes[:2]:
            self.assertIsNotNone(core.get_record(node["id"], "business"))

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

    def test_instructions_inside_evidence_cannot_bypass_controls(self):
        answer = core.answer_question("Did you detect prompt injection?", "business")
        self.assertEqual(answer.calculation["actions_executed"], 0)
        self.assertIn("untrusted evidence", answer.answer)
        dashboard = core.get_dashboard("business")
        route = next(f for f in dashboard["findings"] if f["id"] == "F-ROUTE-001")
        self.assertEqual(route["status"], "open")

    def test_security_questionnaire_answers_are_evidence_backed_and_honest(self):
        dashboard = core.get_dashboard("business")
        self.assertEqual(dashboard["security"]["metrics"]["controls_assessed"], 7)
        self.assertEqual(dashboard["security"]["metrics"]["gaps"], 2)
        mfa = core.answer_question("Is MFA enabled?", "business")
        self.assertIn("Production identities: 18", mfa.answer)
        self.assertIn("MFA enrolled: 16", mfa.answer)
        self.assertEqual(mfa.calculation["status"], "conflict")
        self.assertGreaterEqual(len(mfa.evidence_ids), 2)
        backups = core.answer_question("How often are backups performed?", "business")
        self.assertIn("FAILED", backups.answer)
        self.assertEqual(backups.calculation["status"], "partial")
        followup = core.answer_question("Why?", "business", "control:CTRL-BACKUP")
        self.assertIn("backup owner", followup.answer)

    def test_unknown_security_answer_is_not_invented(self):
        result = core.answer_question("Do you have ISO 27001 certification?", "business")
        self.assertTrue(result.answer.startswith("Unknown."))
        self.assertEqual(result.evidence_ids, [])
        general = core.answer_question("Are you FedRAMP authorized?", "business")
        self.assertTrue(general.answer.startswith("Unknown."))
        self.assertEqual(general.calculation["evidence_count"], 0)

    def test_questionnaire_generation_prioritizes_gaps_and_cites_every_answer(self):
        questionnaire = core.generate_security_questionnaire()
        self.assertEqual(len(questionnaire["answers"]), 7)
        self.assertEqual(questionnaire["answers"][0]["status"], "conflict")
        self.assertTrue(all(answer["evidence_ids"] for answer in questionnaire["answers"]))

    def test_chat_memory_persists_and_separates_workspaces(self):
        result = core.answer_question("Is MFA enabled?", "business")
        core.record_chat_turn("memory-test", "business", "Is MFA enabled?", result)
        self.assertEqual(len(core.list_chat_history("memory-test", "business")), 2)
        self.assertEqual(core.list_chat_history("memory-test", "personal"), [])

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

    def test_spending_cut_suggestion_uses_history_and_discloses_uncertainty(self):
        result = core.answer_question("Where could I cut spending?", "personal")
        self.assertIn("prior monthly baseline", result.answer)
        self.assertIn("suggestion, not a conclusion", result.answer)
        self.assertIn("does not assume", result.answer)
        self.assertFalse(result.calculation["category_itemized"])
        self.assertGreater(result.calculation["increase_cents"], 0)
        self.assertGreater(len(result.evidence_ids), 0)

    def test_spending_category_requires_explicit_email_or_intake_evidence(self):
        core.import_gmail_metadata([{
            "id": "itemized-amazon", "sender": "orders@example.com", "subject": "TX-P-025 itemization",
            "received_at": "2026-07-30", "snippet": "TX-P-025 contains food and drinks.",
        }], "personal")
        result = core.answer_question("Where could I cut spending?", "personal")
        self.assertEqual(result.calculation["category"], "Food & drinks")
        self.assertTrue(result.calculation["category_itemized"])
        self.assertIn(core._gmail_evidence_row_id("personal", "itemized-amazon"), result.evidence_ids)
        business = core.answer_question("Where could the company cut spending?", "business")
        self.assertIn("Possible cut", business.answer)

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
        with self.assertRaisesRegex(ValueError, "Preview"):
            core.remove_source("business", source["id"])
        removal = core.preview_source_removal("business", source["id"])
        self.assertEqual(removal["affected"]["transactions"], 1)
        removed = core.remove_source("business", source["id"], confirmed=True)
        self.assertEqual(removed["removed"], 1)

    def test_bank_csv_preview_reconciles_and_commits_without_double_counting(self):
        content = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-08-04,Northstar Industrial,42100.00,debit,USD,4242,INV-1006,BANK-ROW-1\n"
            "2026-08-27,Lakeside Bistro,186.45,debit,USD,4242,EXP-2026-043,BANK-ROW-2\n"
        )
        before_count = core.get_dashboard("business")["metrics"]["transaction_count"]
        preview = core.preview_bank_statement("business", "statement.csv", content)
        self.assertEqual(len(preview["accepted"]), 2)
        self.assertEqual(preview["reconciliation"]["suggested"], 2)
        first_types = {item["type"] for item in preview["accepted"][0]["matches"]}
        second_types = {item["type"] for item in preview["accepted"][1]["matches"]}
        self.assertIn("invoice", first_types)
        self.assertIn("email", first_types)
        self.assertIn("intake_expense", second_types)
        committed = core.commit_bank_statement_preview(
            "business", "statement.csv", preview["source_hash"], preview["accepted"],
        )
        self.assertTrue(committed["committed"])
        dashboard = core.get_dashboard("business")
        self.assertEqual(dashboard["metrics"]["transaction_count"], before_count)
        self.assertEqual(dashboard["metrics"]["bank_transaction_count"], 4)
        source = next(item for item in core.list_import_sources("business") if item["kind"] == "bank")
        removal = core.preview_source_removal("business", source["id"])
        self.assertEqual(removal["affected"]["bank_transactions"], 2)
        self.assertFalse(removal["upstream_data_deleted"])

    def test_local_bank_source_removal_is_workspace_scoped(self):
        business_content = ("date,description,amount,direction,currency,id\n"
                            "2026-09-01,Business only,10.00,debit,USD,business-row\n")
        personal_content = ("date,description,amount,direction,currency,id\n"
                            "2026-09-02,Personal only,20.00,debit,USD,personal-row\n")
        self.assertTrue(core.import_bank_statement("business", "business.csv", business_content, True)["committed"])
        self.assertTrue(core.import_bank_statement("personal", "personal.csv", personal_content, True)["committed"])
        business_source = next(item for item in core.list_import_sources("business") if item["kind"] == "bank")
        personal_source = next(item for item in core.list_import_sources("personal") if item["kind"] == "bank")
        core.remove_source("business", business_source["id"], confirmed=True)
        self.assertFalse(any(item["id"] == business_source["id"] for item in core.list_import_sources("business")))
        self.assertTrue(any(item["id"] == personal_source["id"] for item in core.list_import_sources("personal")))
        self.assertTrue(any(row["description"] == "Personal only"
                            for row in core.get_dashboard("personal")["bank_transactions"]))

    def test_ofx_parser_masks_account_and_malformed_rows_do_not_commit(self):
        content = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD<ACCTID>1234567890
<BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260827120000<TRNAMT>-186.45
<FITID>ofx-1<NAME>Lakeside Bistro<MEMO>EXP-2026-043</STMTTRN></BANKTRANLIST>
</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
        parsed = core.parse_bank_statement("statement.ofx", content)
        self.assertEqual(parsed["accepted"][0]["account_mask"], "****7890")
        self.assertEqual(parsed["accepted"][0]["direction"], "debit")
        self.assertNotIn("1234567890", json.dumps(parsed))
        malformed = core.import_bank_statement(
            "business", "bad.csv", "date,description,debit,credit,currency\n2026-09-05,X,10,10,USD\n", True,
        )
        self.assertFalse(malformed["committed"])
        self.assertEqual(len(malformed["rejected"]), 1)

    def test_intake_correction_preserves_original_and_rejects_immutable_fields(self):
        before = core.get_record("expense:EXP-2026-043", "business")
        corrected = core.correct_intake_expense(
            "business", "EXP-2026-043", {"amount": "196.45", "purpose": "Corrected customer dinner"},
            "Receipt showed a corrected total",
        )
        self.assertTrue(corrected["original_preserved"])
        history = core.list_intake_expense_history("business", "EXP-2026-043")
        self.assertEqual(len(history["versions"]), 2)
        self.assertEqual(history["versions"][0]["snapshot"]["amount_cents"], before["amount_cents"])
        self.assertEqual(history["versions"][1]["snapshot"]["amount_cents"], 19645)
        with self.assertRaisesRegex(ValueError, "cannot be edited"):
            core.correct_intake_expense("business", "EXP-2026-043", {"id": "changed"}, "bad edit")

    def test_changed_intake_file_requires_audited_correction(self):
        core.USER_INTAKE_DIR.mkdir(parents=True)
        path = core.USER_INTAKE_DIR / "user-expense.json"
        payload = {
            "id": "EXP-USER-001", "document_type": "employee_expense_report", "employee": "Taylor Example",
            "department": "Operations", "office": "Boston", "merchant": "Cafe Example", "amount": "24.50",
            "currency": "USD", "date": "2026-09-01", "category": "Meals", "purpose": "Team lunch",
            "receipt_status": "matched", "approval_status": "submitted",
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(core.scan_intake_folder()["accepted"], 1)
        payload["amount"] = "99.00"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = core.scan_intake_folder()
        self.assertIn("audited correction", result["errors"][0]["reason"])
        self.assertEqual(core.get_record("expense:EXP-USER-001", "business")["amount_cents"], 2450)

    def test_synthetic_reset_preserves_user_state(self):
        content = "id,merchant,amount,currency,date,office\nTX-USER-KEEP,Example,10.00,USD,2026-09-05,Boston\n"
        core.import_transactions_csv("business", "keep.csv", content, True)
        core.import_gmail_metadata([{"id": "keep", "sender": "x@example.com", "subject": "Keep", "snippet": "Keep"}], "business")
        chat = core.ChatResult("answer", [], [])
        core.record_chat_turn("keep-session", "business", "question", chat)
        core.correct_intake_expense("business", "EXP-2026-043", {"purpose": "Preserved edit"}, "valid correction")
        core.record_action("business", "F-ROUTE-001", "hold")
        result = core.reset_synthetic_demo_state()
        self.assertEqual(result["scope"], "synthetic_demo_review_state")
        self.assertIsNotNone(core.get_record("transaction:TX-USER-KEEP", "business"))
        self.assertEqual(len(core.list_chat_history("keep-session", "business")), 2)
        self.assertEqual(len(core.list_intake_expense_history("business", "EXP-2026-043")["versions"]), 2)

    def test_selected_security_control_does_not_hijack_bookkeeping_question(self):
        result = core.answer_question("Could you explain what changed?", "business", "control:CTRL-MFA")
        self.assertIn("****9142", result.answer)

    def test_identical_plaid_ids_sync_remove_and_disconnect_are_workspace_scoped(self):
        connection_id = "shared-connection-id"
        core._save_bank_connections([
            {"id": connection_id, "workspace_id": "business", "item_fingerprint": "business-item",
             "protected_access_token": "cipher-business", "cursor": None, "institution": "Business Bank",
             "account_masks": {}, "created_at": core.utc_now(), "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
            {"id": connection_id, "workspace_id": "personal", "item_fingerprint": "personal-item",
             "protected_access_token": "cipher-personal", "cursor": None, "institution": "Personal Bank",
             "account_masks": {}, "created_at": core.utc_now(), "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
        ])
        sync_counts = {"access-business": 0, "access-personal": 0}

        def plaid_request(endpoint, body):
            token = body.get("access_token")
            if endpoint == "/accounts/get":
                suffix = "1111" if token == "access-business" else "2222"
                return {"accounts": [{"account_id": "shared-account", "mask": suffix}]}
            if endpoint == "/transactions/sync":
                sync_counts[token] += 1
                if token == "access-business" and sync_counts[token] == 2:
                    return {"added": [], "modified": [], "removed": [{"transaction_id": "same-plaid-id"}],
                            "next_cursor": "business-2", "has_more": False}
                description = "Northstar Industrial" if token == "access-business" else "Amazon Marketplace"
                amount = 42100 if token == "access-business" else 899
                added = [{"transaction_id": "same-plaid-id", "account_id": "shared-account",
                          "amount": amount,
                          "iso_currency_code": "USD" if token == "access-business" else None,
                          "unofficial_currency_code": None if token == "access-business" else "btc",
                          "date": "2026-08-04", "merchant_name": description, "pending": False}]
                if token == "access-personal":
                    added.append({"transaction_id": "missing-currency-id", "account_id": "shared-account",
                                  "amount": 12, "iso_currency_code": None,
                                  "unofficial_currency_code": None, "date": "2026-08-05",
                                  "merchant_name": "Currency Unknown", "pending": False})
                return {"added": added,
                        "modified": [], "removed": [],
                        "next_cursor": "business-1" if token == "access-business" else "personal-1",
                        "has_more": False}
            if endpoint == "/item/remove":
                return {}
            self.fail(f"Unexpected Plaid endpoint: {endpoint}")

        def unprotect(value):
            return {"cipher-business": "access-business", "cipher-personal": "access-personal"}[value]

        with patch.object(core, "_unprotect_bank_secret", side_effect=unprotect), \
                patch.object(core, "_plaid_request", side_effect=plaid_request):
            core.sync_plaid_transactions("business", connection_id)
            core.sync_plaid_transactions("personal", connection_id)
            business_row = next(row for row in core.get_dashboard("business")["bank_transactions"]
                                if row["provider"] == "plaid")
            personal_rows = [row for row in core.get_dashboard("personal")["bank_transactions"]
                             if row["provider"] == "plaid"]
            personal_row = next(row for row in personal_rows if row["description"] == "Amazon Marketplace")
            unknown_currency_row = next(row for row in personal_rows
                                        if row["description"] == "Currency Unknown")
            self.assertNotEqual(business_row["id"], personal_row["id"])
            self.assertEqual(business_row["account_mask"], "****1111")
            self.assertEqual(personal_row["account_mask"], "****2222")
            self.assertEqual(personal_row["currency"], "BTC")
            self.assertEqual(unknown_currency_row["currency"], "UNKNOWN")
            self.assertNotIn("shared-account", core.BANK_CONNECTIONS_PATH.read_text(encoding="utf-8"))
            core.sync_plaid_transactions("business", connection_id)
            self.assertFalse(any(row["provider"] == "plaid"
                                 for row in core.get_dashboard("business")["bank_transactions"]))
            self.assertIsNotNone(core.get_record(f"bank:{personal_row['id']}", "personal"))
            core.disconnect_plaid_connection("business", connection_id, confirmed=True)

        remaining = core._load_bank_connections()
        self.assertEqual([(item["id"], item["workspace_id"]) for item in remaining],
                         [(connection_id, "personal")])
        personal_disconnect_audit = [
            item for item in core.get_dashboard("personal")["audit"]
            if item["finding_id"] == connection_id and item["action"].startswith("bank_disconnect")
        ]
        self.assertEqual(personal_disconnect_audit, [])

    def test_custom_company_plaid_connections_and_transaction_ids_are_isolated(self):
        with closing(core._connect()) as database:
            database.executemany(
                "INSERT INTO workspaces(id, name, kind, is_demo) VALUES (?, ?, 'business', 0)",
                [("company-alpha", "Alpha LLC"), ("company-beta", "Beta LLC")],
            )
            database.commit()
        connection_id = "same-connector-id"
        account_key = core._plaid_account_key("same-upstream-account")
        core._save_bank_connections([
            {"id": connection_id, "workspace_id": "company-alpha", "item_fingerprint": "alpha-item",
             "account_set_fingerprint": "alpha-accounts", "protected_access_token": "cipher-alpha",
             "cursor": None, "institution": "Alpha Bank", "account_masks": {account_key: "****1001"},
             "created_at": core.utc_now(), "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
            {"id": connection_id, "workspace_id": "company-beta", "item_fingerprint": "beta-item",
             "account_set_fingerprint": "beta-accounts", "protected_access_token": "cipher-beta",
             "cursor": None, "institution": "Beta Bank", "account_masks": {account_key: "****2002"},
             "created_at": core.utc_now(), "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
        ])

        def unprotect(value):
            return {"cipher-alpha": "access-alpha", "cipher-beta": "access-beta"}[value]

        def plaid_request(endpoint, body):
            if endpoint == "/item/remove":
                return {}
            self.assertEqual(endpoint, "/transactions/sync")
            token = body["access_token"]
            return {
                "added": [{"transaction_id": "identical-upstream-id",
                           "account_id": "same-upstream-account", "amount": 19.95,
                           "iso_currency_code": "USD", "date": "2026-09-05",
                           "merchant_name": "Alpha Cafe" if token == "access-alpha" else "Beta Cafe",
                           "pending": False}],
                "modified": [], "removed": [], "next_cursor": f"cursor-{token}", "has_more": False,
            }

        with patch.object(core, "_unprotect_bank_secret", side_effect=unprotect), \
                patch.object(core, "_plaid_request", side_effect=plaid_request):
            core.sync_plaid_transactions("company-alpha", connection_id)
            core.sync_plaid_transactions("company-beta", connection_id)
            alpha = next(row for row in core.get_dashboard("company-alpha")["bank_transactions"]
                         if row["provider"] == "plaid")
            beta = next(row for row in core.get_dashboard("company-beta")["bank_transactions"]
                        if row["provider"] == "plaid")
            self.assertNotEqual(alpha["id"], beta["id"])
            self.assertEqual(alpha["description"], "Alpha Cafe")
            self.assertEqual(beta["description"], "Beta Cafe")
            core.disconnect_plaid_connection("company-alpha", connection_id, confirmed=True)

        self.assertEqual(
            [(item["id"], item["workspace_id"]) for item in core._load_bank_connections()],
            [(connection_id, "company-beta")],
        )
        with patch.object(core, "_unprotect_bank_secret") as unprotect_missing:
            with self.assertRaisesRegex(ValueError, "Unknown workspace"):
                core.sync_plaid_transactions("company-missing", connection_id)
        unprotect_missing.assert_not_called()

    def test_plaid_exchange_rolls_back_upstream_if_secure_save_fails(self):
        responses = [
            {"access_token": "temporary-access", "item_id": "new-item"},
            {"item": {"institution_id": "ins-test"},
             "accounts": [{"account_id": "account-test", "mask": "8080"}]},
            {},
        ]
        with patch.object(core, "_bank_secure_storage_available", return_value=True), \
                patch.object(core, "_protect_bank_secret", side_effect=OSError("secure store failed")), \
                patch.object(core, "_plaid_request", side_effect=responses) as plaid_request:
            with self.assertRaisesRegex(RuntimeError, "was revoked"):
                core.exchange_plaid_public_token("business", "temporary-public")
        self.assertEqual(core._load_bank_connections(), [])
        self.assertEqual([call.args[0] for call in plaid_request.call_args_list],
                         ["/item/public_token/exchange", "/accounts/get", "/item/remove"])

    def test_duplicate_plaid_account_set_is_revoked_and_not_appended_twice(self):
        with patch.object(core, "_bank_secure_storage_available", return_value=True), \
                patch.object(core, "_protect_bank_secret", return_value="ciphertext"), \
                patch.object(core, "_plaid_request", side_effect=[
                    {"access_token": "first-access", "item_id": "first-item"},
                    {"item": {"institution_id": "ins-shared"},
                     "accounts": [{"account_id": "shared-account", "mask": "4444"}]},
                    {"access_token": "second-access", "item_id": "second-item"},
                    {"item": {"institution_id": "ins-shared"},
                     "accounts": [{"account_id": "shared-account", "mask": "4444"}]},
                    {},
                ]) as plaid_request:
            first = core.exchange_plaid_public_token("business", "public-one")
            second = core.exchange_plaid_public_token("business", "public-two")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["already_connected"])
        self.assertTrue(second["duplicate_item_revoked"])
        self.assertEqual(len(core._load_bank_connections()), 1)
        stored = core.BANK_CONNECTIONS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("first-access", stored)
        self.assertNotIn("second-access", stored)
        self.assertNotIn("shared-account", stored)
        self.assertNotIn("first-item", stored)
        self.assertNotIn("second-item", stored)
        self.assertEqual([call.args[0] for call in plaid_request.call_args_list], [
            "/item/public_token/exchange", "/accounts/get",
            "/item/public_token/exchange", "/accounts/get", "/item/remove",
        ])

    def test_bank_connection_store_replace_failure_is_atomic_and_uses_unique_temps(self):
        original = [{"id": "original", "workspace_id": "business"}]
        core._save_bank_connections(original)
        temporary_paths = []

        def fail_replace(source, destination):
            temporary_paths.append(Path(source))
            raise OSError("replace failed")

        with patch.object(core.os, "replace", side_effect=fail_replace):
            for suffix in ("one", "two"):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    core._save_bank_connections([{"id": suffix, "workspace_id": "business"}])
        self.assertEqual(core._load_bank_connections(), original)
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertFalse(any(path.exists() for path in temporary_paths))

    def test_plaid_sync_cursor_checkpoint_failure_is_recoverable_and_idempotent(self):
        connection_id = "checkpoint-connection"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business", "item_fingerprint": "checkpoint-item",
            "account_set_fingerprint": "checkpoint-account-set",
            "protected_access_token": "cipher", "cursor": None, "institution": "Checkpoint Bank",
            "account_masks": {core._plaid_account_key("acct"): "****3030"},
            "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        delta = {"added": [{"transaction_id": "checkpoint-tx", "account_id": "acct", "amount": 15,
                            "iso_currency_code": "USD", "date": "2026-09-05", "merchant_name": "Cafe",
                            "pending": False}], "modified": [], "removed": [],
                 "next_cursor": "cursor-checkpoint", "has_more": False}
        original_save = core._save_bank_connections
        saves = {"count": 0}

        def flaky_save(connections):
            saves["count"] += 1
            if saves["count"] == 2:
                raise OSError("checkpoint write failed")
            return original_save(connections)

        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", return_value=delta), \
                patch.object(core, "_save_bank_connections", side_effect=flaky_save):
            with self.assertRaises(core.BankConnectorPartialError) as failure:
                core.sync_plaid_transactions("business", connection_id)
            self.assertEqual(failure.exception.details["state"], "records_applied_cursor_checkpoint_pending")
            pending = core._load_bank_connections()[0]["pending_sync"]
            self.assertEqual(pending["from_cursor"], None)
            result = core.sync_plaid_transactions("business", connection_id)
        self.assertTrue(result["cursor_saved"])
        plaid_rows = [row for row in core.get_dashboard("business")["bank_transactions"]
                      if row["provider"] == "plaid"]
        self.assertEqual(len(plaid_rows), 1)
        sync_audits = [item for item in core.get_dashboard("business")["audit"]
                       if item["finding_id"] == connection_id and item["action"] == "bank_sync"]
        self.assertEqual(len(sync_audits), 1)
        self.assertEqual(core._load_bank_connections()[0]["cursor"], "cursor-checkpoint")

    def test_plaid_sync_database_failure_rolls_back_and_retry_applies_once(self):
        connection_id = "database-failure-connection"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business", "item_fingerprint": "db-item",
            "account_set_fingerprint": "db-accounts", "protected_access_token": "cipher",
            "cursor": None, "institution": "Database Test Bank",
            "account_masks": {core._plaid_account_key("acct-db"): "****9191"},
            "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        delta = {"added": [{"transaction_id": "db-failure-tx", "account_id": "acct-db",
                            "amount": 22, "iso_currency_code": "USD", "date": "2026-09-05",
                            "merchant_name": "Database Cafe", "pending": False}],
                 "modified": [], "removed": [], "next_cursor": "db-cursor", "has_more": False}
        original_refresh = core._refresh_reconciliations
        failure = {"armed": True}

        def fail_after_plaid_insert(database, workspace_id):
            has_plaid_row = database.execute(
                "SELECT 1 FROM bank_transactions WHERE workspace_id=? AND provider='plaid'",
                (workspace_id,),
            ).fetchone()
            if workspace_id == "business" and has_plaid_row and failure["armed"]:
                failure["armed"] = False
                raise RuntimeError("database apply failed")
            return original_refresh(database, workspace_id)

        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", return_value=delta), \
                patch.object(core, "_refresh_reconciliations", side_effect=fail_after_plaid_insert):
            with self.assertRaisesRegex(RuntimeError, "database apply failed"):
                core.sync_plaid_transactions("business", connection_id)
            after_failure = core._load_bank_connections()[0]
            self.assertIsNone(after_failure["cursor"])
            self.assertIsNone(after_failure["pending_sync"])
            self.assertFalse(any(row["provider"] == "plaid"
                                 for row in core.get_dashboard("business")["bank_transactions"]))
            recovered = core.sync_plaid_transactions("business", connection_id)
        self.assertTrue(recovered["cursor_saved"])
        rows = [row for row in core.get_dashboard("business")["bank_transactions"]
                if row["provider"] == "plaid" and row["description"] == "Database Cafe"]
        self.assertEqual(len(rows), 1)

    def test_plaid_disconnect_recovers_local_cleanup_without_second_revocation(self):
        connection_id = "disconnect-recovery"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business", "item_fingerprint": "disconnect-item",
            "protected_access_token": "cipher", "cursor": None, "institution": "Recovery Bank",
            "account_masks": {}, "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        original_save = core._save_bank_connections
        saves = {"count": 0}

        def flaky_save(connections):
            saves["count"] += 1
            if saves["count"] == 3:
                raise OSError("local cleanup failed")
            return original_save(connections)

        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", return_value={}) as plaid_request, \
                patch.object(core, "_save_bank_connections", side_effect=flaky_save):
            with self.assertRaises(core.BankConnectorPartialError) as failure:
                core.disconnect_plaid_connection("business", connection_id, confirmed=True)
            self.assertEqual(failure.exception.details["state"], "upstream_revoked_local_cleanup_pending")
            self.assertEqual(core._load_bank_connections()[0]["disconnect_state"],
                             "revoked_pending_local_cleanup")
            recovered = core.disconnect_plaid_connection("business", connection_id, confirmed=True)
        self.assertTrue(recovered["disconnected"])
        self.assertEqual(plaid_request.call_count, 1)
        self.assertEqual(core._load_bank_connections(), [])

    def test_plaid_disconnect_checkpoint_failure_does_not_revoke_twice(self):
        connection_id = "disconnect-checkpoint-recovery"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business",
            "item_fingerprint": "checkpoint-item", "account_set_fingerprint": "checkpoint-accounts",
            "protected_access_token": "cipher", "cursor": None, "institution": "Checkpoint Bank",
            "account_masks": {}, "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        original_save = core._save_bank_connections
        saves = {"count": 0}

        def fail_revoked_checkpoint(connections):
            saves["count"] += 1
            if saves["count"] == 2:
                raise OSError("checkpoint replace failed")
            return original_save(connections)

        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", return_value={}) as plaid_request, \
                patch.object(core, "_save_bank_connections", side_effect=fail_revoked_checkpoint):
            with self.assertRaises(core.BankConnectorPartialError) as failure:
                core.disconnect_plaid_connection("business", connection_id, confirmed=True)
            self.assertEqual(
                failure.exception.details["state"],
                "upstream_revoked_local_checkpoint_failed",
            )
            recovered = core.disconnect_plaid_connection(
                "business", connection_id, confirmed=True,
            )
        self.assertTrue(recovered["disconnected"])
        self.assertEqual(plaid_request.call_count, 1)
        self.assertEqual(core._load_bank_connections(), [])

    def test_plaid_disconnect_reports_success_if_only_completion_audit_fails(self):
        connection_id = "disconnect-audit-pending"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business",
            "item_fingerprint": "audit-item", "account_set_fingerprint": "audit-accounts",
            "protected_access_token": "cipher", "cursor": None, "institution": "Audit Bank",
            "account_masks": {}, "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        original_audit = core._record_bank_connector_audit

        def fail_completion_audit(workspace_id, supplied_connection_id, action, reason):
            if action == "bank_disconnect":
                raise sqlite3.OperationalError("audit unavailable")
            return original_audit(workspace_id, supplied_connection_id, action, reason)

        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", return_value={}), \
                patch.object(core, "_record_bank_connector_audit", side_effect=fail_completion_audit):
            result = core.disconnect_plaid_connection("business", connection_id, confirmed=True)
        self.assertTrue(result["disconnected"])
        self.assertTrue(result["audit_pending"])
        self.assertEqual(result["state"], "disconnected_audit_pending")
        self.assertEqual(core._load_bank_connections(), [])

    def test_plaid_disconnect_upstream_failure_retains_token_for_safe_retry(self):
        connection_id = "disconnect-upstream-retry"
        core._save_bank_connections([{
            "id": connection_id, "workspace_id": "business", "item_fingerprint": "retry-item",
            "account_set_fingerprint": "retry-accounts", "protected_access_token": "cipher",
            "cursor": None, "institution": "Retry Bank", "account_masks": {},
            "created_at": core.utc_now(), "last_synced_at": None,
            "disconnect_state": None, "pending_sync": None,
        }])
        with patch.object(core, "_unprotect_bank_secret", return_value="access"), \
                patch.object(core, "_plaid_request", side_effect=[RuntimeError("timeout"), {}]) as plaid_request:
            with self.assertRaises(core.BankConnectorPartialError) as failure:
                core.disconnect_plaid_connection("business", connection_id, confirmed=True)
            self.assertEqual(failure.exception.details["state"], "upstream_revocation_not_confirmed")
            retained = core._load_bank_connections()[0]
            self.assertEqual(retained["disconnect_state"], "revocation_requested")
            self.assertEqual(retained["protected_access_token"], "cipher")
            recovered = core.disconnect_plaid_connection("business", connection_id, confirmed=True)
        self.assertTrue(recovered["disconnected"])
        self.assertEqual(plaid_request.call_count, 2)
        self.assertEqual(core._load_bank_connections(), [])

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

    def test_runtime_model_fallback_and_bounded_live_response(self):
        base = core.ChatResult("Deterministic answer", ["SRC-1"], ["invoice:1"], {"total": 42})
        with patch.dict(os.environ, {"PAYPROOF_MODEL_BASE_URL": "", "PAYPROOF_MODEL_API_KEY": ""}, clear=False):
            unchanged, status = core.explain_with_runtime_model("Explain it", base)
        self.assertEqual(status["state"], "deterministic_fallback")
        self.assertEqual(unchanged.answer, "Deterministic answer")
        fake_response = unittest.mock.MagicMock()
        grounded = "Deterministic answer; SRC-1."
        fake_response.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": grounded}}]}).encode()
        with patch.dict(os.environ, {"PAYPROOF_MODEL_BASE_URL": "http://model.test/v1", "PAYPROOF_MODEL_API_KEY": "test", "PAYPROOF_MODEL": "test-model"}, clear=False), patch("urllib.request.urlopen", return_value=fake_response):
            enhanced, status = core.explain_with_runtime_model("Explain it", base)
        self.assertEqual(status["state"], "live_model")
        self.assertEqual(enhanced.answer, grounded)
        self.assertEqual(enhanced.evidence_ids, ["SRC-1"])


class PayProofApiTests(IsolatedPayProofTestCase):
    def setUp(self):
        super().setUp()
        self.client = app_module.app.test_client()

    def test_judge_startup_endpoints(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        response.close()
        dashboard = self.client.get("/api/dashboard?workspace=business")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.get_json()["workspace"], "business")

    def test_chat_and_source_status(self):
        response = self.client.post("/api/chat", json={"question": "What data do you have?", "workspace": "business"})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.get_json()["evidence_ids"]), 0)
        with patch.dict(os.environ, {"PLAID_CLIENT_ID": "unit-client", "PLAID_SECRET": "unit-test-secret"}, clear=False):
            sources = self.client.get("/api/sources?workspace=business").get_json()
        self.assertIsInstance(sources["gmail"]["credentials_available"], bool)
        self.assertTrue(sources["intake_folder"]["available"])
        self.assertFalse(sources["bank"]["credentials_collected_by_payproof"])
        self.assertNotIn("unit-test-secret", json.dumps(sources))
        self.assertEqual(self.client.post("/api/sources/intake/scan").status_code, 200)
        questionnaire = self.client.get("/api/security/questionnaire").get_json()
        self.assertEqual(len(questionnaire["answers"]), 7)

    def test_empty_chat_and_bad_action_have_clear_errors(self):
        self.assertEqual(self.client.post("/api/chat", json={"question": ""}).status_code, 400)
        self.assertEqual(self.client.post("/api/actions", json={"finding_id": "F-ROUTE-001", "action": "pay"}).status_code, 400)

    def test_bank_preview_commit_reconciliation_and_confirmed_removal(self):
        content = ("date,description,amount,direction,currency,account_last4,reference,id\n"
                   "2026-08-27,Lakeside Bistro,186.45,debit,USD,4242,EXP-2026-043,ROW-1\n")
        response = self.client.post(
            "/api/import/bank/preview",
            data={"workspace": "business", "file": (io.BytesIO(content.encode()), "statement.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        preview = response.get_json()
        self.assertTrue(preview["accepted"][0]["matches"])
        committed = self.client.post("/api/import/bank/commit", json={"preview_id": preview["preview_id"], "workspace": "business"})
        self.assertEqual(committed.status_code, 200)
        source = next(item for item in self.client.get("/api/sources?workspace=business").get_json()["imports"] if item["kind"] == "bank")
        self.assertEqual(self.client.delete(f"/api/sources/{source['id']}?workspace=business&confirm=true").status_code, 400)
        removal = self.client.get(f"/api/sources/{source['id']}/removal-preview?workspace=business").get_json()
        deleted = self.client.delete(
            f"/api/sources/{source['id']}?workspace=business&confirm=true&preview_id={removal['preview_id']}"
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(deleted.get_json()["upstream_data_deleted"])

    def test_intake_edit_history_and_scoped_reset_api(self):
        edit = self.client.patch("/api/intake/expenses/EXP-2026-043", json={
            "workspace": "business", "changes": {"purpose": "Corrected in Settings"}, "reason": "User correction",
        })
        self.assertEqual(edit.status_code, 200)
        history = self.client.get("/api/intake/expenses/EXP-2026-043/history?workspace=business")
        self.assertEqual(len(history.get_json()["versions"]), 2)
        reset = self.client.post("/api/reset")
        self.assertEqual(reset.get_json()["scope"], "synthetic_demo_review_state")
        self.assertEqual(len(self.client.get("/api/intake/expenses/EXP-2026-043/history?workspace=business").get_json()["versions"]), 2)

    def test_gmail_disconnect_requires_bound_preview_before_any_token_change(self):
        root = Path(self.test_directory.name)
        credentials_path, token_path = root / "credentials.json", root / "gmail-business-token.dpapi.json"
        credentials_path.write_text("{}", encoding="utf-8")
        token_path.write_text("encrypted-token-envelope", encoding="utf-8")
        with patch.object(app_module, "_gmail_paths", return_value=(credentials_path, token_path)), \
                patch.object(app_module.secure_credentials, "secure_storage_available", return_value=True):
            self.assertEqual(self.client.post("/api/sources/gmail/disconnect", json={}).status_code, 400)
            result = self.client.post("/api/sources/gmail/disconnect", json={
                "workspace": "business", "session_id": "test-session", "confirm": True,
            })
        self.assertEqual(result.status_code, 400)
        self.assertTrue(token_path.exists())

    def test_unconfigured_plaid_endpoints_fail_truthfully(self):
        with patch.dict(os.environ, {"PLAID_CLIENT_ID": "", "PLAID_SECRET": ""}, clear=False):
            status = self.client.get("/api/sources/bank/status?workspace=business")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.get_json()["configuration_state"], "not_configured")
            link = self.client.post("/api/sources/bank/link-token", json={"workspace": "business"})
        self.assertEqual(link.status_code, 503)
        self.assertFalse(link.get_json()["connected"])

    def test_plaid_disconnect_preview_is_one_time_session_and_workspace_bound(self):
        connection_id = "shared-api-connection"
        now = core.utc_now()
        core._save_bank_connections([
            {"id": connection_id, "workspace_id": "business", "item_fingerprint": "business-item",
             "protected_access_token": "cipher-business", "cursor": None, "institution": "Business Bank",
             "account_masks": {}, "created_at": now, "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
            {"id": connection_id, "workspace_id": "personal", "item_fingerprint": "personal-item",
             "protected_access_token": "cipher-personal", "cursor": None, "institution": "Personal Bank",
             "account_masks": {}, "created_at": now, "last_synced_at": None,
             "disconnect_state": None, "pending_sync": None},
        ])
        self.assertEqual(
            self.client.get(f"/api/sources/bank/{connection_id}/disconnect-preview?workspace=business").status_code,
            400,
        )
        preview = self.client.get(
            f"/api/sources/bank/{connection_id}/disconnect-preview?workspace=business&session_id=session-a"
        ).get_json()
        self.assertNotIn("session-a", repr(app_module.BANK_DISCONNECT_PREVIEWS))
        mismatch = self.client.delete(f"/api/sources/bank/{connection_id}", json={
            "confirm": True, "workspace": "personal", "session_id": "session-a",
            "preview_id": preview["preview_id"],
        })
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(len(core._load_bank_connections()), 2)

        payload = {"confirm": True, "workspace": "business", "session_id": "session-a",
                   "preview_id": preview["preview_id"]}
        with patch.object(core, "_unprotect_bank_secret", return_value="access-business"), \
                patch.object(core, "_plaid_request", return_value={}) as plaid_request:
            removed = self.client.delete(f"/api/sources/bank/{connection_id}", json=payload)
            replay = self.client.delete(f"/api/sources/bank/{connection_id}", json=payload)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(plaid_request.call_count, 1)
        self.assertEqual(
            [(item["id"], item["workspace_id"]) for item in core._load_bank_connections()],
            [(connection_id, "personal")],
        )
        business_actions = [item["action"] for item in core.get_dashboard("business")["audit"]
                            if item["finding_id"] == connection_id]
        personal_actions = [item["action"] for item in core.get_dashboard("personal")["audit"]
                            if item["finding_id"] == connection_id]
        self.assertIn("bank_disconnect_requested", business_actions)
        self.assertIn("bank_disconnect", business_actions)
        self.assertFalse(any(action.startswith("bank_disconnect") for action in personal_actions))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is only available on Windows")
    def test_windows_dpapi_bank_secret_round_trip(self):
        value = "synthetic-secret"
        protected = core._protect_bank_secret(value)
        self.assertNotEqual(protected, value)
        self.assertEqual(core._unprotect_bank_secret(protected), value)

    def test_plaid_adapter_uses_mocked_network_and_never_persists_plain_tokens(self):
        responses = [
            {"link_token": "link-sandbox-test", "expiration": "2026-09-05T12:00:00Z"},
            {"access_token": "access-secret-test", "item_id": "item-test"},
            {"accounts": [{"account_id": "acct-1", "mask": "6789"}]},
            {"added": [{"transaction_id": "plaid-tx-1", "account_id": "acct-1", "amount": 10.50,
                         "iso_currency_code": "USD", "date": "2026-09-05", "merchant_name": "Example Cafe",
                         "pending": False}], "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False},
            {},
        ]
        with patch.dict(os.environ, {"PLAID_CLIENT_ID": "client-test", "PLAID_SECRET": "server-secret", "PLAID_ENV": "sandbox",
                                         "PLAID_REDIRECT_URI": "https://localhost.example/plaid/callback"}, clear=False), \
                patch.object(core, "_bank_secure_storage_available", return_value=True), \
                patch.object(core, "_protect_bank_secret", return_value="dpapi-ciphertext"), \
                patch.object(core, "_unprotect_bank_secret", return_value="access-secret-test"), \
                patch.object(core, "_plaid_request", side_effect=responses) as plaid_request:
            link = core.create_plaid_link_token("business", "session-test")
            connection = core.exchange_plaid_public_token("business", "public-temporary-test", "Example Bank")
            stored = core.BANK_CONNECTIONS_PATH.read_text(encoding="utf-8")
            self.assertNotIn("access-secret-test", stored)
            self.assertNotIn("public-temporary-test", stored)
            self.assertNotIn("acct-1", stored)
            synced = core.sync_plaid_transactions("business", connection["id"])
            disconnected = core.disconnect_plaid_connection("business", connection["id"], confirmed=True)
        self.assertEqual(link["link_token"], "link-sandbox-test")
        self.assertEqual(plaid_request.call_args_list[0].args[1]["redirect_uri"],
                         "https://localhost.example/plaid/callback")
        self.assertEqual(synced["added"], 1)
        plaid_row = next(row for row in core.get_dashboard("business")["bank_transactions"] if row["provider"] == "plaid")
        self.assertEqual(plaid_row["account_mask"], "****6789")
        self.assertTrue(disconnected["upstream_connection_revoked"])
        self.assertEqual([call.args[0] for call in plaid_request.call_args_list],
                         ["/link/token/create", "/item/public_token/exchange", "/accounts/get",
                          "/transactions/sync", "/item/remove"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
