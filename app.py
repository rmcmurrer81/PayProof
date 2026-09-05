from __future__ import annotations

import os
import time
import json
import hashlib
import hmac
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from src import secure_credentials

from src.core import (
    PROJECT_ROOT,
    add_intake_folder,
    archive_company_workspace,
    answer_question,
    bank_connector_status,
    commit_bank_statement_preview,
    correct_intake_expense,
    create_plaid_link_token,
    create_company_workspace,
    create_company_transfer_package,
    disconnect_plaid_connection,
    explain_with_runtime_model,
    exchange_plaid_public_token,
    get_dashboard,
    get_company_logo_path,
    get_record,
    get_reconciliation_summary,
    import_web_evidence,
    import_transactions_csv,
    import_gmail_metadata,
    import_ocr_receipt,
    generate_security_questionnaire,
    initialize_database,
    list_intake_folders,
    list_import_sources,
    list_workspaces,
    list_chat_history,
    list_intake_expense_history,
    prism_status,
    preview_plaid_disconnect,
    preview_source_removal,
    require_workspace,
    record_action,
    record_chat_turn,
    remove_source,
    remove_intake_folder,
    remove_company_logo,
    rename_company_workspace,
    reset_synthetic_demo_state,
    restore_company_workspace,
    scan_intake_folder,
    save_company_logo,
    send_prism_trace,
    set_employee_budget,
    sync_plaid_transactions,
    update_intake_folder,
    update_company_workspace,
    utc_now,
    preview_bank_statement,
)


def load_local_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
app = Flask(__name__, static_folder="static", static_url_path="/static")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OAUTH_STATE: dict[str, dict] = {}
OCR_PREVIEWS: dict[str, dict] = {}
BANK_PREVIEWS: dict[str, dict] = {}
SOURCE_REMOVAL_PREVIEWS: dict[str, dict] = {}
BANK_DISCONNECT_PREVIEWS: dict[str, dict] = {}
BANK_DISCONNECT_PREVIEW_LOCK = threading.RLock()
BANK_DISCONNECT_PREVIEW_TTL_SECONDS = 10 * 60
GMAIL_DISCONNECT_PREVIEWS: dict[str, dict] = {}
GMAIL_CREDENTIAL_LOCK = threading.RLock()
GMAIL_STATE_TTL_SECONDS = 10 * 60
GMAIL_PREVIEW_TTL_SECONDS = 10 * 60
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT_SECONDS = 8
TAVILY_MAX_RESPONSE_BYTES = 512 * 1024
WEB_IMPORT_MAX_REQUEST_BYTES = 128 * 1024
WEB_SEARCH_MAX_REQUEST_BYTES = 16 * 1024
WEB_IMPORT_MAX_ITEMS = 10
WEB_QUERY_MAX_CHARS = 500


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep the server credential on the one fixed Tavily origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/dashboard")
def dashboard():
    try:
        workspace = _require_workspace(request.args.get("workspace"), "business")
        return jsonify(get_dashboard(workspace))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/workspaces")
def workspaces_list():
    include_archived = request.args.get("include_archived", "false").lower() == "true"
    return jsonify({"workspaces": list_workspaces(include_archived=include_archived)})


@app.post("/api/workspaces")
def workspace_create():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        return jsonify(create_company_workspace(
            str(payload.get("name") or ""), payload.get("website"),
        )), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/workspaces/<workspace_id>")
