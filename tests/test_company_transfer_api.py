from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core
from src.company_transfer import CompanyTransferError


class CompanyTransferApiTests(unittest.TestCase):
    """Exercise the public company-transfer workflow against an isolated runtime."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="payproof-company-transfer-api-"
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
                "PAYPROOF_MODEL_API_KEY": "MODEL-ENV-SECRET-MUST-NOT-EXPORT",
                "PAYPROOF_MODEL": "",
                "PRISMTRACE_PROJECT_ID": "",
                "PRISMTRACE_API_KEY": "PRISM-ENV-SECRET-MUST-NOT-EXPORT",
                "PLAID_CLIENT_ID": "PLAID-CLIENT-MUST-NOT-EXPORT",
                "PLAID_SECRET": "PLAID-ENV-SECRET-MUST-NOT-EXPORT",
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
            patch.object(
                core, "BANK_CONNECTIONS_PATH", self.runtime / "bank-connections.json"
            ),
            patch.object(core, "DEMO_INTAKE_DIR", self.demo_intake),
            patch.object(core, "USER_INTAKE_DIR", self.default_intake),
            patch.object(app_module, "PROJECT_ROOT", self.project_root),
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

    def _create_company(self, name: str) -> dict:
        response = self.client.post(
            "/api/workspaces", json={"name": name, "website": "buyer.example.test"}
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def _export_count(self, workspace_id: str) -> int:
        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM audit WHERE workspace_id=? "
                    "AND action='export_company_transfer'",
                    (workspace_id,),
                ).fetchone()[0]
            )

    def _insert_export_evidence(
        self,
        workspace_id: str,
        marker: str,
        *,
        embedded_secret: str | None = None,
    ) -> None:
        vendor_id = f"{workspace_id}--vendor"
        transaction_id = f"{workspace_id}--transaction"
        email_id = f"{workspace_id}--email"
        snippet = f"Purchased notebooks for {marker}."
        if embedded_secret:
            snippet += (
                f" PLAID_SECRET={embedded_secret}"
                " Bearer abcdefghijklmnopQRSTUV"
                ' {"access_token":"DATABASE-TOKEN-MUST-NOT-EXPORT"}'
                " -----BEGIN PRIVATE KEY-----\n"
                "DATABASE-PRIVATE-KEY-MUST-NOT-EXPORT\n"
                "-----END PRIVATE KEY-----"
            )
        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            connection.execute(
                "INSERT INTO vendors(id,workspace_id,name,category) VALUES (?,?,?,?)",
                (vendor_id, workspace_id, f"Vendor {marker}", "Office"),
            )
            connection.execute(
                """INSERT INTO transactions(
                       id,workspace_id,vendor_id,merchant_raw,amount_cents,currency,
                       occurred_on,office,kind,source_id,reference
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    transaction_id,
                    workspace_id,
                    vendor_id,
                    f"Merchant {marker}",
                    4357,
                    "USD",
                    "2026-09-05",
                    "Main Office",
                    "purchase",
                    f"bank:{marker}",
                    f"REF-{marker}",
                ),
            )
            connection.execute(
                """INSERT INTO email_evidence(
                       id,workspace_id,provider,sender,subject,received_at,snippet,
                       source_label,is_synthetic,content_hash,imported_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    email_id,
                    workspace_id,
                    "gmail",
                    "orders@example.test",
                    f"Receipt {marker}",
                    "2026-09-05",
                    snippet,
                    "Gmail read-only metadata",
                    0,
                    f"hash-{marker}",
                    "2026-09-05T16:00:00+00:00",
                ),
            )
            connection.commit()

    def _transfer(self, company: dict):
        return self.client.post(
            f"/api/workspaces/{company['id']}/transfer-package",
            json={"confirm": True, "company_name": company["name"]},
        )

    @staticmethod
    def _open_zip(response) -> tuple[zipfile.ZipFile, io.BytesIO]:
        stream = io.BytesIO(response.data)
        return zipfile.ZipFile(stream), stream

    def test_confirmation_exact_name_and_custom_company_are_required_without_audit(self) -> None:
        company = self._create_company("Exact Transfer Name")
        url = f"/api/workspaces/{company['id']}/transfer-package"
        invalid_payloads = (
            {},
            {"confirm": False, "company_name": company["name"]},
            {"confirm": True},
            {"confirm": True, "company_name": "exact transfer name"},
            {"confirm": True, "company_name": "Wrong Company"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(url, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
                self.assertEqual(self._export_count(company["id"]), 0)

        for demo_id, demo_name in (
            ("business", "Meridian Works"),
            ("personal", "Robert Household"),
        ):
            with self.subTest(demo_id=demo_id):
                response = self.client.post(
                    f"/api/workspaces/{demo_id}/transfer-package",
                    json={"confirm": True, "company_name": demo_name},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("custom company", response.get_json()["error"].lower())
                self.assertEqual(self._export_count(demo_id), 0)

    def test_active_transfer_has_safe_headers_and_portable_readable_files(self) -> None:
        company = self._create_company("Portable Paperwork LLC")
        marker = "SELECTED-COMPANY-PAPERWORK-419"
        self._insert_export_evidence(company["id"], marker)

        self.assertEqual(self._export_count(company["id"]), 0)
        response = self._transfer(company)

        self.assertEqual(
            response.status_code, 200, f"unexpected transfer status {response.status_code}"
        )
        self.assertEqual(response.content_type, "application/zip")
        disposition = response.headers.get("Content-Disposition", "")
        self.assertRegex(
            disposition,
            r'^attachment; filename="payproof-portable-paperwork-llc-\d{8}\.zip"$',
        )
        self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(
            response.headers.get("X-PayProof-Credentials-Included"), "false"
        )

        archive, stream = self._open_zip(response)
        try:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertTrue(
                {
                    "index.html",
                    "README.txt",
                    "manifest.json",
                    "company-profile.json",
                    "json/transactions.json",
                    "csv/transactions.csv",
                    "json/email_evidence.json",
                    "csv/email_evidence.csv",
                }.issubset(names)
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["format"], "payproof-company-transfer")
            self.assertEqual(manifest["workspace"]["id"], company["id"])
            self.assertEqual(manifest["workspace"]["name"], company["name"])
            self.assertFalse(manifest["workspace"]["archived"])
            self.assertFalse(manifest["credentials_included"])

            html = archive.read("index.html").decode("utf-8")
            self.assertIn(company["name"], html)
            self.assertIn(marker, html)
            self.assertNotIn("<script", html.lower())
            self.assertNotIn('src="http', html.lower())

            rows = list(
                csv.DictReader(
                    io.StringIO(
                        archive.read("csv/transactions.csv").decode("utf-8-sig")
                    )
                )
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["workspace_id"], company["id"])
            self.assertIn(marker, rows[0]["merchant_raw"])
            self.assertIn("PayProof is not required", archive.read("README.txt").decode())
        finally:
            archive.close()
            stream.close()

        self.assertEqual(self._export_count(company["id"]), 1)

    def test_archived_custom_company_can_transfer_without_cross_company_records(self) -> None:
        sold = self._create_company("Sold Company")
        rival = self._create_company("Unrelated Company")
        sold_marker = "SOLD-COMPANY-ONLY-991"
        rival_marker = "RIVAL-COMPANY-MUST-STAY-PRIVATE-882"
        self._insert_export_evidence(sold["id"], sold_marker)
        self._insert_export_evidence(rival["id"], rival_marker)

        archived = self.client.delete(
            f"/api/workspaces/{sold['id']}",
            json={"confirm": True, "company_name": sold["name"]},
        )
        self.assertEqual(archived.status_code, 200, archived.get_data(as_text=True))
        self.assertTrue(archived.get_json()["is_archived"])

        response = self._transfer(sold)
        self.assertEqual(
            response.status_code, 200, f"unexpected transfer status {response.status_code}"
        )
        archive, stream = self._open_zip(response)
        try:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read("manifest.json"))
            self.assertTrue(manifest["workspace"]["archived"])
            combined = b"\n".join(archive.read(name) for name in archive.namelist()).decode(
                "utf-8", errors="replace"
            )
        finally:
            archive.close()
            stream.close()

        self.assertIn(sold_marker, combined)
        self.assertNotIn(rival_marker, combined)
        self.assertNotIn(rival["id"], combined)
        self.assertNotIn(rival["name"], combined)
        self.assertEqual(self._export_count(sold["id"]), 1)
        self.assertEqual(self._export_count(rival["id"]), 0)

    def test_transfer_redacts_evidence_secrets_and_excludes_connector_secret_files(self) -> None:
        company = self._create_company("Credential Safe Transfer")
        embedded_secret = "DATABASE-PLAID-SECRET-MUST-NOT-EXPORT"
        self._insert_export_evidence(
            company["id"], "SAFE-EXPORT-RECORD", embedded_secret=embedded_secret
        )

        (self.project_root / ".env").write_text(
            "PRIVATE_KEY=DOTENV-SECRET-MUST-NOT-EXPORT\n", encoding="utf-8"
        )
        core.BANK_CONNECTIONS_PATH.write_text(
            json.dumps({"access_token": "CONNECTOR-TOKEN-MUST-NOT-EXPORT"}),
            encoding="utf-8",
        )
        (self.project_root / "credentials.json").write_text(
            json.dumps({"client_secret": "GMAIL-SECRET-MUST-NOT-EXPORT"}),
            encoding="utf-8",
        )

        response = self._transfer(company)
        self.assertEqual(
            response.status_code, 200, f"unexpected transfer status {response.status_code}"
        )
        archive, stream = self._open_zip(response)
        try:
            combined = b"\n".join(archive.read(name) for name in archive.namelist()).decode(
                "utf-8", errors="replace"
            )
        finally:
            archive.close()
            stream.close()

        forbidden = (
            embedded_secret,
            "abcdefghijklmnopQRSTUV",
            "DATABASE-TOKEN-MUST-NOT-EXPORT",
            "DATABASE-PRIVATE-KEY-MUST-NOT-EXPORT",
            "DOTENV-SECRET-MUST-NOT-EXPORT",
            "CONNECTOR-TOKEN-MUST-NOT-EXPORT",
            "GMAIL-SECRET-MUST-NOT-EXPORT",
            "MODEL-ENV-SECRET-MUST-NOT-EXPORT",
            "PRISM-ENV-SECRET-MUST-NOT-EXPORT",
            "PLAID-CLIENT-MUST-NOT-EXPORT",
            "PLAID-ENV-SECRET-MUST-NOT-EXPORT",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, combined)
        self.assertIn("[REDACTED_CREDENTIAL]", combined)
        self.assertIn("[REDACTED_PRIVATE_KEY]", combined)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertFalse(
                json.loads(archive.read("manifest.json"))["credentials_included"]
            )

    def test_failed_package_build_does_not_write_export_audit_event(self) -> None:
        company = self._create_company("Fail Closed Export")
        self.assertEqual(self._export_count(company["id"]), 0)
        with patch.object(
            core,
            "build_company_transfer_zip",
            side_effect=CompanyTransferError("forced safe export failure"),
        ):
            response = self._transfer(company)

        self.assertEqual(response.status_code, 400)
        self.assertIn("forced safe export failure", response.get_json()["error"])
        self.assertEqual(self._export_count(company["id"]), 0)


if __name__ == "__main__":
    unittest.main()
