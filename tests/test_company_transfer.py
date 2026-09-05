from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import unittest
import zipfile

from src.company_transfer import (
    TABLE_COLUMNS,
    CompanyTransferError,
    CompanyTransferLimitError,
    build_company_transfer_zip,
    suggested_transfer_filename,
)


FIXED_TIME = "2026-09-05T16:30:00+00:00"


class CompanyTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "kind TEXT NOT NULL, is_demo INTEGER NOT NULL, website TEXT, "
            "logo_filename TEXT, archived_at TEXT)"
        )
        for table, columns in TABLE_COLUMNS.items():
            declarations = ", ".join(f'"{column}" TEXT' for column in columns)
            self.db.execute(f'CREATE TABLE "{table}" ({declarations})')

        self.db.executemany(
            "INSERT INTO workspaces(id,name,kind,is_demo,website,logo_filename,archived_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                ("company-acme", "<script>alert(1)</script> & Acme", "company", 0,
                 "https://acme.example", "private-runtime-logo.png", None),
                ("company-rival", "Rival Secret Co", "company", 0,
                 "https://rival.example", None, None),
                ("business", "Synthetic Demo", "demo", 1, None, None, None),
            ],
        )
        self._insert("vendors", {
            "id": "vendor-acme", "workspace_id": "company-acme", "name": "Amazon",
            "category": "Retail",
        })
        self._insert("vendors", {
            "id": "vendor-rival", "workspace_id": "company-rival",
            "name": "OTHER-COMPANY-PRIVATE-VENDOR", "category": "Secret",
        })
        self._insert("transactions", {
            "id": "txn-acme", "workspace_id": "company-acme",
            "vendor_id": "vendor-acme", "merchant_raw": '=HYPERLINK("https://bad")',
            "amount_cents": 4357, "currency": "USD", "occurred_on": "2026-09-01",
            "kind": "purchase", "source_id": "bank:acme", "reference": "AMZ-43",
        })
        self._insert("transactions", {
            "id": "txn-rival", "workspace_id": "company-rival",
            "vendor_id": "vendor-rival", "merchant_raw": "OTHER-COMPANY-PRIVATE-TXN",
            "amount_cents": 999999, "currency": "USD", "occurred_on": "2026-09-01",
            "kind": "purchase", "source_id": "bank:rival",
        })
        self._insert("invoices", {
            "id": "invoice-acme", "workspace_id": "company-acme",
            "vendor_id": "vendor-acme", "amount_cents": 4357, "currency": "USD",
            "invoice_date": "2026-09-01", "destination_masked": "****1234",
            "source_id": "email-acme", "status": "open",
        })
        self._insert("receipts", {
            "id": "receipt-acme", "workspace_id": "company-acme",
            "vendor_id": "vendor-acme", "amount_cents": 4357, "currency": "USD",
            "receipt_date": "2026-09-01", "transaction_id": "txn-acme",
            "source_id": "email-acme",
        })
        self._insert("employees", {
            "id": "employee-acme", "workspace_id": "company-acme", "name": "Alex",
            "department": "Operations", "office": "Boston",
        })
        self._insert("expense_reports", {
            "id": "expense-acme", "workspace_id": "company-acme",
            "employee_id": "employee-acme", "merchant": "Amazon",
            "amount_cents": 4357, "currency": "USD", "spent_on": "2026-09-01",
            "category": "Food", "purpose": "Team drinks", "receipt_status": "matched",
            "approval_status": "approved", "source_id": "intake:expense-acme",
        })
        self._insert("bank_transactions", {
            "id": "bank-acme", "workspace_id": "company-acme", "provider": "plaid",
            "account_mask": "****6789", "description": "Amazon Marketplace",
            "amount_cents": 4357, "currency": "USD", "posted_on": "2026-09-01",
            "direction": "outflow", "reference": "AMZ-43", "source_id": "plaid:masked",
            "is_synthetic": 0, "imported_at": FIXED_TIME,
        })
        self._insert("email_evidence", {
            "id": "email-acme", "workspace_id": "company-acme", "provider": "gmail",
            "sender": "orders@example.test", "subject": "Amazon order $43.57",
            "received_at": "2026-09-01", "snippet": (
                "Items: coffee filters and sparkling water. "
                "PLAID_SECRET=ultra-secret-selected Bearer abcdefghijklmnop "
                "{\"access_token\":\"nested-json-secret\"} "
                "-----BEGIN PRIVATE KEY-----\nprivate-key-material\n"
                "-----END PRIVATE KEY-----"
            ), "source_label": "Gmail read-only metadata", "is_synthetic": 0,
            "content_hash": "safe-content-hash", "imported_at": FIXED_TIME,
        })
        self._insert("email_evidence", {
            "id": "email-rival", "workspace_id": "company-rival", "provider": "gmail",
            "sender": "rival@example.test", "subject": "OTHER-COMPANY-PRIVATE-EMAIL",
            "snippet": "never export me", "source_label": "Gmail", "is_synthetic": 0,
            "content_hash": "rival-hash", "imported_at": FIXED_TIME,
        })
        self._insert("intake_documents", {
            "id": "doc-acme", "workspace_id": "company-acme", "filename": "expense.json",
            "document_type": "expense", "source_id": "intake:expense-acme",
            "employee_id": "employee-acme", "status": "accepted", "is_synthetic": 0,
            "content_hash": "doc-hash", "imported_at": FIXED_TIME,
        })
        self._insert("reconciliations", {
            "id": "match-acme", "workspace_id": "company-acme",
            "bank_transaction_id": "bank-acme", "evidence_type": "email",
            "evidence_id": "email-acme", "evidence_source_id": "email-acme",
            "confidence": 96, "match_basis": "amount, date, and merchant",
            "status": "suggested", "created_at": FIXED_TIME,
        })
        self._insert("intake_versions", {
            "id": 1, "workspace_id": "company-acme", "expense_id": "expense-acme",
            "version": 1, "snapshot_json": '{"amount_cents":4357}',
            "changed_fields": "[]", "reason": "Initial import", "source_kind": "intake",
            "created_at": FIXED_TIME,
        })
        self._insert("imports", {
            "id": "import-acme", "workspace_id": "company-acme",
            "filename": "statement.csv", "source_hash": "statement-hash",
            "accepted": 1, "rejected": 0, "created_at": FIXED_TIME,
        })
        self._insert("audit", {
            "id": 1, "workspace_id": "company-acme", "finding_id": "expense-acme",
            "action": "correct_intake", "reason": "Approved correction",
            "created_at": FIXED_TIME,
        })
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def _insert(self, table: str, values: dict) -> None:
        columns = tuple(values)
        placeholders = ",".join("?" for _ in columns)
        names = ",".join(f'"{column}"' for column in columns)
        self.db.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
            tuple(values[column] for column in columns),
        )

    def _archive(self) -> tuple[bytes, dict[str, bytes]]:
        content = build_company_transfer_zip(
            self.db, "company-acme", generated_at=FIXED_TIME,
        )
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            files = {name: archive.read(name) for name in archive.namelist()}
        return content, files

    def test_package_is_portable_complete_and_company_scoped(self) -> None:
        _, files = self._archive()
        self.assertIn("index.html", files)
        self.assertIn("README.txt", files)
        self.assertIn("manifest.json", files)
        self.assertIn("company-profile.json", files)
        for table in TABLE_COLUMNS:
            self.assertIn(f"json/{table}.json", files)
            self.assertIn(f"csv/{table}.csv", files)

        combined = b"\n".join(files.values()).decode("utf-8", errors="replace")
        self.assertIn("txn-acme", combined)
        self.assertIn("coffee filters", combined)
        self.assertNotIn("OTHER-COMPANY-PRIVATE", combined)
        self.assertNotIn("company-rival", combined)
        self.assertNotIn("private-runtime-logo.png", combined)
        self.assertNotIn("ultra-secret-selected", combined)
        self.assertNotIn("abcdefghijklmnop", combined)
        self.assertNotIn("nested-json-secret", combined)
        self.assertNotIn("private-key-material", combined)
        self.assertIn("[REDACTED_CREDENTIAL]", combined)
        self.assertIn("[REDACTED_PRIVATE_KEY]", combined)

        readme = files["README.txt"].decode("utf-8")
        self.assertIn("PayProof is not required", readme)
        self.assertIn("Excel, Google Sheets", readme)
        self.assertIn("must use their own authorization", readme)

    def test_manifest_hashes_and_byte_counts_every_payload(self) -> None:
        _, files = self._archive()
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["format"], "payproof-company-transfer")
        self.assertEqual(manifest["workspace"]["id"], "company-acme")
        self.assertFalse(manifest["credentials_included"])
        self.assertGreaterEqual(manifest["redactions"], 2)
        listed = {item["path"]: item for item in manifest["files"]}
        self.assertEqual(set(listed), set(files) - {"manifest.json"})
        for path, item in listed.items():
            self.assertEqual(item["bytes"], len(files[path]))
            self.assertEqual(item["sha256"], hashlib.sha256(files[path]).hexdigest())

    def test_html_escapes_evidence_and_csv_neutralizes_formulas(self) -> None:
        _, files = self._archive()
        report = files["index.html"].decode("utf-8")
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; Acme", report)
        self.assertIn("USD 43.57", report)
        self.assertNotIn("src=\"http", report)
        self.assertNotIn("<script", report.lower())

        transaction_csv = files["csv/transactions.csv"].decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", transaction_csv)

    def test_authorization_headers_are_redacted_without_leaving_tokens(self) -> None:
        bearer = "bearer-token-that-must-never-export"
        basic = "QWxhZGRpbjpvcGVuIHNlc2FtZQ=="
        self._insert("email_evidence", {
            "id": "email-auth", "workspace_id": "company-acme", "provider": "gmail",
            "sender": "security@example.test", "subject": "Connector debug output",
            "snippet": (
                f"Authorization: Bearer {bearer}\n"
                f'"proxy_authorization": "Basic {basic}"'
            ),
            "source_label": "Gmail", "is_synthetic": 0,
            "content_hash": "auth-header-hash", "imported_at": FIXED_TIME,
        })
        self.db.commit()

        _, files = self._archive()
        combined = b"\n".join(files.values()).decode("utf-8", errors="replace")
        self.assertNotIn(bearer, combined)
        self.assertNotIn(basic, combined)
        self.assertGreaterEqual(combined.count("[REDACTED_CREDENTIAL]"), 2)

    def test_fixed_timestamp_produces_deterministic_zip_bytes(self) -> None:
        first = build_company_transfer_zip(self.db, "company-acme", generated_at=FIXED_TIME)
        second = build_company_transfer_zip(self.db, "company-acme", generated_at=FIXED_TIME)
        self.assertEqual(first, second)

    def test_demo_unknown_and_incomplete_packages_fail_closed(self) -> None:
        with self.assertRaisesRegex(CompanyTransferError, "custom company"):
            build_company_transfer_zip(self.db, "business", generated_at=FIXED_TIME)
        with self.assertRaisesRegex(CompanyTransferError, "Unknown"):
            build_company_transfer_zip(self.db, "missing", generated_at=FIXED_TIME)

        self._insert("transactions", {
            "id": "txn-acme-2", "workspace_id": "company-acme",
            "vendor_id": "vendor-acme", "merchant_raw": "Amazon",
            "amount_cents": 100, "currency": "USD", "occurred_on": "2026-09-02",
            "kind": "purchase", "source_id": "bank:acme",
        })
        self.db.commit()
        with self.assertRaisesRegex(CompanyTransferLimitError, "transactions has 2 rows"):
            build_company_transfer_zip(
                self.db, "company-acme", generated_at=FIXED_TIME,
                max_rows_per_table=1,
            )

    def test_suggested_filename_is_path_safe(self) -> None:
        filename = suggested_transfer_filename("../Acme & Sons\\Payroll", FIXED_TIME)
        self.assertEqual(filename, "payproof-acme-sons-payroll-20260905.zip")
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)


if __name__ == "__main__":
    unittest.main()
