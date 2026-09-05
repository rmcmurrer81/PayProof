from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import app as app_module
import src.core as core


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.read_limit = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, limit: int = -1) -> bytes:
        self.read_limit = limit
        return self.body


def tavily_response(results: list[dict] | None = None) -> FakeResponse:
    return FakeResponse(json.dumps({"results": results or []}).encode("utf-8"))


class TavilyConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="payproof-tavily-")
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
        app_module.app.config.update(TESTING=True)
        core.initialize_database(reset=True)
        self.client = app_module.app.test_client()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def test_missing_key_returns_503_without_network_or_evidence_write(self) -> None:
        with patch.dict(os.environ, {}, clear=False), \
                patch.object(app_module.urllib.request, "build_opener") as build_opener, \
                patch.object(app_module, "import_web_evidence") as import_evidence:
            os.environ.pop("TAVILY_API_KEY", None)
            response = self.client.post(
                "/api/sources/tavily/search",
                json={"workspace": "business", "query": "NewWave Consulting registration"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.get_json()["error"].lower())
        build_opener.assert_not_called()
        import_evidence.assert_not_called()

    def test_request_contract_is_bounded_and_only_result_fields_are_imported(self) -> None:
        secret = "tvly-unit-test-secret"
        response_body = json.dumps({
            "answer": "must not be imported",
            "request_id": "must-not-cross-boundary",
            "results": [{
                "title": "NewWave Consulting LLC",
                "url": "https://registry.example/newwave",
                "content": "A public registry summary.",
                "score": 0.91,
                "raw_content": "must not be imported",
                "favicon": "https://registry.example/favicon.ico",
            }],
        }).encode("utf-8")
        upstream = FakeResponse(response_body)
        opener = MagicMock()
        opener.open.return_value = upstream
        saved = {
            "accepted": 1,
            "skipped": 0,
            "batch_id": "batch-1",
            "source_id": "web:batch-1",
        }
        with patch.dict(os.environ, {"TAVILY_API_KEY": secret}, clear=False), \
                patch.object(app_module.urllib.request, "build_opener", return_value=opener) as build_opener, \
                patch.object(app_module, "utc_now", return_value="2026-09-05T18:00:00+00:00"), \
                patch.object(app_module, "import_web_evidence", return_value=saved) as import_evidence:
            response = self.client.post(
                "/api/sources/tavily/search",
                json={
                    "workspace": "business",
                    "query": "  NewWave Consulting company registration  ",
                    "max_results": 5,
                },
            )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        request_object = opener.open.call_args.args[0]
        self.assertEqual(request_object.full_url, "https://api.tavily.com/search")
        self.assertEqual(request_object.get_method(), "POST")
        self.assertEqual(request_object.get_header("Authorization"), f"Bearer {secret}")
        self.assertEqual(request_object.get_header("Content-type"), "application/json")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], app_module.TAVILY_TIMEOUT_SECONDS)
        build_opener.assert_called_once()
        self.assertIsInstance(build_opener.call_args.args[0], app_module._NoRedirectHandler)
        self.assertEqual(json.loads(request_object.data), {
            "query": "NewWave Consulting company registration",
            "max_results": 5,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        })
        self.assertEqual(upstream.read_limit, app_module.TAVILY_MAX_RESPONSE_BYTES + 1)
        import_evidence.assert_called_once_with(
            [{
                "title": "NewWave Consulting LLC",
                "url": "https://registry.example/newwave",
                "content": "A public registry summary.",
                "score": 0.91,
            }],
            "business",
            source_label="Tavily web search · unverified",
            query="NewWave Consulting company registration",
            retrieved_at="2026-09-05T18:00:00+00:00",
        )
        serialized = response.get_data(as_text=True)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("raw_content", serialized)
        self.assertEqual(response.get_json()["accepted"], 1)

    def test_bad_client_payloads_are_400_and_never_reach_tavily(self) -> None:
        requests = [
            ({"workspace": "business", "query": ""}, None),
            ({"workspace": "business", "query": "x" * 501}, None),
            ({"workspace": "business", "query": "vendor\nsecret"}, None),
            ({"workspace": "missing-workspace", "query": "vendor"}, None),
            ({"workspace": "business", "query": "vendor", "max_results": 0}, None),
            ({"workspace": "business", "query": "vendor", "max_results": 11}, None),
            ({"workspace": "business", "query": "vendor", "max_results": True}, None),
            ({"workspace": "business", "query": "vendor", "max_results": "5"}, None),
        ]
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=False), \
                patch.object(app_module.urllib.request, "build_opener") as build_opener, \
                patch.object(app_module, "import_web_evidence") as import_evidence:
            malformed = self.client.post(
                "/api/sources/tavily/search", data="{", content_type="application/json"
            )
            not_an_object = self.client.post(
                "/api/sources/tavily/search", json=["not", "an", "object"]
            )
            responses = [self.client.post("/api/sources/tavily/search", json=payload)
                         for payload, _ in requests]

        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(not_an_object.status_code, 400)
        self.assertTrue(all(response.status_code == 400 for response in responses))
        build_opener.assert_not_called()
        import_evidence.assert_not_called()

    def test_bad_upstream_json_shapes_status_and_size_are_safe_502s(self) -> None:
        secret = "tvly-do-not-echo-this"
        too_large = b"{" + (b"x" * app_module.TAVILY_MAX_RESPONSE_BYTES)
        upstream_responses = [
            FakeResponse(b"not-json"),
            FakeResponse(json.dumps({"answer": "no results field"}).encode("utf-8")),
            FakeResponse(json.dumps({"results": {"not": "a list"}}).encode("utf-8")),
            FakeResponse(json.dumps({"results": ["not an object"]}).encode("utf-8")),
            FakeResponse(b"{}", status=429),
            FakeResponse(too_large),
        ]
        with patch.dict(os.environ, {"TAVILY_API_KEY": secret}, clear=False):
            for upstream in upstream_responses:
                opener = MagicMock()
                opener.open.return_value = upstream
                with self.subTest(status=upstream.status, size=len(upstream.body)), \
                        patch.object(app_module.urllib.request, "build_opener", return_value=opener), \
                        patch.object(app_module, "import_web_evidence") as import_evidence:
                    response = self.client.post(
                        "/api/sources/tavily/search",
                        json={"workspace": "business", "query": "vendor", "max_results": 3},
                    )
                    self.assertEqual(response.status_code, 502, response.get_data(as_text=True))
                    self.assertNotIn(secret, response.get_data(as_text=True))
                    import_evidence.assert_not_called()

    def test_transport_errors_never_echo_or_log_the_server_key(self) -> None:
        secret = "tvly-sensitive-server-key"
        failure = urllib.error.URLError(f"synthetic failure carrying {secret}")
        opener = MagicMock()
        opener.open.side_effect = failure
        with patch.dict(os.environ, {"TAVILY_API_KEY": secret}, clear=False), \
                patch.object(app_module.urllib.request, "build_opener", return_value=opener), \
                patch.object(app_module, "import_web_evidence") as import_evidence, \
                patch.object(app_module.app.logger, "error") as error_log, \
                patch.object(app_module.app.logger, "exception") as exception_log:
            response = self.client.post(
                "/api/sources/tavily/search",
                json={"workspace": "business", "query": "vendor registration"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn(secret, response.get_data(as_text=True))
        error_log.assert_not_called()
        exception_log.assert_not_called()
        import_evidence.assert_not_called()

    def test_search_uses_the_selected_workspace_and_rejects_unknown_workspaces(self) -> None:
        company_a = core.create_company_workspace("Northwind Test")
        company_b = core.create_company_workspace("Tailspin Test")
        result = [{
            "title": "Registry page",
            "url": "https://registry.example/vendor",
            "content": "Public registry listing",
            "score": 0.8,
        }]
        opener = MagicMock()
        opener.open.side_effect = [tavily_response(result), tavily_response(result)]
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-workspace-test"}, clear=False), \
                patch.object(app_module.urllib.request, "build_opener", return_value=opener), \
                patch.object(app_module, "import_web_evidence", return_value={
                    "accepted": 1, "skipped": 0, "batch_id": "batch", "source_id": "web:batch",
                }) as import_evidence:
            first = self.client.post("/api/sources/tavily/search", json={
                "workspace": company_a["id"], "query": "vendor",
            })
            second = self.client.post("/api/sources/tavily/search", json={
                "workspace": company_b["id"], "query": "vendor",
            })
            unknown = self.client.post("/api/sources/tavily/search", json={
                "workspace": "company-missing-99999999", "query": "vendor",
            })

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(
            [called.args[1] for called in import_evidence.call_args_list],
            [company_a["id"], company_b["id"]],
        )
        self.assertEqual(opener.open.call_count, 2)

    def test_redirect_handler_refuses_to_create_a_cross_origin_request(self) -> None:
        original = app_module.urllib.request.Request(
            "https://api.tavily.com/search",
            headers={"Authorization": "Bearer tvly-never-forward"},
        )
        redirected = app_module._NoRedirectHandler().redirect_request(
            original,
            None,
            302,
            "Found",
            {"Location": "https://attacker.example/collect"},
            "https://attacker.example/collect",
        )

        self.assertIsNone(redirected)

    def test_manual_snapshots_are_bounded_and_labeled_user_supplied(self) -> None:
        company = core.create_company_workspace("Manual Research Test")
        items = [{
            "title": "State registry",
            "url": "https://registry.example/newwave",
            "content": "User copied this public result.",
            "score": 0.7,
        }]
        with patch.object(app_module, "utc_now", return_value="2026-09-05T19:00:00+00:00"), \
                patch.object(app_module, "import_web_evidence", return_value={
                    "accepted": 1, "skipped": 0, "batch_id": "manual", "source_id": "web:manual",
                }) as import_evidence:
            response = self.client.post("/api/sources/web/import", json={
                "workspace": company["id"],
                "query": "NewWave Consulting",
                "items": items,
                "source_label": "Pretend this is verified",
                "retrieved_at": "1900-01-01T00:00:00Z",
            })
            oversized = self.client.post("/api/sources/web/import", json={
                "workspace": company["id"],
                "items": items * 11,
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(oversized.status_code, 400)
        import_evidence.assert_called_once_with(
            items,
            company["id"],
            source_label="User-supplied web snapshot · unverified",
            query="NewWave Consulting",
            retrieved_at="2026-09-05T19:00:00+00:00",
        )

    def test_source_status_reports_configuration_without_exposing_the_key(self) -> None:
        secret = "tvly-status-secret"
        with patch.dict(os.environ, {"TAVILY_API_KEY": secret}, clear=False):
            configured = self.client.get("/api/sources?workspace=business")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TAVILY_API_KEY", None)
            unconfigured = self.client.get("/api/sources?workspace=business")

        self.assertEqual(configured.status_code, 200)
        self.assertTrue(configured.get_json()["tavily"]["configured"])
        self.assertFalse(configured.get_json()["tavily"]["api_key_exposed_to_browser"])
        self.assertNotIn(secret, configured.get_data(as_text=True))
        self.assertFalse(unconfigured.get_json()["tavily"]["configured"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
