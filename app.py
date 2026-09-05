from __future__ import annotations

import os
import time
import json
import hashlib
import re
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from src.core import (
    PROJECT_ROOT,
    answer_question,
    get_dashboard,
    get_record,
    import_transactions_csv,
    import_gmail_metadata,
    import_ocr_receipt,
    initialize_database,
    list_import_sources,
    prism_status,
    record_action,
    remove_source,
    scan_intake_folder,
    send_prism_trace,
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
initialize_database()
app = Flask(__name__, static_folder="static", static_url_path="/static")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OAUTH_STATE: dict[str, str] = {}
OCR_PREVIEWS: dict[str, dict] = {}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/dashboard")
def dashboard():
    workspace = request.args.get("workspace", "business")
    if workspace not in {"business", "personal"}:
        return jsonify({"error": "Unknown workspace"}), 400
    return jsonify(get_dashboard(workspace))


@app.get("/api/records/<path:entity_id>")
def record(entity_id: str):
    workspace = request.args.get("workspace", "business")
    item = get_record(entity_id, workspace)
    return (jsonify(item), 200) if item else (jsonify({"error": "Record not found"}), 404)


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify({"error": "Ask a question"}), 400
    workspace = payload.get("workspace", "business")
    selected_id = payload.get("selected_id")
    session_id = str(payload.get("session_id") or "payproof-session")
    started = time.perf_counter()
    result = answer_question(question, workspace, selected_id, payload.get("filters"))
    latency = round((time.perf_counter() - started) * 1000)
    trace = send_prism_trace(question, result, session_id, latency, workspace)
    return jsonify({"answer": result.answer, "evidence_ids": result.evidence_ids, "focus_ids": result.focus_ids,
                    "calculation": result.calculation, "context": {"workspace": workspace, "selected_id": selected_id,
                    "evidence_ids": result.evidence_ids, "calculation": result.calculation}, "trace": trace})


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
    initialize_database(reset=True)
    return jsonify({"ok": True})


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


def _gmail_paths():
    return PROJECT_ROOT / "credentials.json.json", PROJECT_ROOT / "data" / "runtime" / "gmail-token.json"


@app.get("/api/sources")
def sources():
    workspace = request.args.get("workspace", "business")
    credentials_path, token_path = _gmail_paths()
    return jsonify({
        "gmail": {"credentials_available": credentials_path.exists(), "connected": token_path.exists(),
                  "mode": "read-only metadata and snippets", "token_stored_locally": token_path.exists()},
        "imports": list_import_sources(workspace), "csv": {"available": True},
        "intake_folder": {"available": True, "mode": "local JSON paperwork", "path": str(PROJECT_ROOT / "intake")},
    })


@app.post("/api/sources/intake/scan")
def intake_scan():
    return jsonify(scan_intake_folder())


@app.get("/api/sources/gmail/connect")
def gmail_connect():
    credentials_path, _ = _gmail_paths()
    if not credentials_path.exists():
        return jsonify({"error": "Google OAuth client file is missing"}), 400
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return jsonify({"error": "Google connector packages are not installed. Run Setup PayProof.cmd."}), 503
    redirect_uri = request.url_root.rstrip("/") + "/oauth2callback"
    flow = Flow.from_client_secrets_file(str(credentials_path), scopes=GMAIL_SCOPES, redirect_uri=redirect_uri)
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    OAUTH_STATE[state] = redirect_uri
    return jsonify({"authorization_url": authorization_url})


@app.get("/oauth2callback")
def gmail_callback():
    state = request.args.get("state", "")
    redirect_uri = OAUTH_STATE.pop(state, None)
    if not redirect_uri:
        return "Invalid or expired OAuth state. Return to PayProof and try again.", 400
    credentials_path, token_path = _gmail_paths()
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(str(credentials_path), scopes=GMAIL_SCOPES, state=state, redirect_uri=redirect_uri)
        flow.fetch_token(authorization_response=request.url)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(flow.credentials.to_json(), encoding="utf-8")
        return "<html><body style='background:#020711;color:#edf8ff;font-family:Segoe UI;padding:40px'><h1>Gmail connected</h1><p>Read-only permission was saved locally. Return to PayProof and select Import Gmail evidence.</p><script>setTimeout(()=>window.close(),2500)</script></body></html>"
    except Exception as exc:
        return f"Gmail connection failed: {type(exc).__name__}. Return to PayProof and try again.", 400


@app.post("/api/sources/gmail/import")
def gmail_import():
    _, token_path = _gmail_paths()
    if not token_path.exists():
        return jsonify({"error": "Connect Gmail first"}), 400
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or "newer_than:365d (from:amazon.com OR category:purchases)")
    max_results = min(max(int(payload.get("max_results", 20)), 1), 50)
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        listing = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        imported = []
        for item in listing.get("messages", []):
            message = service.users().messages().get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
            imported.append({"id": item["id"], "sender": headers.get("from", "Unknown sender"),
                             "subject": headers.get("subject", "(no subject)"), "received_at": headers.get("date", ""),
                             "snippet": message.get("snippet", "")})
        result = import_gmail_metadata(imported, str(payload.get("workspace") or "personal"))
        return jsonify({**result, "query": query, "requested": max_results})
    except Exception as exc:
        return jsonify({"error": f"Gmail import failed: {type(exc).__name__}: {exc}"}), 400


@app.delete("/api/sources/<source_id>")
def delete_source(source_id: str):
    try:
        return jsonify(remove_source(request.args.get("workspace", "business"), source_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404


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
    app.run(host="127.0.0.1", port=int(os.getenv("PAYPROOF_PORT", "8765")), debug=False)
