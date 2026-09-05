from __future__ import annotations

import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as app_module
import src.core as core


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"p" * 24)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + (b"j" * 24)
WEBP_BYTES = b"RIFF" + (24).to_bytes(4, "little") + b"WEBP" + (b"w" * 20)


class CompanyProfileApiTests(unittest.TestCase):
    """Company branding must remain validated and isolated by workspace."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="payproof-company-profile-"
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

        app_module.app.config.update(TESTING=True)
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.environment_patcher.stop()
        self.temporary_directory.cleanup()

    def _create_company(self, name: str, website: str | None = None) -> dict:
        payload: dict[str, str] = {"name": name}
        if website is not None:
            payload["website"] = website
        response = self.client.post("/api/workspaces", json=payload)
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        return response.get_json()

    def _upload(self, workspace: str, content: bytes, filename: str):
        return self.client.post(
            f"/api/workspaces/{workspace}/logo",
            data={"logo": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    def _import_transaction(self, workspace: str, external_id: str) -> str:
        content = (
            "id,merchant,amount,currency,date,office,direction\n"
            f"{external_id},Preserved Vendor,19.95,USD,2026-09-05,Main Office,debit\n"
        )
        response = self.client.post(
            "/api/import/transactions",
            data={
                "workspace": workspace,
                "commit": "true",
                "file": (io.BytesIO(content.encode("utf-8")), "preserved.csv"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertTrue(payload["committed"], payload)
        self.assertEqual(payload["errors"], [])
        return external_id

    def test_create_normalizes_website_and_never_leaks_logo_filename(self) -> None:
        company = self._create_company(
            "Northwind Books", "books.example.test/company?view=public"
        )
        self.assertEqual(
            company["website"], "https://books.example.test/company?view=public"
        )
        self.assertIsNone(company["logo_url"])
        self.assertNotIn("logo_filename", company)

        listing = self.client.get("/api/workspaces").get_json()["workspaces"]
        listed = next(item for item in listing if item["id"] == company["id"])
        self.assertEqual(listed["website"], company["website"])
        self.assertNotIn("logo_filename", listed)

        dashboard = self.client.get(
            "/api/dashboard", query_string={"workspace": company["id"]}
        ).get_json()
        selected = next(
            item for item in dashboard["workspaces"] if item["id"] == company["id"]
        )
        self.assertNotIn("logo_filename", selected)

    def test_patch_updates_name_and_website_and_rejects_invalid_fields(self) -> None:
        company = self._create_company("Original Company")
        response = self.client.patch(
            f"/api/workspaces/{company['id']}",
            json={"name": "Renamed Company", "website": "http://example.test/about"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["name"], "Renamed Company")
        self.assertEqual(response.get_json()["website"], "http://example.test/about")

        for payload in (
            {"website": "javascript:alert(1)"},
            {"website": "https://user:secret@example.test"},
            {"website": "https://bad host.example"},
            {"kind": "business"},
        ):
            with self.subTest(payload=payload):
                rejected = self.client.patch(
                    f"/api/workspaces/{company['id']}", json=payload
                )
                self.assertEqual(rejected.status_code, 400)
                self.assertIn("error", rejected.get_json())

        for demo_workspace in ("business", "personal"):
            rejected = self.client.patch(
                f"/api/workspaces/{demo_workspace}",
                json={"name": "Do Not Edit Demo"},
            )
            self.assertEqual(rejected.status_code, 400)

    def test_png_logo_round_trip_has_safe_headers(self) -> None:
        company = self._create_company("PNG Company")
        uploaded = self._upload(company["id"], PNG_BYTES, "brand.png")
        self.assertEqual(uploaded.status_code, 200, uploaded.get_data(as_text=True))
        payload = uploaded.get_json()
        self.assertEqual(payload["logo_url"], f"/api/workspaces/{company['id']}/logo")
        self.assertNotIn("logo_filename", payload)

        fetched = self.client.get(payload["logo_url"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.data, PNG_BYTES)
        self.assertEqual(fetched.mimetype, "image/png")
        self.assertIn("no-store", fetched.headers["Cache-Control"])
        self.assertEqual(fetched.headers["X-Content-Type-Options"], "nosniff")

    def test_jpeg_and_webp_signatures_are_detected_from_content(self) -> None:
        company = self._create_company("Multi Format Company")
        for content, misleading_name, expected_mime in (
            (JPEG_BYTES, "logo.png", "image/jpeg"),
            (WEBP_BYTES, "logo.jpg", "image/webp"),
        ):
            with self.subTest(mime=expected_mime):
                uploaded = self._upload(company["id"], content, misleading_name)
                self.assertEqual(uploaded.status_code, 200, uploaded.get_data(as_text=True))
                fetched = self.client.get(
                    f"/api/workspaces/{company['id']}/logo"
                )
                self.assertEqual(fetched.status_code, 200)
                self.assertEqual(fetched.data, content)
                self.assertEqual(fetched.mimetype, expected_mime)

    def test_bad_signature_oversize_missing_file_and_demo_upload_are_rejected(self) -> None:
        company = self._create_company("Rejected Logo Company")
        cases = (
            (b"not an image", "pretend.png"),
            (PNG_BYTES + (b"x" * (core.MAX_COMPANY_LOGO_BYTES + 1)), "huge.png"),
        )
        for content, filename in cases:
            with self.subTest(filename=filename):
                response = self._upload(company["id"], content, filename)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())

        missing = self.client.post(
            f"/api/workspaces/{company['id']}/logo",
            data={},
            content_type="multipart/form-data",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(self._upload("business", PNG_BYTES, "demo.png").status_code, 400)

    def test_logo_isolation_delete_confirmation_and_absent_state(self) -> None:
        company_a = self._create_company("Company A")
        company_b = self._create_company("Company B")
        uploaded = self._upload(company_a["id"], PNG_BYTES, "a.png")
        self.assertEqual(uploaded.status_code, 200)

        self.assertEqual(
            self.client.get(f"/api/workspaces/{company_b['id']}/logo").status_code,
            404,
        )
        denied = self.client.delete(f"/api/workspaces/{company_a['id']}/logo")
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/workspaces/{company_a['id']}/logo").status_code,
            200,
        )

        removed = self.client.delete(
            f"/api/workspaces/{company_a['id']}/logo", json={"confirm": True}
        )
        self.assertEqual(removed.status_code, 200, removed.get_data(as_text=True))
        self.assertTrue(removed.get_json()["logo_removed"])
        self.assertEqual(
            self.client.get(f"/api/workspaces/{company_a['id']}/logo").status_code,
            404,
        )
        absent = self.client.delete(
            f"/api/workspaces/{company_a['id']}/logo", json={"confirm": True}
        )
        self.assertEqual(absent.status_code, 200)
        self.assertEqual(absent.get_json()["state"], "already_absent")

    def test_stored_logo_path_is_not_exposed_and_other_company_cannot_select_it(self) -> None:
        company_a = self._create_company("Private Logo A")
        company_b = self._create_company("Private Logo B")
        self.assertEqual(self._upload(company_a["id"], PNG_BYTES, "a.png").status_code, 200)

        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            stored_filename = connection.execute(
                "SELECT logo_filename FROM workspaces WHERE id=?", (company_a["id"],)
            ).fetchone()[0]
            self.assertTrue(stored_filename)
            other_filename = connection.execute(
                "SELECT logo_filename FROM workspaces WHERE id=?", (company_b["id"],)
            ).fetchone()[0]
            self.assertIsNone(other_filename)

        serialized = self.client.get("/api/workspaces").get_data(as_text=True)
        self.assertNotIn(stored_filename, serialized)
        self.assertNotIn(str(self.runtime), serialized)

    def test_archive_requires_confirmation_and_exact_name_and_protects_demo(self) -> None:
        company = self._create_company("Archive Me Exactly")
        url = f"/api/workspaces/{company['id']}"
        for payload in (
            {},
            {"confirm": False, "company_name": "Archive Me Exactly"},
            {"confirm": True, "company_name": "archive me exactly"},
            {"confirm": True, "company_name": "Wrong Company"},
        ):
            with self.subTest(payload=payload):
                response = self.client.delete(url, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(
                    next(
                        item
                        for item in self.client.get("/api/workspaces").get_json()["workspaces"]
                        if item["id"] == company["id"]
                    )["is_archived"]
                )

        for demo_workspace, demo_name in (
            ("business", "Meridian Works"),
            ("personal", "Robert Household"),
        ):
            response = self.client.delete(
                f"/api/workspaces/{demo_workspace}",
                json={"confirm": True, "company_name": demo_name},
            )
            self.assertEqual(response.status_code, 400)

    def test_archive_hides_company_preserves_records_and_restore_recovers_it(self) -> None:
        company = self._create_company("Restorable Records")
        external_id = self._import_transaction(company["id"], "ARCHIVE-TXN-001")

        before = self.client.get(
            f"/api/records/transaction:{external_id}",
            query_string={"workspace": company["id"]},
        )
        self.assertEqual(before.status_code, 200, before.get_data(as_text=True))

        archived = self.client.delete(
            f"/api/workspaces/{company['id']}",
            json={"confirm": True, "company_name": company["name"]},
        )
        self.assertEqual(archived.status_code, 200, archived.get_data(as_text=True))
        archive_payload = archived.get_json()
        self.assertTrue(archive_payload["removed"])
        self.assertTrue(archive_payload["records_preserved"])
        self.assertTrue(archive_payload["connections_preserved"])
        self.assertTrue(archive_payload["is_archived"])
        self.assertNotIn("logo_filename", archive_payload)

        active_ids = {
            item["id"]
            for item in self.client.get("/api/workspaces").get_json()["workspaces"]
        }
        self.assertNotIn(company["id"], active_ids)
        archived_listing = self.client.get(
            "/api/workspaces", query_string={"include_archived": "true"}
        ).get_json()["workspaces"]
        archived_company = next(
            item for item in archived_listing if item["id"] == company["id"]
        )
        self.assertTrue(archived_company["is_archived"])
        self.assertIsNotNone(archived_company["archived_at"])
        self.assertNotIn("logo_filename", archived_company)

        denied_restore = self.client.post(
            f"/api/workspaces/{company['id']}/restore", json={"confirm": False}
        )
        self.assertEqual(denied_restore.status_code, 400)
        restored = self.client.post(
            f"/api/workspaces/{company['id']}/restore", json={"confirm": True}
        )
        self.assertEqual(restored.status_code, 200, restored.get_data(as_text=True))
        self.assertTrue(restored.get_json()["restored"])
        self.assertFalse(restored.get_json()["is_archived"])

        active_ids = {
            item["id"]
            for item in self.client.get("/api/workspaces").get_json()["workspaces"]
        }
        self.assertIn(company["id"], active_ids)
        after = self.client.get(
            f"/api/records/transaction:{external_id}",
            query_string={"workspace": company["id"]},
        )
        self.assertEqual(after.status_code, 200, after.get_data(as_text=True))
        self.assertEqual(after.get_json()["workspace_id"], company["id"])

    def test_additive_migration_preserves_old_workspace_and_chat_rows(self) -> None:
        old_db = core.DB_PATH
        old_db.unlink(missing_ok=True)
        with closing(sqlite3.connect(old_db)) as connection:
            connection.execute(
                "CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "kind TEXT NOT NULL, is_demo INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id TEXT NOT NULL, workspace_id TEXT NOT NULL, role TEXT NOT NULL, "
                "content TEXT NOT NULL, evidence_ids TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO workspaces VALUES ('legacy-company', 'Legacy Company', 'company', 0)"
            )
            connection.execute(
                "INSERT INTO workspaces VALUES ('business', 'Meridian Works', 'business', 1)"
            )
            connection.execute(
                "INSERT INTO workspaces VALUES ('personal', 'Robert Household', 'personal', 1)"
            )
            connection.execute(
                "INSERT INTO chat_history(session_id, workspace_id, role, content, "
                "evidence_ids, created_at) VALUES ('legacy-session', 'legacy-company', "
                "'user', 'hello', '[]', '2026-09-05T00:00:00+00:00')"
            )
            connection.commit()

        core.initialize_database()
        with closing(sqlite3.connect(old_db)) as connection:
            workspace_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(workspaces)")
            }
            chat_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(chat_history)")
            }
            preserved = connection.execute(
                "SELECT name, website, logo_filename, archived_at FROM workspaces "
                "WHERE id='legacy-company'"
            ).fetchone()
            chat = connection.execute(
                "SELECT content, focus_ids, calculation_json FROM chat_history "
                "WHERE session_id='legacy-session'"
            ).fetchone()

        self.assertTrue(
            {"website", "logo_filename", "archived_at"}.issubset(workspace_columns)
        )
        self.assertTrue({"focus_ids", "calculation_json"}.issubset(chat_columns))
        self.assertEqual(preserved, ("Legacy Company", None, None, None))
        self.assertEqual(chat, ("hello", "[]", None))


if __name__ == "__main__":
    unittest.main()
