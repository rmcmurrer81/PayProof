from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import src.core as core
from src.company_transfer import build_company_transfer_zip


FIXED_TIME = "2026-09-05T18:30:00+00:00"


class WebEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="payproof-web-evidence-"
        )
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.root / "runtime"
        self.patchers = [
            patch.object(core, "RUNTIME_DIR", self.runtime),
            patch.object(core, "DB_PATH", self.runtime / "payproof.sqlite3"),
            patch.object(core, "TRACE_QUEUE_PATH", self.runtime / "prism_queue.jsonl"),
            patch.object(
                core, "BANK_CONNECTIONS_PATH", self.runtime / "bank-connections.json"
            ),
            patch.object(core, "DEMO_INTAKE_DIR", self.root / "demo-intake"),
            patch.object(core, "USER_INTAKE_DIR", self.root / "intake"),
        ]
        for patcher in self.patchers:
            patcher.start()
        # The database path is new and temporary, so no real database reset is used.
        core.initialize_database()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    @staticmethod
    def item(**changes: object) -> dict[str, object]:
        result: dict[str, object] = {
            "title": "NewWave Consulting registration",
            "url": "https://registry.example/newwave",
            "content": "A public registry result for NewWave Consulting.",
            "score": 0.93,
        }
        result.update(changes)
        return result

    def count(self, table: str, workspace_id: str = "business") -> int:
        self.assertIn(table, {"web_evidence", "email_evidence", "reconciliations"})
        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            return int(connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE workspace_id=?',
                (workspace_id,),
            ).fetchone()[0])

    def test_requires_a_real_workspace_and_a_small_strict_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown workspace"):
            core.import_web_evidence([self.item()], "company-missing-12345678")
        for invalid in (None, {}, "results"):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaisesRegex(
                ValueError, "must be a list"
            ):
                core.import_web_evidence(invalid, "business")  # type: ignore[arg-type]
        for invalid in ([], [self.item()] * 11):
            with self.subTest(count=len(invalid)), self.assertRaisesRegex(
                ValueError, "between 1 and 10"
            ):
                core.import_web_evidence(invalid, "business")
        with self.assertRaisesRegex(ValueError, "item 1 must be an object"):
            core.import_web_evidence(["not-an-object"], "business")  # type: ignore[list-item]
        self.assertEqual(self.count("web_evidence"), 0)

    def test_rejects_missing_wrong_type_blank_and_oversized_fields_atomically(self) -> None:
        invalid_items = [
            self.item(title=None),
            self.item(title="   "),
            self.item(title="t" * (core.MAX_WEB_EVIDENCE_TITLE_CHARS + 1)),
            self.item(content=7),
            self.item(content="\0hostile"),
            self.item(content="c" * (core.MAX_WEB_EVIDENCE_CONTENT_CHARS + 1)),
            self.item(url=None),
            self.item(url="https://example.com/" + "x" * core.MAX_WEB_EVIDENCE_URL_CHARS),
            self.item(score="0.9"),
            self.item(score=float("nan")),
            self.item(score=1.01),
        ]
        for item in invalid_items:
            with self.subTest(item=item), self.assertRaises(ValueError):
                core.import_web_evidence([self.item(), item], "business")
            self.assertEqual(self.count("web_evidence"), 0)

        with self.assertRaises(ValueError):
            core.import_web_evidence(
                [self.item()], "business", source_label=" "
            )
        with self.assertRaises(ValueError):
            core.import_web_evidence(
                [self.item()], "business",
                query="q" * (core.MAX_WEB_EVIDENCE_QUERY_CHARS + 1),
            )
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            core.import_web_evidence(
                [self.item()], "business", retrieved_at="not-a-timestamp"
            )

    def test_canonicalizes_public_urls_and_rejects_unsafe_destinations(self) -> None:
        unsafe_urls = [
            "ftp://example.com/file",
            "/relative/path",
            "https://user:password@example.com/page",
            "https://example.com:8080/page",
            "https://localhost/page",
            "https://service.local/page",
            "http://intranet/page",
            "https://service.internal/page",
            "http://127.0.0.1/page",
            "http://127.1/page",
            "http://10.2.3.4/page",
            "http://169.254.10.20/page",
            "http://192.0.2.20/page",
            "http://[::1]/page",
            "http://[fe80::1]/page",
            "https://example.com/page?access_token=tvly-secret",
            "https://example.com/page?api%5Fkey=tvly-secret",
            "https://example.com/page?client-secret=tvly-secret",
            "https://example.com/page?X-Amz-Signature=tvly-secret",
            "https://example.com/page?X-Amz-Credential=tvly-secret",
            "https://example.com/page?sig=tvly-secret",
            "https://example.com/page?auth=tvly-secret",
            "https://example.com/page?code=tvly-secret",
        ]
        for url in unsafe_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                core.import_web_evidence([self.item(url=url)], "business")

        imported = core.import_web_evidence(
            [self.item(url="HTTPS://Example.COM:443/a%2fb?q=registration#result")],
            "business",
            retrieved_at=FIXED_TIME,
        )
        record = core.get_record(f"web:{imported['record_ids'][0]}", "business")
        self.assertIsNotNone(record)
        self.assertEqual(
            record["url"], "https://example.com/a%2Fb?q=registration"
        )

    def test_server_owns_batch_source_timestamp_and_untrusted_marker(self) -> None:
        imported = core.import_web_evidence(
            [self.item(
                batch_id="attacker-batch",
                source_id="gmail",
                retrieved_at="1999-01-01T00:00:00Z",
                is_untrusted=False,
            )],
            "business",
            source_label="Tavily web search · unverified",
            query="NewWave Consulting company registration",
            retrieved_at=FIXED_TIME,
        )
        self.assertEqual(imported["accepted"], 1)
        self.assertEqual(imported["skipped"], 0)
        self.assertRegex(imported["batch_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(imported["source_id"], f"web:{imported['batch_id']}")

        record = core.get_record(f"web:{imported['record_ids'][0]}", "business")
        self.assertEqual(record["batch_id"], imported["batch_id"])
        self.assertEqual(record["source_id"], imported["source_id"])
        self.assertEqual(record["retrieved_at"], FIXED_TIME)
        self.assertEqual(record["query"], "NewWave Consulting company registration")
        self.assertEqual(record["score"], 0.93)
        self.assertEqual(record["is_untrusted"], 1)
        self.assertNotIn("attacker", json.dumps(record))

    def test_same_url_is_company_scoped_while_duplicates_skip_and_changes_revise(self) -> None:
        first_company = core.create_company_workspace("Lighthouse Books")["id"]
        second_company = core.create_company_workspace("Harbor Coffee")["id"]

        first = core.import_web_evidence([self.item()], first_company)
        second = core.import_web_evidence([self.item()], second_company)
        duplicate = core.import_web_evidence([
            self.item(
                title="A changed search-result title does not change page content",
                url="HTTPS://REGISTRY.EXAMPLE:443/newwave#top",
            )
        ], first_company)
        revision = core.import_web_evidence([
            self.item(content="The public registry result was updated.")
        ], first_company)

        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["accepted"], 1)
        self.assertNotEqual(first["record_ids"][0], second["record_ids"][0])
        self.assertIn(first_company.upper(), first["record_ids"][0])
        self.assertIn(second_company.upper(), second["record_ids"][0])
        self.assertEqual(duplicate["accepted"], 0)
        self.assertEqual(duplicate["skipped"], 1)
        self.assertIsNone(duplicate["batch_id"])
        self.assertIsNone(duplicate["source_id"])
        self.assertEqual(revision["accepted"], 1)
        self.assertNotEqual(first["record_ids"][0], revision["record_ids"][0])
        self.assertEqual(self.count("web_evidence", first_company), 2)

        self.assertIsNone(
            core.get_record(f"web:{first['record_ids'][0]}", second_company)
        )
        with self.assertRaisesRegex(ValueError, "not found"):
            core.preview_source_removal(second_company, first["source_id"])

    def test_sources_preview_and_confirmed_removal_target_only_one_web_batch(self) -> None:
        gmail = core.import_gmail_metadata([{
            "id": "gmail-preserved",
            "sender": "merchant@example.test",
            "subject": "Preserved Gmail evidence",
            "snippet": "This is independent of web research.",
        }], "business")
        self.assertEqual(gmail["accepted"], 1)
        first = core.import_web_evidence([
            self.item(),
            self.item(
                title="NewWave profile",
                url="https://directory.example/newwave",
                content="A separate public directory result.",
                score=0.8,
            ),
        ], "business", query="NewWave Consulting")
        second = core.import_web_evidence([
            self.item(content="A later public registry revision.")
        ], "business", query="NewWave Consulting updated")

        web_sources = [
            source for source in core.list_import_sources("business")
            if source["kind"] == "web"
        ]
        self.assertEqual({source["id"] for source in web_sources}, {
            first["source_id"], second["source_id"],
        })
        self.assertEqual(
            next(source for source in web_sources if source["id"] == first["source_id"])["record_count"],
            2,
        )
        preview = core.preview_source_removal("business", first["source_id"])
        self.assertEqual(preview["affected"], {"web_evidence": 2})
        self.assertFalse(preview["upstream_data_deleted"])
        with self.assertRaisesRegex(ValueError, "confirm"):
            core.remove_source("business", first["source_id"])
        with self.assertRaises(ValueError):
            core.preview_source_removal("business", "web")

        removed = core.remove_source("business", first["source_id"], confirmed=True)
        self.assertEqual(removed["removed"], 2)
        self.assertEqual(self.count("web_evidence"), 1)
        self.assertEqual(self.count("email_evidence"), 6)
        remaining = core.get_dashboard("business")["web_evidence"]
        self.assertEqual({record["source_id"] for record in remaining}, {second["source_id"]})

    def test_gmail_and_reconciliation_paths_never_consume_web_rows(self) -> None:
        core.import_gmail_metadata([{
            "id": "isolated-gmail-row",
            "sender": "billing@example.test",
            "subject": "Gmail-only evidence",
            "snippet": "This row remains on the Gmail path.",
        }], "business")
        gmail_before = self.count("email_evidence")
        reconciliation_before = self.count("reconciliations")
        imported = core.import_web_evidence([
            self.item(
                title="Amazon order $43.57",
                content="Amazon Marketplace total $43.57 on 2026-09-01.",
            )
        ], "business")

        dashboard = core.get_dashboard("business")
        self.assertEqual(self.count("email_evidence"), gmail_before)
        self.assertEqual(self.count("reconciliations"), reconciliation_before)
        self.assertFalse(any(
            email["id"] == imported["record_ids"][0] for email in dashboard["emails"]
        ))
        self.assertTrue(any(
            row["id"] == imported["record_ids"][0]
            for row in dashboard["web_evidence"]
        ))
        self.assertFalse(any(
            match["type"] == "web"
            for row in dashboard["reconciliation"]["rows"]
            for match in row["matches"]
        ))

        core.remove_source("business", "gmail", confirmed=True)
        self.assertEqual(self.count("email_evidence"), gmail_before - 1)
        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            gmail_provider_rows = connection.execute(
                """SELECT COUNT(*) FROM email_evidence
                   WHERE workspace_id='business' AND provider='gmail'"""
            ).fetchone()[0]
        self.assertEqual(gmail_provider_rows, 0)
        self.assertEqual(self.count("web_evidence"), 1)

    def test_company_transfer_includes_sanitized_web_evidence_without_secrets(self) -> None:
        company = core.create_company_workspace("NewWave Buyer")
        imported = core.import_web_evidence([
            self.item(content=(
                "Registry evidence. Authorization: Bearer tavily-secret-token\n"
                "client_secret=another-secret-value"
            ))
        ], company["id"], query="registration api_key=query-secret", retrieved_at=FIXED_TIME)

        with closing(sqlite3.connect(core.DB_PATH)) as connection:
            package = build_company_transfer_zip(
                connection, company["id"], generated_at=FIXED_TIME,
            )
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}

        self.assertIn("json/web_evidence.json", files)
        self.assertIn("csv/web_evidence.csv", files)
        envelope = json.loads(files["json/web_evidence.json"])
        self.assertEqual(envelope["record_count"], 1)
        self.assertEqual(envelope["records"][0]["id"], imported["record_ids"][0])
        self.assertTrue(envelope["records"][0]["is_untrusted"])
        combined = b"\n".join(files.values()).decode("utf-8", errors="replace")
        self.assertNotIn("tavily-secret-token", combined)
        self.assertNotIn("another-secret-value", combined)
        self.assertNotIn("query-secret", combined)
        self.assertIn("[REDACTED_CREDENTIAL]", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
