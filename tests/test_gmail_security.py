from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as app_module
import src.core as core
from src import secure_credentials


class GmailSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="payproof-gmail-security-")
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.root / "runtime"
        self.patchers = [
            patch.object(core, "RUNTIME_DIR", self.runtime),
            patch.object(core, "DB_PATH", self.runtime / "payproof.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", self.runtime / "prism_queue.jsonl"),
            patch.object(core, "BANK_CONNECTIONS_PATH", self.runtime / "bank-connections.json"),
            patch.object(core, "DEMO_INTAKE_DIR", self.root / "demo-intake"),
            patch.object(core, "USER_INTAKE_DIR", self.root / "intake"),
            patch.object(app_module, "PROJECT_ROOT", self.root),
        ]
        for patcher in self.patchers:
            patcher.start()
        app_module.OAUTH_STATE.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        app_module.app.config.update(TESTING=True)
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        app_module.OAUTH_STATE.clear()
        app_module.GMAIL_DISCONNECT_PREVIEWS.clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required")
    def test_dpapi_envelope_contains_no_plaintext_and_is_purpose_bound(self) -> None:
        path = self.root / "gmail-business-token.dpapi.json"
        plaintext = json.dumps({"token": "access-secret", "refresh_token": "refresh-secret"})
        secure_credentials.write_protected_text(path, plaintext, "gmail-oauth:business")

        stored = path.read_text(encoding="utf-8")
        self.assertNotIn("access-secret", stored)
        self.assertNotIn("refresh-secret", stored)
        self.assertEqual(json.loads(stored)["protection"], "windows-dpapi-current-user")
        self.assertEqual(
            secure_credentials.read_protected_text(path, "gmail-oauth:business"), plaintext
        )
        with self.assertRaises(secure_credentials.SecureCredentialError):
            secure_credentials.read_protected_text(path, "gmail-oauth:personal")

    def test_connect_prefers_standard_credentials_and_binds_state_to_workspace(self) -> None:
        standard = self.root / "credentials.json"
        legacy = self.root / "credentials.json.json"
        self.assertEqual(app_module._gmail_paths("business")[0], standard)
        legacy.write_text("{}", encoding="utf-8")
        self.assertEqual(app_module._gmail_paths("business")[0], legacy)
        standard.write_text("{}", encoding="utf-8")
        self.assertEqual(app_module._gmail_paths("business")[0], standard)

        fake_flow = MagicMock()
        fake_flow.authorization_url.return_value = (
            "https://accounts.google.test/authorize?state=generated-state", "generated-state"
        )
        with patch.object(secure_credentials, "secure_storage_available", return_value=True), \
                patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file",
                      return_value=fake_flow):
            response = self.client.get(
                "/api/sources/gmail/connect?workspace=personal&session_id=connect-session"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        state = app_module.OAUTH_STATE["generated-state"]
        self.assertEqual(state["workspace"], "personal")
        self.assertEqual(
            state["session_fingerprint"], app_module._session_fingerprint("connect-session")
        )
        fake_flow.authorization_url.assert_called_once()

    def test_connect_fails_closed_when_dpapi_is_unavailable(self) -> None:
        credentials_path, token_path = app_module._gmail_paths("business")
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{}", encoding="utf-8")
        with patch.object(secure_credentials, "secure_storage_available", return_value=False), \
                patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file") as flow:
            response = self.client.get(
                "/api/sources/gmail/connect?workspace=business&session_id=closed-session"
            )

        self.assertEqual(response.status_code, 501)
        self.assertFalse(response.get_json()["plaintext_fallback_enabled"])
        self.assertFalse(token_path.exists())
        self.assertFalse(app_module.OAUTH_STATE)
        flow.assert_not_called()

    def test_connect_accepts_a_user_created_company_and_rejects_an_unknown_one(self) -> None:
        company = core.create_company_workspace("Lighthouse Books")
        credentials_path, token_path = app_module._gmail_paths(company["id"])
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{}", encoding="utf-8")
        fake_flow = MagicMock()
        fake_flow.authorization_url.return_value = (
            "https://accounts.google.test/authorize?state=company-state", "company-state"
        )

        with patch.object(secure_credentials, "secure_storage_available", return_value=True), \
                patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file",
                      return_value=fake_flow):
            response = self.client.get(
                f"/api/sources/gmail/connect?workspace={company['id']}&session_id=company-session"
            )
            unknown = self.client.get(
                "/api/sources/gmail/connect?workspace=company-missing-99999999&session_id=company-session"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["workspace"], company["id"])
        self.assertEqual(app_module.OAUTH_STATE["company-state"]["workspace"], company["id"])
        self.assertEqual(
            token_path.name, f"gmail-{company['id']}-token.dpapi.json"
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.get_json()["error"], "Unknown workspace")

    def test_oauth_callback_uses_workspace_bound_state_once_and_encrypts(self) -> None:
        credentials_path, business_token_path = app_module._gmail_paths("business")
        credentials_path.parent.mkdir(parents=True, exist_ok=True)
        credentials_path.write_text("{}", encoding="utf-8")
        fake_credentials = SimpleNamespace(
            refresh_token="refresh-secret",
            token="access-secret",
            to_json=lambda: json.dumps({"refresh_token": "refresh-secret", "token": "access-secret"}),
        )
        fake_flow = MagicMock(credentials=fake_credentials)
        app_module._remember_gmail_oauth_state(
            "business-state", "business", "http://localhost/oauth2callback", "session-business"
        )

        with patch.object(secure_credentials, "secure_storage_available", return_value=True), \
                patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file", return_value=fake_flow), \
                patch.object(secure_credentials, "write_protected_text") as protected_write:
            response = self.client.get(
                "/oauth2callback?state=business-state&workspace=personal&code=synthetic"
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        protected_write.assert_called_once_with(
            business_token_path,
            fake_credentials.to_json(),
            "gmail-oauth:business",
        )
        self.assertEqual(self.client.get("/oauth2callback?state=business-state&code=replay").status_code, 400)
        self.assertFalse(app_module._gmail_paths("personal")[1].exists())

    def test_import_decrypts_in_memory_and_never_uses_plaintext_token_file(self) -> None:
        _, token_path = app_module._gmail_paths("business")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text('{"ciphertext":"synthetic-envelope"}', encoding="utf-8")
        serialized = json.dumps({"token": "access-secret", "refresh_token": "refresh-secret"})
        fake_credentials = SimpleNamespace(
            token="refreshed-access-secret",
            refresh_token="refresh-secret",
            to_json=lambda: json.dumps({"token": "refreshed-access-secret", "refresh_token": "refresh-secret"}),
        )
        messages_api = MagicMock()
        messages_api.list.return_value.execute.return_value = {"messages": [{"id": "gmail-message-1"}]}
        messages_api.get.return_value.execute.return_value = {
            "payload": {"headers": [
                {"name": "From", "value": "orders@example.test"},
                {"name": "Subject", "value": "Receipt 100"},
                {"name": "Date", "value": "2026-09-05"},
            ]},
            "snippet": "Receipt total $10.00",
        }
        service = MagicMock()
        service.users.return_value.messages.return_value = messages_api

        with patch.object(secure_credentials, "secure_storage_available", return_value=True), \
                patch.object(secure_credentials, "read_protected_text", return_value=serialized) as protected_read, \
                patch.object(secure_credentials, "write_protected_text") as protected_write, \
                patch("google.oauth2.credentials.Credentials.from_authorized_user_info",
                      return_value=fake_credentials) as from_memory, \
                patch("google.oauth2.credentials.Credentials.from_authorized_user_file") as from_file, \
                patch("googleapiclient.discovery.build", return_value=service):
            response = self.client.post(
                "/api/sources/gmail/import",
                json={"workspace": "business", "max_results": 1},
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["accepted"], 1)
        protected_read.assert_called_once_with(token_path, "gmail-oauth:business")
        from_memory.assert_called_once()
        from_file.assert_not_called()
        protected_write.assert_called_once_with(
            token_path, fake_credentials.to_json(), "gmail-oauth:business"
        )
        self.assertNotIn("access-secret", token_path.read_text(encoding="utf-8"))

    def test_same_gmail_message_is_isolated_in_both_workspaces(self) -> None:
        message = {
            "id": "shared-message-id",
            "sender": "merchant@example.test",
            "subject": "Shared receipt",
            "received_at": "2026-09-05",
            "snippet": "Same message may support two explicitly selected workspaces.",
        }
        self.assertEqual(core.import_gmail_metadata([message], "business")["accepted"], 1)
        self.assertEqual(core.import_gmail_metadata([message], "personal")["accepted"], 1)
        self.assertEqual(core.import_gmail_metadata([message], "business")["skipped"], 1)

        business_ids = {
            row["id"] for row in core.get_dashboard("business")["emails"]
            if row["subject"] == "Shared receipt"
        }
        personal_ids = {
            row["id"] for row in core.get_dashboard("personal")["emails"]
            if row["subject"] == "Shared receipt"
        }
        self.assertEqual(len(business_ids), 1)
        self.assertEqual(len(personal_ids), 1)
        self.assertTrue(next(iter(business_ids)).startswith("GMAIL-BUSINESS-"))
        self.assertTrue(next(iter(personal_ids)).startswith("GMAIL-PERSONAL-"))
        self.assertTrue(business_ids.isdisjoint(personal_ids))

    def test_same_gmail_message_is_isolated_in_two_custom_companies(self) -> None:
        first_company = core.create_company_workspace("Lighthouse Books")["id"]
        second_company = core.create_company_workspace("Harbor Coffee")["id"]

        message = {
            "id": "same-provider-message-id",
            "sender": "billing@example.test",
            "subject": "Receipt shared with two companies",
            "received_at": "2026-09-05",
            "snippet": "Each company explicitly imported this provider record.",
        }
        self.assertEqual(core.import_gmail_metadata([message], first_company)["accepted"], 1)
        self.assertEqual(core.import_gmail_metadata([message], second_company)["accepted"], 1)
        self.assertEqual(core.import_gmail_metadata([message], first_company)["skipped"], 1)

        first_ids = {
            row["id"] for row in core.get_dashboard(first_company)["emails"]
            if row["subject"] == message["subject"]
        }
        second_ids = {
            row["id"] for row in core.get_dashboard(second_company)["emails"]
            if row["subject"] == message["subject"]
        }
        self.assertEqual(len(first_ids), 1)
        self.assertEqual(len(second_ids), 1)
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertNotEqual(
            app_module._gmail_paths(first_company)[1],
            app_module._gmail_paths(second_company)[1],
        )

    def _create_disconnect_preview(self, session_id: str = "session-owner") -> dict:
        response = self.client.post(
            "/api/sources/gmail/disconnect-preview",
            json={"workspace": "business", "session_id": session_id},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def test_disconnect_preview_is_workspace_session_bound_and_revokes_before_delete(self) -> None:
        _, token_path = app_module._gmail_paths("business")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("encrypted-token-envelope", encoding="utf-8")
        core.import_gmail_metadata([{
            "id": "preserved-evidence", "sender": "sender@example.test",
            "subject": "Preserve me", "snippet": "Imported evidence remains local.",
        }], "business")
        fake_credentials = SimpleNamespace(refresh_token="refresh-secret", token="access-secret")

        with patch.object(secure_credentials, "secure_storage_available", return_value=True):
            wrong_workspace_preview = self._create_disconnect_preview()
            mismatch = self.client.post("/api/sources/gmail/disconnect", json={
                "workspace": "personal", "session_id": "session-owner",
                "preview_id": wrong_workspace_preview["preview_id"], "confirm": True,
            })
            self.assertEqual(mismatch.status_code, 403)
            self.assertTrue(token_path.exists())

            wrong_session_preview = self._create_disconnect_preview()
            mismatch = self.client.post("/api/sources/gmail/disconnect", json={
                "workspace": "business", "session_id": "different-session",
                "preview_id": wrong_session_preview["preview_id"], "confirm": True,
            })
            self.assertEqual(mismatch.status_code, 403)
            self.assertTrue(token_path.exists())

            preview = self._create_disconnect_preview()

            def revoke_while_token_exists(_credentials):
                self.assertTrue(token_path.exists())
                return {"revoked": True, "provider_status": 200, "state": "revoked"}

            with patch.object(app_module, "_load_gmail_credentials", return_value=fake_credentials), \
                    patch.object(app_module, "_revoke_google_credentials",
                                 side_effect=revoke_while_token_exists) as revoke:
                response = self.client.post("/api/sources/gmail/disconnect", json={
                    "workspace": "business", "session_id": "session-owner",
                    "preview_id": preview["preview_id"], "confirm": True,
                })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()
        self.assertTrue(result["upstream_authorization_revoked"])
        self.assertTrue(result["local_token_deleted"])
        self.assertTrue(result["imported_evidence_preserved"])
        self.assertFalse(result["upstream_data_deleted"])
        self.assertNotIn("refresh-secret", response.get_data(as_text=True))
        self.assertFalse(token_path.exists())
        revoke.assert_called_once_with(fake_credentials)
        self.assertEqual(
            core.preview_source_removal("business", "gmail")["affected"]["email_evidence"], 1
        )

    def test_revocation_failure_retains_encrypted_token_and_preview_is_one_use(self) -> None:
        _, token_path = app_module._gmail_paths("business")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("encrypted-token-envelope", encoding="utf-8")
        fake_credentials = SimpleNamespace(refresh_token="refresh-secret", token="access-secret")

        with patch.object(secure_credentials, "secure_storage_available", return_value=True):
            preview = self._create_disconnect_preview()
            with patch.object(app_module, "_load_gmail_credentials", return_value=fake_credentials), \
                    patch.object(app_module, "_revoke_google_credentials", return_value={
                        "revoked": False, "provider_status": None, "state": "provider_unreachable",
                    }):
                response = self.client.post("/api/sources/gmail/disconnect", json={
                    "workspace": "business", "session_id": "session-owner",
                    "preview_id": preview["preview_id"], "confirm": True,
                })
                replay = self.client.post("/api/sources/gmail/disconnect", json={
                    "workspace": "business", "session_id": "session-owner",
                    "preview_id": preview["preview_id"], "confirm": True,
                })

        self.assertEqual(response.status_code, 502)
        result = response.get_json()
        self.assertFalse(result["disconnected"])
        self.assertFalse(result["upstream_authorization_revoked"])
        self.assertFalse(result["local_token_deleted"])
        self.assertTrue(result["imported_evidence_preserved"])
        self.assertTrue(token_path.exists())
        self.assertEqual(replay.status_code, 400)
        self.assertNotIn("refresh-secret", response.get_data(as_text=True))

    def test_revocation_success_with_local_cleanup_failure_is_truthful(self) -> None:
        _, token_path = app_module._gmail_paths("business")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("encrypted-token-envelope", encoding="utf-8")
        fake_credentials = SimpleNamespace(refresh_token="refresh-secret", token="access-secret")

        with patch.object(secure_credentials, "secure_storage_available", return_value=True):
            preview = self._create_disconnect_preview()
            with patch.object(app_module, "_load_gmail_credentials", return_value=fake_credentials), \
                    patch.object(app_module, "_revoke_google_credentials", return_value={
                        "revoked": True, "provider_status": 200, "state": "revoked",
                    }), patch.object(Path, "unlink", side_effect=OSError("synthetic cleanup failure")):
                response = self.client.post("/api/sources/gmail/disconnect", json={
                    "workspace": "business", "session_id": "session-owner",
                    "preview_id": preview["preview_id"], "confirm": True,
                })

        self.assertEqual(response.status_code, 500)
        result = response.get_json()
        self.assertEqual(result["state"], "upstream_revoked_local_cleanup_failed")
        self.assertTrue(result["upstream_authorization_revoked"])
        self.assertFalse(result["local_token_deleted"])
        self.assertTrue(token_path.exists())

    def test_google_revocation_posts_token_without_putting_it_in_url(self) -> None:
        credentials = SimpleNamespace(refresh_token="refresh secret/+", token="access-secret")
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = app_module._revoke_google_credentials(credentials)

        self.assertTrue(result["revoked"])
        revoke_request = urlopen.call_args.args[0]
        self.assertEqual(revoke_request.full_url, "https://oauth2.googleapis.com/revoke")
        self.assertNotIn("refresh", revoke_request.full_url)
        self.assertIn(b"token=refresh+secret%2F%2B", revoke_request.data)

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            failed = app_module._revoke_google_credentials(credentials)
        self.assertFalse(failed["revoked"])
        self.assertEqual(failed["state"], "provider_unreachable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
