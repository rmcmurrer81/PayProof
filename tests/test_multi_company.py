from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


class MultiCompanyIsolationTests(unittest.TestCase):
    """Adversarial coverage for tenant IDs reused by independent companies."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="payproof-multi-company-"
        )
        self.root = Path(self.temporary_directory.name).resolve()
        self.runtime = self.root / "runtime"
        self.demo_intake = self.root / "demo-intake"
        self.default_intake = self.root / "default-intake"
        self.project_root = self.root / "project"
        for directory in (
            self.runtime,
            self.demo_intake,
            self.default_intake,
            self.project_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.environment_patcher = patch.dict(
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
        self.environment_patcher.start()
        self.patchers = [
            patch.object(core, "PROJECT_ROOT", self.project_root),
            patch.object(core, "RUNTIME_DIR", self.runtime),
            patch.object(core, "DB_PATH", self.runtime / "payproof.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", self.runtime / "prism-queue.jsonl"),
            patch.object(core, "BANK_CONNECTIONS_PATH", self.runtime / "bank-connections.json"),
            patch.object(core, "DEMO_INTAKE_DIR", self.demo_intake),
            patch.object(core, "USER_INTAKE_DIR", self.default_intake),
            patch.object(app_module, "PROJECT_ROOT", self.project_root),
        ]
        for patcher in self.patchers:
            patcher.start()

        app_module.BANK_PREVIEWS.clear()
        app_module.OCR_PREVIEWS.clear()
        app_module.OAUTH_STATE.clear()
        app_module.SOURCE_REMOVAL_PREVIEWS.clear()
        app_module.BANK_DISCONNECT_PREVIEWS.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        app_module.app.config.update(TESTING=True)
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()
        self.company_a = self._create_company("Alpha Ledger Works")
        self.company_b = self._create_company("Beta Harbor Books")

    def tearDown(self) -> None:
        app_module.BANK_PREVIEWS.clear()
        app_module.OCR_PREVIEWS.clear()
        app_module.OAUTH_STATE.clear()
        app_module.SOURCE_REMOVAL_PREVIEWS.clear()
        app_module.BANK_DISCONNECT_PREVIEWS.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.environment_patcher.stop()
        self.temporary_directory.cleanup()

    def _create_company(self, name: str) -> str:
        response = self.client.post("/api/workspaces", json={"name": name})
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["name"], name)
        self.assertEqual(payload["kind"], "company")
        self.assertFalse(payload["is_demo"])
        return payload["id"]

    def _import_transaction_csv(
        self,
        workspace: str,
        *,
        external_id: str,
        merchant: str,
        amount: str,
        filename: str,
    ) -> dict:
        content = (
            "id,merchant,amount,currency,date,office\n"
            f"{external_id},{merchant},{amount},USD,2026-09-05,Main Office\n"
        )
        response = self.client.post(
            "/api/import/transactions",
            data={
                "workspace": workspace,
                "commit": "true",
                "file": (io.BytesIO(content.encode("utf-8")), filename),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["committed"], payload)
        self.assertEqual(payload["errors"], [])
        return payload

    def _preview_bank(self, workspace: str, content: str, filename: str) -> dict:
        response = self.client.post(
            "/api/import/bank/preview",
            data={
                "workspace": workspace,
                "file": (io.BytesIO(content.encode("utf-8")), filename),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload["errors"], [])
        self.assertEqual(len(payload["accepted"]), 1)
        return payload

    def _commit_bank(self, workspace: str, preview_id: str) -> dict:
        response = self.client.post(
            "/api/import/bank/commit",
            json={"workspace": workspace, "preview_id": preview_id},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["committed"], payload)
        return payload

    @staticmethod
    def _expense_payload(
        *, expense_id: str, merchant: str, amount: str, purpose: str
    ) -> dict:
        return {
            "id": expense_id,
            "document_type": "employee_expense_report",
            "employee": "Alex Shared",
            "department": "Operations",
            "office": "Main Office",
            "merchant": merchant,
            "amount": amount,
            "currency": "USD",
            "date": "2026-09-05",
            "category": "Office supplies",
            "purpose": purpose,
            "receipt_status": "missing",
            "approval_status": "needs_review",
        }

    def _add_intake_folder(
        self,
        workspace: str,
        root: Path,
        *,
        label: str,
        include_subfolders: bool,
    ) -> dict:
        response = self.client.post(
            f"/api/workspaces/{workspace}/intake-folders",
            json={
                "path": str(root),
                "label": label,
                "include_subfolders": include_subfolders,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def test_workspace_api_create_list_rename_and_protect_demo_workspaces(self) -> None:
        listing = self.client.get("/api/workspaces")
        self.assertEqual(listing.status_code, 200)
        by_id = {item["id"]: item for item in listing.get_json()["workspaces"]}
        self.assertIn("business", by_id)
        self.assertIn("personal", by_id)
        self.assertIn(self.company_a, by_id)
        self.assertIn(self.company_b, by_id)

        renamed = self.client.patch(
            f"/api/workspaces/{self.company_a}", json={"name": "Alpha Operations"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.get_data(as_text=True))
        self.assertEqual(renamed.get_json()["id"], self.company_a)
        self.assertEqual(renamed.get_json()["name"], "Alpha Operations")
        refreshed = {
            item["id"]: item
            for item in self.client.get("/api/workspaces").get_json()["workspaces"]
        }
        self.assertEqual(refreshed[self.company_a]["name"], "Alpha Operations")
        self.assertEqual(refreshed[self.company_b]["name"], "Beta Harbor Books")

        duplicate = self.client.post(
            "/api/workspaces", json={"name": "Alpha Operations"}
        )
        self.assertEqual(duplicate.status_code, 400)
        protected_demo = self.client.patch(
            "/api/workspaces/business", json={"name": "Do Not Rename"}
        )
        self.assertEqual(protected_demo.status_code, 400)

    def test_same_external_csv_transaction_id_has_no_collision_or_leak(self) -> None:
        external_id = "SHARED-CSV-TX-001"
        imported_a = self._import_transaction_csv(
            self.company_a,
            external_id=external_id,
            merchant="Alpha Exclusive Supply",
            amount="101.11",
            filename="alpha-transactions.csv",
        )
        imported_b = self._import_transaction_csv(
            self.company_b,
            external_id=external_id,
            merchant="Beta Exclusive Supply",
            amount="202.22",
            filename="beta-transactions.csv",
        )
        self.assertEqual(imported_a["accepted"][0]["id"], external_id)
        self.assertEqual(imported_b["accepted"][0]["id"], external_id)

        dashboard_a = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        dashboard_b = self.client.get(
            f"/api/dashboard?workspace={self.company_b}"
        ).get_json()
        transaction_a = dashboard_a["transactions"][0]
        transaction_b = dashboard_b["transactions"][0]
        self.assertEqual(transaction_a["merchant_raw"], "Alpha Exclusive Supply")
        self.assertEqual(transaction_b["merchant_raw"], "Beta Exclusive Supply")
        self.assertEqual(transaction_a["reference"], external_id)
        self.assertEqual(transaction_b["reference"], external_id)
        self.assertEqual(transaction_a["workspace_id"], self.company_a)
        self.assertEqual(transaction_b["workspace_id"], self.company_b)
        self.assertNotEqual(transaction_a["id"], transaction_b["id"])
        self.assertNotIn("Beta", transaction_a["merchant_raw"])
        self.assertNotIn("Alpha", transaction_b["merchant_raw"])

        own_record = self.client.get(
            f"/api/records/transaction:{transaction_a['id']}?workspace={self.company_a}"
        )
        cross_record = self.client.get(
            f"/api/records/transaction:{transaction_a['id']}?workspace={self.company_b}"
        )
        self.assertEqual(own_record.status_code, 200)
        self.assertEqual(cross_record.status_code, 404)
        source_names_a = {
            item["filename"]
            for item in self.client.get(
                f"/api/sources?workspace={self.company_a}"
            ).get_json()["imports"]
        }
        source_names_b = {
            item["filename"]
            for item in self.client.get(
                f"/api/sources?workspace={self.company_b}"
            ).get_json()["imports"]
        }
        self.assertEqual(source_names_a, {"alpha-transactions.csv"})
        self.assertEqual(source_names_b, {"beta-transactions.csv"})

    def test_identical_local_bank_statement_imports_into_both_companies(self) -> None:
        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-09-05,Shared Bank Merchant,44.55,debit,USD,4242,SHARED-REF,ROW-1\n"
        )
        preview_a = self._preview_bank(
            self.company_a, statement, "identical-statement.csv"
        )
        preview_b = self._preview_bank(
            self.company_b, statement, "identical-statement.csv"
        )
        provider_row_id = preview_a["accepted"][0]["id"]
        self.assertEqual(provider_row_id, preview_b["accepted"][0]["id"])
        committed_a = self._commit_bank(self.company_a, preview_a["preview_id"])
        committed_b = self._commit_bank(self.company_b, preview_b["preview_id"])
        self.assertNotEqual(committed_a["import_id"], committed_b["import_id"])

        dashboard_a = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        dashboard_b = self.client.get(
            f"/api/dashboard?workspace={self.company_b}"
        ).get_json()
        bank_a = dashboard_a["bank_transactions"]
        bank_b = dashboard_b["bank_transactions"]
        self.assertEqual(len(bank_a), 1)
        self.assertEqual(len(bank_b), 1)
        self.assertEqual(bank_a[0]["workspace_id"], self.company_a)
        self.assertEqual(bank_b[0]["workspace_id"], self.company_b)
        self.assertEqual(bank_a[0]["description"], "Shared Bank Merchant")
        self.assertEqual(bank_b[0]["description"], "Shared Bank Merchant")
        self.assertNotEqual(bank_a[0]["id"], bank_b[0]["id"])
        self.assertEqual(
            bank_a[0]["id"], f"{self.company_a}--local-bank--{provider_row_id}"
        )
        self.assertEqual(
            bank_b[0]["id"], f"{self.company_b}--local-bank--{provider_row_id}"
        )
        self.assertEqual(
            self.client.get(
                f"/api/records/bank:{bank_a[0]['id']}?workspace={self.company_b}"
            ).status_code,
            404,
        )
        self.assertEqual(
            [item["kind"] for item in self.client.get(
                f"/api/sources?workspace={self.company_a}"
            ).get_json()["imports"]],
            ["bank"],
        )
        self.assertEqual(
            [item["kind"] for item in self.client.get(
                f"/api/sources?workspace={self.company_b}"
            ).get_json()["imports"]],
            ["bank"],
        )

    def test_same_gmail_message_id_is_isolated_between_companies(self) -> None:
        message_id = "SAME-GMAIL-PROVIDER-ID"
        result_a = core.import_gmail_metadata(
            [{
                "id": message_id,
                "sender": "billing@example.test",
                "subject": "Alpha receipt only",
                "received_at": "2026-09-05",
                "snippet": "Evidence explicitly assigned to Alpha.",
            }],
            self.company_a,
        )
        result_b = core.import_gmail_metadata(
            [{
                "id": message_id,
                "sender": "billing@example.test",
                "subject": "Beta receipt only",
                "received_at": "2026-09-05",
                "snippet": "Evidence explicitly assigned to Beta.",
            }],
            self.company_b,
        )
        self.assertEqual(result_a, {"accepted": 1, "skipped": 0})
        self.assertEqual(result_b, {"accepted": 1, "skipped": 0})
        self.assertEqual(
            core.import_gmail_metadata([{"id": message_id}], self.company_a)["skipped"],
            1,
        )

        dashboard_a = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        dashboard_b = self.client.get(
            f"/api/dashboard?workspace={self.company_b}"
        ).get_json()
        email_a = dashboard_a["emails"][0]
        email_b = dashboard_b["emails"][0]
        self.assertEqual(email_a["subject"], "Alpha receipt only")
        self.assertEqual(email_b["subject"], "Beta receipt only")
        self.assertEqual(email_a["workspace_id"], self.company_a)
        self.assertEqual(email_b["workspace_id"], self.company_b)
        self.assertNotEqual(email_a["id"], email_b["id"])
        self.assertEqual(
            self.client.get(
                f"/api/records/email:{email_a['id']}?workspace={self.company_b}"
            ).status_code,
            404,
        )
        sources_a = self.client.get(
            f"/api/sources?workspace={self.company_a}"
        ).get_json()
        sources_b = self.client.get(
            f"/api/sources?workspace={self.company_b}"
        ).get_json()
        self.assertEqual(sources_a["imports"][0]["record_count"], 1)
        self.assertEqual(sources_b["imports"][0]["record_count"], 1)

    def test_nested_intake_with_same_expense_and_employee_ids_is_isolated(self) -> None:
        root_a = self.root / "alpha-intake"
        root_b = self.root / "beta-intake"
        nested_a = root_a / "team" / "receipts"
        nested_b = root_b / "team" / "receipts"
        nested_a.mkdir(parents=True)
        nested_b.mkdir(parents=True)
        (nested_a / "shared-expense.json").write_text(
            json.dumps(self._expense_payload(
                expense_id="EXP-SHARED-001",
                merchant="Alpha Office Shop",
                amount="31.11",
                purpose="Alpha supplies",
            )),
            encoding="utf-8",
        )
        (nested_b / "shared-expense.json").write_text(
            json.dumps(self._expense_payload(
                expense_id="EXP-SHARED-001",
                merchant="Beta Office Shop",
                amount="62.22",
                purpose="Beta supplies",
            )),
            encoding="utf-8",
        )
        folder_a = self._add_intake_folder(
            self.company_a, root_a, label="Shared Intake", include_subfolders=True
        )
        folder_b = self._add_intake_folder(
            self.company_b, root_b, label="Shared Intake", include_subfolders=True
        )
        scan_a = self.client.post(
            "/api/sources/intake/scan",
            json={"workspace": self.company_a, "folder_id": folder_a["id"]},
        )
        scan_b = self.client.post(
            "/api/sources/intake/scan",
            json={"workspace": self.company_b, "folder_id": folder_b["id"]},
        )
        self.assertEqual(scan_a.status_code, 200, scan_a.get_data(as_text=True))
        self.assertEqual(scan_b.status_code, 200, scan_b.get_data(as_text=True))
        self.assertEqual(scan_a.get_json()["accepted"], 1)
        self.assertEqual(scan_b.get_json()["accepted"], 1)

        dashboard_a = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        dashboard_b = self.client.get(
            f"/api/dashboard?workspace={self.company_b}"
        ).get_json()
        expense_a = dashboard_a["expenses"][0]
        expense_b = dashboard_b["expenses"][0]
        employee_a = dashboard_a["employees"][0]
        employee_b = dashboard_b["employees"][0]
        self.assertEqual(expense_a["merchant"], "Alpha Office Shop")
        self.assertEqual(expense_b["merchant"], "Beta Office Shop")
        self.assertEqual(expense_a["id"], f"{self.company_a}--EXP-SHARED-001")
        self.assertEqual(expense_b["id"], f"{self.company_b}--EXP-SHARED-001")
        self.assertEqual(employee_a["id"], f"{self.company_a}--alex-shared")
        self.assertEqual(employee_b["id"], f"{self.company_b}--alex-shared")
        self.assertNotEqual(expense_a["id"], expense_b["id"])
        self.assertNotEqual(employee_a["id"], employee_b["id"])
        self.assertEqual(dashboard_a["documents"][0]["filename"], "team/receipts/shared-expense.json")
        self.assertEqual(dashboard_b["documents"][0]["filename"], "team/receipts/shared-expense.json")
        self.assertEqual(
            self.client.get(
                f"/api/records/expense:{expense_a['id']}?workspace={self.company_b}"
            ).status_code,
            404,
        )

    def test_intake_folder_update_disable_and_removal_preserve_data_and_files(self) -> None:
        original_root = self.root / "lifecycle-intake"
        nested = original_root / "nested"
        nested.mkdir(parents=True)
        original_file = nested / "expense.json"
        original_file.write_text(
            json.dumps(self._expense_payload(
                expense_id="EXP-LIFECYCLE-001",
                merchant="Lifecycle Merchant",
                amount="77.77",
                purpose="Folder lifecycle coverage",
            )),
            encoding="utf-8",
        )
        folder = self._add_intake_folder(
            self.company_a,
            original_root,
            label="Lifecycle Original",
            include_subfolders=False,
        )
        first_scan = self.client.post(
            "/api/sources/intake/scan",
            json={"workspace": self.company_a, "folder_id": folder["id"]},
        )
        self.assertEqual(first_scan.status_code, 200)
        self.assertEqual(first_scan.get_json()["accepted"], 0)

        recursive = self.client.patch(
            f"/api/workspaces/{self.company_a}/intake-folders/{folder['id']}",
            json={"label": "Lifecycle Recursive", "include_subfolders": True},
        )
        self.assertEqual(recursive.status_code, 200, recursive.get_data(as_text=True))
        self.assertTrue(recursive.get_json()["include_subfolders"])
        imported = self.client.post(
            "/api/sources/intake/scan",
            json={"workspace": self.company_a, "folder_id": folder["id"]},
        )
        self.assertEqual(imported.status_code, 200, imported.get_data(as_text=True))
        self.assertEqual(imported.get_json()["accepted"], 1)

        cross_company_update = self.client.patch(
            f"/api/workspaces/{self.company_b}/intake-folders/{folder['id']}",
            json={"enabled": False},
        )
        self.assertEqual(cross_company_update.status_code, 400)
        disabled = self.client.patch(
            f"/api/workspaces/{self.company_a}/intake-folders/{folder['id']}",
            json={"enabled": False},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.get_json()["enabled"])
        disabled_scan = self.client.post(
            "/api/sources/intake/scan",
            json={"workspace": self.company_a, "folder_id": folder["id"]},
        )
        self.assertEqual(disabled_scan.status_code, 400)

        replacement_root = self.root / "replacement-intake"
        replacement_root.mkdir()
        updated = self.client.patch(
            f"/api/workspaces/{self.company_a}/intake-folders/{folder['id']}",
            json={
                "enabled": True,
                "path": str(replacement_root),
                "label": "Lifecycle Replacement",
                "include_subfolders": False,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_data(as_text=True))
        self.assertTrue(updated.get_json()["enabled"])
        self.assertEqual(updated.get_json()["path"], str(replacement_root.resolve()))
        self.assertFalse(updated.get_json()["include_subfolders"])

        no_confirmation = self.client.delete(
            f"/api/workspaces/{self.company_a}/intake-folders/{folder['id']}",
            json={"confirm": False},
        )
        self.assertEqual(no_confirmation.status_code, 400)
        wrong_company = self.client.delete(
            f"/api/workspaces/{self.company_b}/intake-folders/{folder['id']}",
            json={"confirm": True},
        )
        self.assertEqual(wrong_company.status_code, 400)
        removed = self.client.delete(
            f"/api/workspaces/{self.company_a}/intake-folders/{folder['id']}",
            json={"confirm": True},
        )
        self.assertEqual(removed.status_code, 200, removed.get_data(as_text=True))
        removal = removed.get_json()
        self.assertTrue(removal["removed"])
        self.assertFalse(removal["files_deleted"])
        self.assertTrue(removal["imported_records_preserved"])
        self.assertTrue(original_file.exists())
        self.assertTrue(replacement_root.exists())

        folders = self.client.get(
            f"/api/workspaces/{self.company_a}/intake-folders"
        ).get_json()["folders"]
        self.assertNotIn(folder["id"], {item["id"] for item in folders})
        dashboard = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        self.assertEqual(len(dashboard["expenses"]), 1)
        self.assertEqual(dashboard["expenses"][0]["merchant"], "Lifecycle Merchant")

    def test_dashboard_sources_and_same_session_chat_are_company_scoped(self) -> None:
        self._import_transaction_csv(
            self.company_a,
            external_id="CHAT-SHARED-ID",
            merchant="Alpha Chat Merchant",
            amount="111.11",
            filename="alpha-chat.csv",
        )
        self._import_transaction_csv(
            self.company_b,
            external_id="CHAT-SHARED-ID",
            merchant="Beta Chat Merchant",
            amount="222.22",
            filename="beta-chat.csv",
        )
        core.import_gmail_metadata(
            [{"id": "ALPHA-CHAT-MAIL", "subject": "Alpha mail only"}],
            self.company_a,
        )
        core.import_gmail_metadata(
            [{"id": "BETA-CHAT-MAIL", "subject": "Beta mail only"}],
            self.company_b,
        )

        dashboard_a = self.client.get(
            f"/api/dashboard?workspace={self.company_a}"
        ).get_json()
        dashboard_b = self.client.get(
            f"/api/dashboard?workspace={self.company_b}"
        ).get_json()
        self.assertEqual(
            {item["merchant_raw"] for item in dashboard_a["transactions"]},
            {"Alpha Chat Merchant"},
        )
        self.assertEqual(
            {item["merchant_raw"] for item in dashboard_b["transactions"]},
            {"Beta Chat Merchant"},
        )
        self.assertTrue(all(
            item["workspace_id"] == self.company_a
            for collection in ("transactions", "emails", "bank_transactions", "expenses")
            for item in dashboard_a[collection]
        ))
        self.assertTrue(all(
            item["workspace_id"] == self.company_b
            for collection in ("transactions", "emails", "bank_transactions", "expenses")
            for item in dashboard_b[collection]
        ))

        sources_a = self.client.get(
            f"/api/sources?workspace={self.company_a}"
        ).get_json()
        sources_b = self.client.get(
            f"/api/sources?workspace={self.company_b}"
        ).get_json()
        self.assertEqual(
            {item["label"] for item in sources_a["imports"]},
            {"Gmail · read-only metadata", "alpha-chat.csv"},
        )
        self.assertEqual(
            {item["label"] for item in sources_b["imports"]},
            {"Gmail · read-only metadata", "beta-chat.csv"},
        )

        session_id = "one-browser-session"
        chat_a = self.client.post(
            "/api/chat",
            json={
                "workspace": self.company_a,
                "session_id": session_id,
                "question": "Show the largest transaction",
            },
        )
        chat_b = self.client.post(
            "/api/chat",
            json={
                "workspace": self.company_b,
                "session_id": session_id,
                "question": "Show the largest transaction",
            },
        )
        self.assertEqual(chat_a.status_code, 200, chat_a.get_data(as_text=True))
        self.assertEqual(chat_b.status_code, 200, chat_b.get_data(as_text=True))
        self.assertIn("Alpha Chat Merchant", chat_a.get_json()["answer"])
        self.assertNotIn("Beta Chat Merchant", chat_a.get_json()["answer"])
        self.assertIn("Beta Chat Merchant", chat_b.get_json()["answer"])
        self.assertNotIn("Alpha Chat Merchant", chat_b.get_json()["answer"])
        history_a = self.client.get(
            f"/api/chat/history?workspace={self.company_a}&session_id={session_id}"
        ).get_json()
        history_b = self.client.get(
            f"/api/chat/history?workspace={self.company_b}&session_id={session_id}"
        ).get_json()
        self.assertEqual(len(history_a), 2)
        self.assertEqual(len(history_b), 2)
        serialized_a = json.dumps(history_a)
        serialized_b = json.dumps(history_b)
        self.assertIn("Alpha Chat Merchant", serialized_a)
        self.assertNotIn("Beta Chat Merchant", serialized_a)
        self.assertIn("Beta Chat Merchant", serialized_b)
        self.assertNotIn("Alpha Chat Merchant", serialized_b)

    def test_unknown_workspace_is_rejected_by_mutating_and_source_endpoints(self) -> None:
        unknown = "company-does-not-exist-99999999"
        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-09-05,Unknown Merchant,10.00,debit,USD,4242,UNKNOWN,ROW-1\n"
        )
        transaction = (
            "id,merchant,amount,currency,date,office\n"
            "UNKNOWN-TX,Unknown Merchant,10.00,USD,2026-09-05,Nowhere\n"
        )
        requests = [
            ("dashboard", self.client.get(f"/api/dashboard?workspace={unknown}"), 400),
            ("sources", self.client.get(f"/api/sources?workspace={unknown}"), 400),
            ("gmail connect", self.client.get(
                f"/api/sources/gmail/connect?workspace={unknown}&session_id=test"
            ), 400),
            ("intake scan", self.client.post(
                "/api/sources/intake/scan", json={"workspace": unknown}
            ), 400),
            ("intake list", self.client.get(
                f"/api/workspaces/{unknown}/intake-folders"
            ), 404),
            ("intake add", self.client.post(
                f"/api/workspaces/{unknown}/intake-folders",
                json={"path": str(self.default_intake)},
            ), 400),
            ("workspace rename", self.client.patch(
                f"/api/workspaces/{unknown}", json={"name": "Phantom Company"}
            ), 400),
            ("transaction import", self.client.post(
                "/api/import/transactions",
                data={
                    "workspace": unknown,
                    "commit": "true",
                    "file": (io.BytesIO(transaction.encode("utf-8")), "unknown.csv"),
                },
                content_type="multipart/form-data",
            ), 400),
            ("bank preview", self.client.post(
                "/api/import/bank/preview",
                data={
                    "workspace": unknown,
                    "file": (io.BytesIO(statement.encode("utf-8")), "unknown-bank.csv"),
                },
                content_type="multipart/form-data",
            ), 400),
        ]
        for label, response, expected_status in requests:
            with self.subTest(endpoint=label):
                self.assertEqual(
                    response.status_code,
                    expected_status,
                    response.get_data(as_text=True),
                )
        with self.assertRaisesRegex(ValueError, "Unknown workspace"):
            core.import_gmail_metadata([{"id": "PHANTOM"}], unknown)
        with self.assertRaisesRegex(ValueError, "Unknown workspace"):
            core.get_dashboard(unknown)

    def test_unknown_workspace_chat_history_and_reconciliation_are_rejected(self) -> None:
        """No endpoint may create or query an unregistered phantom tenant."""

        unknown = "company-phantom-99999999"
        responses = [
            ("chat", self.client.post(
                "/api/chat",
                json={
                    "workspace": unknown,
                    "session_id": "phantom-session",
                    "question": "What sources do you have?",
                },
            )),
            ("chat history", self.client.get(
                f"/api/chat/history?workspace={unknown}&session_id=phantom-session"
            )),
            ("reconciliation", self.client.get(
                f"/api/reconciliation?workspace={unknown}"
            )),
        ]
        for label, response in responses:
            with self.subTest(endpoint=label):
                self.assertEqual(
                    response.status_code,
                    400,
                    response.get_data(as_text=True),
                )
        with closing(core._connect()) as connection:
            phantom_messages = connection.execute(
                "SELECT COUNT(*) FROM chat_history WHERE workspace_id=?", (unknown,)
            ).fetchone()[0]
        self.assertEqual(phantom_messages, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