def workspace_update(workspace_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        return jsonify(update_company_workspace(workspace_id, payload))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/workspaces/<workspace_id>")
def workspace_archive(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(archive_company_workspace(
            workspace_id,
            confirmed=payload.get("confirm") is True,
            expected_name=str(payload.get("company_name") or ""),
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/workspaces/<workspace_id>/restore")
def workspace_restore(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(restore_company_workspace(
            workspace_id, confirmed=payload.get("confirm") is True,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/workspaces/<workspace_id>/transfer-package")
def workspace_transfer_package(workspace_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        archive, filename = create_company_transfer_package(
            workspace_id,
            confirmed=payload.get("confirm") is True,
            expected_name=str(payload.get("company_name") or ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    response = Response(archive, mimetype="application/zip")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-PayProof-Credentials-Included"] = "false"
    return response


@app.get("/api/workspaces/<workspace_id>/logo")
def workspace_logo_get(workspace_id: str):
    try:
        logo_path, mime_type = get_company_logo_path(workspace_id)
        response = send_file(logo_path, mimetype=mime_type, conditional=False)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/api/workspaces/<workspace_id>/logo")
def workspace_logo_upload(workspace_id: str):
    uploaded = request.files.get("logo")
    if not uploaded:
        return jsonify({"error": "Choose a PNG, JPEG, or WebP logo"}), 400
    # Read one byte beyond the limit so oversized payloads fail without being
    # written to disk. The core validates the content signature again.
    content = uploaded.read((2 * 1024 * 1024) + 1)
    try:
        return jsonify(save_company_logo(
            workspace_id, uploaded.filename or "logo", content,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/workspaces/<workspace_id>/logo")
def workspace_logo_delete(workspace_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(remove_company_logo(
            workspace_id, confirmed=payload.get("confirm") is True,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/records/<path:entity_id>")
def record(entity_id: str):
    try:
        workspace = _require_workspace(request.args.get("workspace"), "business")
        item = get_record(entity_id, workspace)
        return (jsonify(item), 200) if item else (jsonify({"error": "Record not found"}), 404)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Ask a question"}), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        session_id = _require_session_id(payload.get("session_id") or "payproof-session")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    selected_id = payload.get("selected_id")
    started = time.perf_counter()
    result = answer_question(
        question, workspace, selected_id, payload.get("filters"), session_id=session_id,
    )
    result, model_status = explain_with_runtime_model(question, result)
    latency = round((time.perf_counter() - started) * 1000)
    trace = send_prism_trace(question, result, session_id, latency, workspace)
    record_chat_turn(session_id, workspace, question, result)
    return jsonify({"answer": result.answer, "evidence_ids": result.evidence_ids, "focus_ids": result.focus_ids, "model": model_status,
                    "calculation": result.calculation, "context": {"workspace": workspace, "selected_id": selected_id,
                    "evidence_ids": result.evidence_ids, "calculation": result.calculation}, "trace": trace})


@app.get("/api/chat/history")
def chat_history():
    try:
        return jsonify(list_chat_history(
            _require_session_id(request.args.get("session_id") or "payproof-session"),
            _require_workspace(request.args.get("workspace"), "business"),
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/security/questionnaire")
def security_questionnaire():
    return jsonify(generate_security_questionnaire())


@app.post("/api/actions")
def actions():
    payload = request.get_json(silent=True) or {}
    try:
        result = record_action(payload.get("workspace", "business"), str(payload.get("finding_id", "")),
                               str(payload.get("action", "")), str(payload.get("reason", "")))
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/reset")
def reset():
    return jsonify(reset_synthetic_demo_state())


@app.post("/api/import/transactions")
def import_transactions():
    if "file" not in request.files:
        return jsonify({"error": "Choose a CSV file"}), 400
    uploaded = request.files["file"]
    try:
        content = uploaded.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"error": "The CSV must use UTF-8 text encoding"}), 400
    commit = request.form.get("commit", "false").lower() == "true"
    result = import_transactions_csv(request.form.get("workspace", "business"), uploaded.filename or "upload.csv", content, commit)
    return jsonify(result), (200 if not result["errors"] else 400)


@app.get("/api/templates/transactions.csv")
def csv_template():
    template_dir = Path(app.static_folder) / "templates"
    return send_from_directory(template_dir, "transactions-template.csv", as_attachment=True)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "prism": prism_status()})


def _require_workspace(value, default: str = "business") -> str:
    workspace = default if value is None or value == "" else value
    if not isinstance(workspace, str):
        raise ValueError("Unknown workspace")
    return require_workspace(workspace)


def _require_session_id(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError("A valid session_id is required")
    return value.strip()


def _require_web_query(value, *, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError("query must be text")
    query = value.strip()
    if (required and not query) or len(query) > WEB_QUERY_MAX_CHARS:
        qualifier = "between 1 and" if required else "no more than"
        raise ValueError(f"query must be {qualifier} {WEB_QUERY_MAX_CHARS} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in query):
        raise ValueError("query contains unsupported control characters")
    return query


def _tavily_api_key() -> str | None:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key or len(key) > 4096 or "\r" in key or "\n" in key:
        return None
    return key


def _tavily_status() -> dict:
    configured = _tavily_api_key() is not None
    return {
        "id": "tavily",
        "provider": "Tavily",
        "configured": configured,
        "state": "ready" if configured else "not_configured",
        "mode": "public web search imported as unverified evidence",
        "api_key_exposed_to_browser": False,
        "search_endpoint": "/api/sources/tavily/search",
    }


def _gmail_paths(workspace_id: str = "business"):
    workspace_id = _require_workspace(workspace_id)
    standard_credentials = PROJECT_ROOT / "credentials.json"
    legacy_credentials = PROJECT_ROOT / "credentials.json.json"
    credentials_path = (
        standard_credentials
        if standard_credentials.exists() or not legacy_credentials.exists()
        else legacy_credentials
    )
    return (
        credentials_path,
        PROJECT_ROOT / "data" / "runtime" / f"gmail-{workspace_id}-token.dpapi.json",
    )


def _gmail_token_purpose(workspace_id: str) -> str:
    return f"gmail-oauth:{_require_workspace(workspace_id)}"


def _session_fingerprint(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _prune_timed_store(store: dict[str, dict], ttl_seconds: int, maximum: int = 128) -> None:
    now = time.time()
    for key in [key for key, value in store.items() if now - float(value.get("created", 0)) > ttl_seconds]:
        store.pop(key, None)
    while len(store) >= maximum:
        oldest = min(store, key=lambda key: float(store[key].get("created", 0)))
        store.pop(oldest, None)


def _remember_gmail_oauth_state(state: str, workspace_id: str, redirect_uri: str,
                                 session_id: str) -> None:
    if not isinstance(state, str) or not state or len(state) > 1000:
        raise ValueError("Google did not return a valid OAuth state")
    _prune_timed_store(OAUTH_STATE, GMAIL_STATE_TTL_SECONDS)
    OAUTH_STATE[state] = {
        "workspace": _require_workspace(workspace_id),
        "redirect_uri": redirect_uri,
        "session_fingerprint": _session_fingerprint(_require_session_id(session_id)),
        "created": time.time(),
    }


def _consume_gmail_oauth_state(state: str) -> dict | None:
    entry = OAUTH_STATE.pop(state, None)
    if not isinstance(entry, dict):
        return None
    if time.time() - float(entry.get("created", 0)) > GMAIL_STATE_TTL_SECONDS:
        return None
    try:
        entry["workspace"] = _require_workspace(entry.get("workspace"))
    except ValueError:
        return None
    if not isinstance(entry.get("redirect_uri"), str) or not entry["redirect_uri"]:
        return None
    return entry


def _gmail_ciphertext_digest(token_path: Path) -> str | None:
    if not token_path.exists():
        return None
    try:
        return hashlib.sha256(token_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise secure_credentials.SecureCredentialError(
            "The protected Gmail credential could not be inspected"
        ) from exc


def _gmail_status(workspace_id: str) -> dict:
    credentials_path, token_path = _gmail_paths(workspace_id)
    storage_available = secure_credentials.secure_storage_available()
    token_present = token_path.exists()
    connected = bool(storage_available and token_present)
    if connected:
        state = "connected"
    elif token_present:
        state = "secure_storage_unavailable"
    else:
        state = "not_connected"
    legacy_token_present = (PROJECT_ROOT / "data" / "runtime" / "gmail-token.json").exists()
    return {
        "id": "gmail",
        "provider": "Gmail",
        "workspace": workspace_id,
        "credentials_available": credentials_path.exists(),
        "connected": connected,
        "state": state,
        "mode": "read-only metadata and snippets",
        "token_stored_locally": token_present,
        "secure_token_storage": "windows_dpapi" if storage_available else "unavailable",
        "plaintext_fallback_enabled": False,
        "legacy_plaintext_token_detected": legacy_token_present,
        "upstream_data_changed_on_remove": False,
        "capabilities": [
            "connect",
            "reconnect",
            "disconnect_preview",
            "disconnect_with_revocation",
            "import_metadata",
            "remove_local_evidence",
        ],
    }


@app.get("/api/sources")
def sources():
    try:
        workspace = require_workspace(str(request.args.get("workspace") or "business"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    bank = bank_connector_status(workspace)
    gmail = _gmail_status(workspace)
    tavily = _tavily_status()
    intake_folders = list_intake_folders(workspace)
    return jsonify({
        "gmail": gmail,
        "tavily": tavily,
        "imports": list_import_sources(workspace), "csv": {"available": True},
        "bank": bank,
        "connections": [gmail, {"id": "bank", **bank,
                                  "capabilities": ["add_local_statement", "remove_local_statement", "view_reconciliation",
                                                   "create_link_token", "exchange_public_token", "sync", "disconnect"]}],
        "capabilities": {"source_removal_requires_preview": True, "source_removal_requires_confirmation": True,
                         "add_bank": "/api/import/bank/preview", "add_email": "/api/sources/gmail/connect",
                         "search_web": tavily["search_endpoint"],
                         "import_web_snapshot": "/api/sources/web/import"},
        "intake_folder": {"available": True, "mode": "local JSON paperwork",
                          "path": str(PROJECT_ROOT / "intake"), "folders": intake_folders,
                          "editable": True, "edit_mode": "audited_correction", "originals_preserved": True,
                          "editable_fields": ["merchant", "amount", "currency", "date", "category", "purpose", "receipt_status", "approval_status"]},
    })


@app.post("/api/sources/web/import")
def web_snapshot_import():
    if request.content_length is not None and request.content_length > WEB_IMPORT_MAX_REQUEST_BYTES:
        return jsonify({"error": "Web snapshot request is too large"}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        query = _require_web_query(payload.get("query"), required=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    items = payload.get("items")
    if (not isinstance(items, list) or not 1 <= len(items) <= WEB_IMPORT_MAX_ITEMS
            or not all(isinstance(item, dict) for item in items)):
        return jsonify({"error": f"items must contain 1 to {WEB_IMPORT_MAX_ITEMS} web result objects"}), 400
    try:
        result = import_web_evidence(
            items,
            workspace,
            source_label="User-supplied web snapshot · unverified",
            query=query,
            retrieved_at=utc_now(),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        return jsonify({"error": "Web snapshots could not be saved"}), 500
    return jsonify(result)


@app.put("/api/employees/<path:employee_id>/budget")
def employee_budget_update(employee_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        return jsonify(set_employee_budget(
            _require_workspace(payload.get("workspace"), "business"),
            employee_id,
            payload.get("amount"),
            payload.get("currency", "USD"),
            payload.get("period"),
        ))
    except (ValueError, ArithmeticError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/sources/tavily/search")
def tavily_search():
    if request.content_length is not None and request.content_length > WEB_SEARCH_MAX_REQUEST_BYTES:
        return jsonify({"error": "Search request is too large"}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        query = _require_web_query(payload.get("query"), required=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    max_results = payload.get("max_results", 5)
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 10:
        return jsonify({"error": "max_results must be a whole number from 1 to 10"}), 400
    api_key = _tavily_api_key()
    if api_key is None:
        return jsonify({"error": "Tavily search is not configured on this server"}), 503

    upstream_payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        upstream_request = urllib.request.Request(
            TAVILY_SEARCH_URL,
            data=json.dumps(upstream_payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(upstream_request, timeout=TAVILY_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                return jsonify({"error": "Tavily search is temporarily unavailable"}), 502
            response_bytes = response.read(TAVILY_MAX_RESPONSE_BYTES + 1)
    except Exception:
        return jsonify({"error": "Tavily search is temporarily unavailable"}), 502

    if not isinstance(response_bytes, (bytes, bytearray)) or len(response_bytes) > TAVILY_MAX_RESPONSE_BYTES:
        return jsonify({"error": "Tavily returned an unusable response"}), 502
    try:
        upstream_result = json.loads(bytes(response_bytes).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "Tavily returned an unusable response"}), 502
    if not isinstance(upstream_result, dict) or not isinstance(upstream_result.get("results"), list):
        return jsonify({"error": "Tavily returned an unusable response"}), 502

    provider_results = upstream_result["results"][:max_results]
    if not all(isinstance(item, dict) for item in provider_results):
        return jsonify({"error": "Tavily returned an unusable response"}), 502
    mapped_results = [
        {field: item.get(field) for field in ("title", "url", "content", "score")}
        for item in provider_results
    ]
    if not mapped_results:
        return jsonify({
            "accepted": 0,
            "skipped": 0,
            "batch_id": None,
            "source_id": None,
            "query": query,
            "requested": max_results,
        })
    retrieved_at = utc_now()
    try:
        result = import_web_evidence(
            mapped_results,
            workspace,
            source_label="Tavily web search · unverified",
            query=query,
            retrieved_at=retrieved_at,
        )
    except ValueError:
        return jsonify({"error": "Tavily returned an unusable response"}), 502
    except Exception:
        return jsonify({"error": "Web search evidence could not be saved"}), 500
    return jsonify({**result, "query": query, "requested": max_results})


@app.post("/api/sources/intake/scan")
def intake_scan():
    payload = request.get_json(silent=True) or {}
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        folder_id = payload.get("folder_id")
        if folder_id is not None and not isinstance(folder_id, str):
            raise ValueError("folder_id must be a string")
        return jsonify(scan_intake_folder(workspace, folder_id or None))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/workspaces/<workspace_id>/intake-folders")
def intake_folders_list(workspace_id: str):
    try:
        return jsonify({"workspace": require_workspace(workspace_id),
                        "folders": list_intake_folders(workspace_id)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/api/workspaces/<workspace_id>/intake-folders")
def intake_folder_add(workspace_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        item = add_intake_folder(
            workspace_id, str(payload.get("path") or ""),
            label=payload.get("label"),
            include_subfolders=payload.get("include_subfolders", False),
        )
        return jsonify(item), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/workspaces/<workspace_id>/intake-folders/<folder_id>")
def intake_folder_update(workspace_id: str, folder_id: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        return jsonify(update_intake_folder(workspace_id, folder_id, payload))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/workspaces/<workspace_id>/intake-folders/<folder_id>")
def intake_folder_remove(workspace_id: str, folder_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(remove_intake_folder(
            workspace_id, folder_id, confirmed=payload.get("confirm") is True,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/intake/expenses/<expense_id>")
def intake_expense_correction(expense_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(correct_intake_expense(
            str(payload.get("workspace") or "business"), expense_id,
            payload.get("changes") or {}, str(payload.get("reason") or ""),
        ))
    except (ValueError, ArithmeticError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/intake/expenses/<expense_id>/history")
def intake_expense_history(expense_id: str):
    try:
        return jsonify(list_intake_expense_history(
            str(request.args.get("workspace") or "business"), expense_id,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.get("/api/sources/bank/status")
def bank_status():
    try:
        return jsonify(bank_connector_status(
            _require_workspace(request.args.get("workspace"), "business")
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _bank_connector_error(exc: Exception):
    message = str(exc)
    if "not configured" in message:
        status = 503
    elif "unavailable" in message or "not supported" in message:
        status = 501
    elif "not found" in message:
        status = 404
    else:
        status = 502
    details = getattr(exc, "details", {})
    return jsonify({"error": message, "connected": False, **details}), status


@app.post("/api/sources/bank/link-token")
def bank_link_token():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(create_plaid_link_token(
            str(payload.get("workspace") or "business"),
            str(payload.get("session_id") or "payproof-local-session"),
        ))
    except (RuntimeError, ValueError) as exc:
        return _bank_connector_error(exc)


@app.post("/api/sources/bank/exchange")
def bank_public_token_exchange():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(exchange_plaid_public_token(
            str(payload.get("workspace") or "business"), str(payload.get("public_token") or ""),
            str(payload.get("institution") or ""),
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc), "connected": False}), 400
    except RuntimeError as exc:
        return _bank_connector_error(exc)


@app.post("/api/sources/bank/<connection_id>/sync")
def bank_connection_sync(connection_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(sync_plaid_transactions(
            str(payload.get("workspace") or "business"), connection_id,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return _bank_connector_error(exc)


@app.get("/api/sources/bank/<connection_id>/disconnect-preview")
def bank_connection_disconnect_preview(connection_id: str):
    try:
        workspace = _require_workspace(request.args.get("workspace"), "business")
        session_id = _require_session_id(request.args.get("session_id"))
        details = preview_plaid_disconnect(workspace, connection_id)
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        return jsonify({"error": str(exc)}), status
    preview_id = str(uuid.uuid4())
    with BANK_DISCONNECT_PREVIEW_LOCK:
        _prune_timed_store(BANK_DISCONNECT_PREVIEWS, BANK_DISCONNECT_PREVIEW_TTL_SECONDS)
        BANK_DISCONNECT_PREVIEWS[preview_id] = {
            "workspace": workspace, "connection_id": connection_id,
            "session_fingerprint": _session_fingerprint(session_id),
            "details": details, "created": time.time(),
        }
    return jsonify({**details, "preview_id": preview_id,
                    "expires_in_seconds": BANK_DISCONNECT_PREVIEW_TTL_SECONDS,
                    "one_time": True, "session_bound": True})


@app.delete("/api/sources/bank/<connection_id>")
def bank_connection_disconnect(connection_id: str):
    payload = request.get_json(silent=True) or {}
    preview_id = str(payload.get("preview_id") or "")
    if payload.get("confirm") is not True:
        return jsonify({"error": "A fresh one-time disconnect preview and explicit confirmation are required"}), 400
    try:
        workspace = require_workspace(str(payload.get("workspace") or "business"))
        session_fingerprint = _session_fingerprint(_require_session_id(payload.get("session_id")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    with BANK_DISCONNECT_PREVIEW_LOCK:
        preview = BANK_DISCONNECT_PREVIEWS.get(preview_id)
        if preview and time.time() - preview["created"] > BANK_DISCONNECT_PREVIEW_TTL_SECONDS:
            BANK_DISCONNECT_PREVIEWS.pop(preview_id, None)
            preview = None
        if not preview:
            return jsonify({"error": "A fresh one-time disconnect preview and explicit confirmation are required"}), 400
        matches_requester = (
            preview["connection_id"] == connection_id
            and preview["workspace"] == workspace
            and hmac.compare_digest(preview["session_fingerprint"], session_fingerprint)
        )
        if matches_requester:
            BANK_DISCONNECT_PREVIEWS.pop(preview_id, None)
    if not matches_requester:
        return jsonify({"error": "Disconnect preview does not match this session, workspace, or connection"}), 400
    try:
        current = preview_plaid_disconnect(workspace, connection_id)
        if current != preview["details"]:
            return jsonify({"error": "Connection impact changed; request a new disconnect preview"}), 409
        return jsonify(disconnect_plaid_connection(workspace, connection_id, confirmed=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return _bank_connector_error(exc)


@app.post("/api/import/bank/preview")
def bank_import_preview():
    if "file" not in request.files:
        return jsonify({"error": "Choose a CSV, OFX, or QFX statement"}), 400
    uploaded = request.files["file"]
    filename = Path(uploaded.filename or "bank-statement.csv").name
    if Path(filename).suffix.lower() not in {".csv", ".ofx", ".qfx"}:
        return jsonify({"error": "Supported bank formats are CSV, OFX, and QFX"}), 400
    raw = uploaded.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        return jsonify({"error": "Statement must be between 1 byte and 5 MB"}), 400
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("cp1252")
    workspace = str(request.form.get("workspace") or "business")
    result = preview_bank_statement(workspace, filename, content)
    if result.get("errors"):
        return jsonify(result), 400
    preview_id = str(uuid.uuid4())
    now = time.time()
    for key in [key for key, value in BANK_PREVIEWS.items() if now - value["created"] > 15 * 60]:
        BANK_PREVIEWS.pop(key, None)
    # Raw statement text and full account identifiers are deliberately not retained.
    BANK_PREVIEWS[preview_id] = {
        "workspace": workspace, "filename": filename, "source_hash": result["source_hash"],
        "records": result["accepted"], "created": now,
    }
    return jsonify({**result, "preview_id": preview_id, "expires_in_seconds": 900})


@app.post("/api/import/bank/commit")
def bank_import_commit():
    payload = request.get_json(silent=True) or {}
    preview_id = str(payload.get("preview_id") or "")
    preview = BANK_PREVIEWS.pop(preview_id, None)
    if not preview or time.time() - preview["created"] > 15 * 60:
        return jsonify({"error": "Bank preview expired; choose the statement again"}), 400
    workspace = str(payload.get("workspace") or preview["workspace"])
    if workspace != preview["workspace"]:
        BANK_PREVIEWS[preview_id] = preview
        return jsonify({"error": "The preview belongs to a different workspace"}), 400
    result = commit_bank_statement_preview(
        workspace, preview["filename"], preview["source_hash"], preview["records"],
    )
    if result.get("errors"):
        BANK_PREVIEWS[preview_id] = preview
        return jsonify(result), 400
    return jsonify(result)


@app.get("/api/reconciliation")
def reconciliation():
    try:
        limit = int(request.args.get("limit", "200"))
        workspace = _require_workspace(request.args.get("workspace"), "business")
        return jsonify(get_reconciliation_summary(workspace, limit))
    except ValueError as exc:
        message = str(exc)
        return jsonify({"error": "limit must be a number" if "invalid literal" in message else message}), 400


@app.get("/api/templates/bank.csv")
def bank_csv_template():
    content = "date,description,amount,direction,currency,account_last4,reference,id\n2026-09-05,Example merchant,125.50,debit,USD,4242,INV-EXAMPLE,BANK-EXAMPLE-001\n"
    return Response(content, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=bank-statement-template.csv"})


@app.get("/api/templates/intake.json")
def intake_json_template():
    return jsonify({
        "id": "EXP-YYYY-NNN", "document_type": "employee_expense_report", "employee": "Employee name",
        "department": "Department", "office": "Office", "merchant": "Merchant", "amount": "0.00",
        "currency": "USD", "date": "2026-09-05", "category": "Category", "purpose": "Business purpose",
        "receipt_status": "missing", "approval_status": "needs_review",
    })


@app.get("/api/sources/gmail/connect")
def gmail_connect():
    try:
        workspace = _require_workspace(request.args.get("workspace"), "business")
        session_id = _require_session_id(
            request.args.get("session_id") or "payproof-local-session"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc), "connected": False}), 400
    credentials_path, _ = _gmail_paths(workspace)
    if not credentials_path.exists():
        return jsonify({"error": "Google OAuth client file is missing"}), 400
    if not secure_credentials.secure_storage_available():
        return jsonify({
            "error": "Gmail connection is unavailable because OS-protected token storage is not supported",
            "connected": False,
            "plaintext_fallback_enabled": False,
        }), 501
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return jsonify({"error": "Google connector packages are not installed. Run Setup PayProof.cmd."}), 503
    redirect_uri = request.url_root.rstrip("/") + "/oauth2callback"
    try:
        flow = Flow.from_client_secrets_file(
            str(credentials_path), scopes=GMAIL_SCOPES, redirect_uri=redirect_uri
        )
        authorization_url, state = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent"
        )
        with GMAIL_CREDENTIAL_LOCK:
            _remember_gmail_oauth_state(state, workspace, redirect_uri, session_id)
    except Exception as exc:
        return jsonify({
            "error": f"Google OAuth could not start ({type(exc).__name__})",
            "connected": False,
        }), 400
    return jsonify({
        "authorization_url": authorization_url,
        "workspace": workspace,
        "secure_token_storage": "windows_dpapi",
    })


def _load_gmail_credentials(workspace_id: str):
    from google.oauth2.credentials import Credentials

    _, token_path = _gmail_paths(workspace_id)
    serialized = secure_credentials.read_protected_text(
        token_path, _gmail_token_purpose(workspace_id)
    )
    try:
        information = json.loads(serialized)
        if not isinstance(information, dict):
            raise ValueError("not an object")
        return Credentials.from_authorized_user_info(information, GMAIL_SCOPES)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise secure_credentials.SecureCredentialCorrupt(
            "The decrypted Gmail credential is invalid"
        ) from exc


def _revoke_google_credentials(credentials) -> dict:
    token = str(getattr(credentials, "refresh_token", None) or getattr(credentials, "token", None) or "")
    if not token:
        return {"revoked": False, "provider_status": None, "state": "credential_has_no_revocable_token"}
    request_body = urllib.parse.urlencode({"token": token}).encode("ascii")
    revoke_request = urllib.request.Request(
        "https://oauth2.googleapis.com/revoke",
        data=request_body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(revoke_request, timeout=12) as response:
            status = int(getattr(response, "status", response.getcode()))
    except urllib.error.HTTPError as exc:
        return {"revoked": False, "provider_status": exc.code, "state": "provider_rejected_revocation"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"revoked": False, "provider_status": None, "state": "provider_unreachable"}
    return {
        "revoked": status == 200,
        "provider_status": status,
        "state": "revoked" if status == 200 else "unexpected_provider_response",
    }


@app.post("/api/sources/gmail/disconnect-preview")
def gmail_disconnect_preview():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        session_id = _require_session_id(payload.get("session_id"))
        _, token_path = _gmail_paths(workspace)
        if token_path.exists() and not secure_credentials.secure_storage_available():
            raise secure_credentials.SecureStorageUnavailable(
                "The Gmail credential cannot be opened without OS-protected storage"
            )
        evidence = preview_source_removal(workspace, "gmail")["affected"]["email_evidence"]
        with GMAIL_CREDENTIAL_LOCK:
            credential_digest = _gmail_ciphertext_digest(token_path)
            _prune_timed_store(GMAIL_DISCONNECT_PREVIEWS, GMAIL_PREVIEW_TTL_SECONDS)
            preview_id = str(uuid.uuid4())
            GMAIL_DISCONNECT_PREVIEWS[preview_id] = {
                "workspace": workspace,
                "session_fingerprint": _session_fingerprint(session_id),
                "credential_digest": credential_digest,
                "email_evidence": evidence,
                "created": time.time(),
            }
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except secure_credentials.SecureCredentialError as exc:
        return jsonify({"error": str(exc), "disconnected": False}), 503
    return jsonify({
        "preview_id": preview_id,
        "workspace": workspace,
        "connected": credential_digest is not None,
        "confirmation_required": True,
        "expires_in_seconds": GMAIL_PREVIEW_TTL_SECONDS,
        "impact": {
            "local_encrypted_token_will_be_deleted": credential_digest is not None,
            "google_authorization_will_be_revoked_first": credential_digest is not None,
            "imported_evidence_preserved": True,
            "imported_evidence_count": evidence,
            "gmail_messages_deleted": False,
            "same_google_grant_in_other_workspaces_may_be_affected": True,
        },
    })


@app.post("/api/sources/gmail/disconnect")
def gmail_disconnect():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required", "disconnected": False}), 400
    if payload.get("confirm") is not True:
        return jsonify({
            "error": "Preview the impact and explicitly confirm Gmail disconnection",
            "disconnected": False,
            "upstream_data_deleted": False,
        }), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "business")
        session_id = _require_session_id(payload.get("session_id"))
    except ValueError as exc:
        return jsonify({"error": str(exc), "disconnected": False}), 400
    preview_id = payload.get("preview_id")
    if not isinstance(preview_id, str) or not preview_id:
        return jsonify({"error": "A disconnect preview is required", "disconnected": False}), 400

    with GMAIL_CREDENTIAL_LOCK:
        preview = GMAIL_DISCONNECT_PREVIEWS.pop(preview_id, None)
        if not preview or time.time() - float(preview.get("created", 0)) > GMAIL_PREVIEW_TTL_SECONDS:
            return jsonify({"error": "The disconnect preview is invalid or expired", "disconnected": False}), 400
        if preview.get("workspace") != workspace or not hmac.compare_digest(
            str(preview.get("session_fingerprint") or ""), _session_fingerprint(session_id)
        ):
            return jsonify({"error": "The disconnect preview does not match this workspace and session",
                            "disconnected": False}), 403
        _, token_path = _gmail_paths(workspace)
        try:
            current_digest = _gmail_ciphertext_digest(token_path)
            evidence = preview_source_removal(workspace, "gmail")["affected"]["email_evidence"]
        except secure_credentials.SecureCredentialError as exc:
            return jsonify({"error": str(exc), "disconnected": False}), 503
        if current_digest != preview.get("credential_digest") or evidence != preview.get("email_evidence"):
            return jsonify({"error": "Gmail connection impact changed; create a new preview",
                            "disconnected": False}), 409
        if current_digest is None:
            return jsonify({
                "workspace": workspace,
                "state": "already_disconnected",
                "disconnected": True,
                "upstream_authorization_revoked": None,
                "local_token_deleted": False,
                "imported_evidence_preserved": True,
                "imported_evidence_count": evidence,
                "upstream_data_deleted": False,
            })
        if not secure_credentials.secure_storage_available():
            return jsonify({
                "error": "OS-protected storage is unavailable; the credential was not opened or deleted",
                "state": "secure_storage_unavailable",
                "disconnected": False,
                "upstream_authorization_revoked": False,
                "local_token_deleted": False,
                "imported_evidence_preserved": True,
            }), 503
        try:
            credentials = _load_gmail_credentials(workspace)
        except (ImportError, secure_credentials.SecureCredentialError):
            return jsonify({
                "error": "The encrypted Gmail credential could not be loaded; nothing was deleted",
                "state": "credential_load_failed",
                "disconnected": False,
                "upstream_authorization_revoked": False,
                "local_token_deleted": False,
                "imported_evidence_preserved": True,
            }), 503
        revocation = _revoke_google_credentials(credentials)
        if not revocation["revoked"]:
            return jsonify({
                "error": "Google authorization could not be revoked; the encrypted token was retained for retry",
                "state": revocation["state"],
                "provider_status": revocation["provider_status"],
                "disconnected": False,
                "upstream_authorization_revoked": False,
                "local_token_deleted": False,
                "imported_evidence_preserved": True,
                "imported_evidence_count": evidence,
                "upstream_data_deleted": False,
            }), 502
        try:
            token_path.unlink()
        except OSError:
            return jsonify({
                "error": "Google authorization was revoked, but local encrypted-token cleanup failed",
                "state": "upstream_revoked_local_cleanup_failed",
                "provider_status": revocation["provider_status"],
                "disconnected": False,
                "upstream_authorization_revoked": True,
                "local_token_deleted": False,
                "imported_evidence_preserved": True,
                "imported_evidence_count": evidence,
                "upstream_data_deleted": False,
            }), 500
    return jsonify({
        "workspace": workspace,
        "state": "disconnected",
        "disconnected": True,
        "provider_status": revocation["provider_status"],
        "upstream_authorization_revoked": True,
        "local_token_deleted": True,
        "imported_evidence_preserved": True,
        "imported_evidence_count": evidence,
        "upstream_data_deleted": False,
        "notice": "Google authorization was revoked and PayProof's encrypted token was deleted. Imported evidence was preserved.",
    })


@app.get("/oauth2callback")
def gmail_callback():
    state = request.args.get("state", "")
    with GMAIL_CREDENTIAL_LOCK:
        oauth_state = _consume_gmail_oauth_state(state)
    if not oauth_state:
        return "Invalid or expired OAuth state. Return to PayProof and try again.", 400
    workspace = oauth_state["workspace"]
    credentials_path, token_path = _gmail_paths(workspace)
    if not secure_credentials.secure_storage_available():
        return "Gmail connection failed because protected token storage is unavailable. No plaintext token was saved.", 503
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(credentials_path), scopes=GMAIL_SCOPES, state=state,
            redirect_uri=oauth_state["redirect_uri"],
        )
        flow.fetch_token(authorization_response=request.url)
    except Exception as exc:
        return f"Gmail connection failed: {type(exc).__name__}. Return to PayProof and try again.", 400
    try:
        with GMAIL_CREDENTIAL_LOCK:
            secure_credentials.write_protected_text(
                token_path, flow.credentials.to_json(), _gmail_token_purpose(workspace)
            )
    except secure_credentials.SecureCredentialError:
        revocation = _revoke_google_credentials(flow.credentials)
        state_notice = "The new authorization was revoked." if revocation["revoked"] else (
            "Automatic revocation also failed; remove PayProof from your Google Account permissions."
        )
        return (
            "Gmail connection failed because the token could not be stored securely. "
            f"No plaintext token was saved. {state_notice}",
            503,
        )
    return (
        "<html><body style='background:#020711;color:#edf8ff;font-family:Segoe UI;padding:40px'>"
        "<h1>Gmail connected</h1><p>The read-only authorization was encrypted with Windows DPAPI "
        f"for the {workspace} workspace. Return to PayProof and select Import Gmail evidence.</p>"
        "<script>setTimeout(()=>window.close(),2500)</script></body></html>"
    )


@app.post("/api/sources/gmail/import")
def gmail_import():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    try:
        workspace = _require_workspace(payload.get("workspace"), "personal")
        max_results = min(max(int(payload.get("max_results", 20)), 1), 50)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc) if str(exc) == "Unknown workspace" else "max_results must be a number"}), 400
    query = str(payload.get("query") or "newer_than:365d (from:amazon.com OR category:purchases)").strip()
    if not query or len(query) > 500:
        return jsonify({"error": "Gmail query must be between 1 and 500 characters"}), 400
    _, token_path = _gmail_paths(workspace)
    if not token_path.exists():
        return jsonify({"error": "Connect Gmail for this workspace first"}), 400
    if not secure_credentials.secure_storage_available():
        return jsonify({"error": "Protected Gmail token storage is unavailable; plaintext fallback is disabled"}), 503
    try:
        from googleapiclient.discovery import build
        with GMAIL_CREDENTIAL_LOCK:
            credentials = _load_gmail_credentials(workspace)
            service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
            listing = service.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            imported = []
            for item in listing.get("messages", []):
                message = service.users().messages().get(
                    userId="me", id=item["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                headers = {
                    h["name"].lower(): h["value"]
                    for h in message.get("payload", {}).get("headers", [])
                }
                imported.append({
                    "id": item["id"],
                    "sender": headers.get("from", "Unknown sender"),
                    "subject": headers.get("subject", "(no subject)"),
                    "received_at": headers.get("date", ""),
                    "snippet": message.get("snippet", ""),
                })
            # Persist any refreshed access token using the same encrypted envelope
            # before accepting imported evidence. No decrypted temp file is used.
            secure_credentials.write_protected_text(
                token_path, credentials.to_json(), _gmail_token_purpose(workspace)
            )
            result = import_gmail_metadata(imported, workspace)
        return jsonify({**result, "query": query, "requested": max_results})
    except ImportError:
        return jsonify({"error": "Google connector packages are not installed. Run Setup PayProof.cmd."}), 503
    except secure_credentials.SecureCredentialError as exc:
        return jsonify({"error": str(exc), "imported": False}), 503
    except Exception as exc:
        return jsonify({"error": f"Gmail import failed ({type(exc).__name__})"}), 502


@app.delete("/api/sources/<source_id>")
def delete_source(source_id: str):
    preview_id = str(request.args.get("preview_id") or "")
    confirm = str(request.args.get("confirm") or "").lower() == "true"
    preview = SOURCE_REMOVAL_PREVIEWS.pop(preview_id, None)
    if not confirm or not preview or time.time() - preview["created"] > 15 * 60:
        return jsonify({"error": "Preview the affected records and explicitly confirm removal first",
                        "upstream_data_deleted": False}), 400
    workspace = request.args.get("workspace", "business")
    if preview["source_id"] != source_id or preview["workspace"] != workspace:
        return jsonify({"error": "Removal preview does not match this source or workspace"}), 400
    try:
        current = preview_source_removal(workspace, source_id)
        if current != preview["details"]:
            return jsonify({"error": "Source contents changed; create a new removal preview"}), 409
        return jsonify(remove_source(workspace, source_id, confirmed=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


@app.get("/api/sources/<source_id>/removal-preview")
def source_removal_preview(source_id: str):
    workspace = request.args.get("workspace", "business")
    try:
        details = preview_source_removal(workspace, source_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    preview_id = str(uuid.uuid4())
    SOURCE_REMOVAL_PREVIEWS[preview_id] = {
        "source_id": source_id, "workspace": workspace, "details": details, "created": time.time(),
    }
    return jsonify({**details, "preview_id": preview_id, "expires_in_seconds": 900,
                    "confirmation_required": True})


@app.post("/api/ocr/preview")
def ocr_preview():
    if "file" not in request.files:
        return jsonify({"error": "Choose a PNG, JPG, or WEBP image"}), 400
    uploaded = request.files["file"]
    extension = Path(uploaded.filename or "").suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        return jsonify({"error": "Supported image types: PNG, JPG, JPEG, WEBP"}), 400
    image_bytes = uploaded.read()
    if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
        return jsonify({"error": "Image must be between 1 byte and 10 MB"}), 400
    temp_path = None
    try:
        from rapidocr import RapidOCR
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as handle:
            handle.write(image_bytes)
            temp_path = Path(handle.name)
        output = RapidOCR()(str(temp_path))
        lines = [str(value).strip() for value in (output.txts or []) if str(value).strip()]
        scores = [float(value) for value in (output.scores or [])]
    except ImportError:
        return jsonify({"error": "Local OCR is not installed. Run Setup PayProof.cmd."}), 503
    except Exception as exc:
        return jsonify({"error": f"OCR could not read this image: {type(exc).__name__}"}), 400
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
    text = "\n".join(lines)
    amount_candidates = []
    for match in re.finditer(r"(?:\$|USD\s*)?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2}))", text, re.IGNORECASE):
        try:
            amount_candidates.append(Decimal(match.group(1).replace(",", "")))
        except ArithmeticError:
            pass
    date_match = re.search(r"\b(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)\b", text)
    suggested_date = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}" if date_match else date.today().isoformat()
    merchant = next((line for line in lines if len(line) >= 3 and not re.fullmatch(r"[\d\W]+", line)), "Unknown merchant")[:120]
    preview_id = str(uuid.uuid4())
    source_hash = hashlib.sha256(image_bytes).hexdigest()
    OCR_PREVIEWS[preview_id] = {"filename": uploaded.filename or f"receipt{extension}", "source_hash": source_hash,
                                "text": text, "created": time.time()}
    return jsonify({"preview_id": preview_id, "filename": uploaded.filename, "text": text, "line_count": len(lines),
                    "average_confidence": round(sum(scores) / len(scores), 3) if scores else 0,
                    "suggested": {"merchant": merchant, "amount": str(max(amount_candidates)) if amount_candidates else "",
                                  "currency": "USD", "date": suggested_date}})


@app.post("/api/ocr/commit")
def ocr_commit():
    payload = request.get_json(silent=True) or {}
    preview = OCR_PREVIEWS.pop(str(payload.get("preview_id", "")), None)
    if not preview:
        return jsonify({"error": "OCR preview expired; choose the image again"}), 400
    try:
        result = import_ocr_receipt(str(payload.get("workspace") or "personal"), preview["filename"], preview["source_hash"],
                                    str(payload.get("merchant", "")), str(payload.get("amount", "")),
                                    str(payload.get("currency", "USD")), str(payload.get("date", "")))
        return jsonify(result)
    except ValueError as exc:
        OCR_PREVIEWS[str(payload.get("preview_id"))] = preview
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    initialize_database()
    app.run(host="127.0.0.1", port=int(os.getenv("PAYPROOF_PORT", "8765")), debug=False)
