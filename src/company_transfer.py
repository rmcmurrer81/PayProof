"""Portable, single-company financial record exports.

The exporter is deliberately read-only and accepts an existing SQLite connection.
It never reads intake folders, connector stores, ``.env`` files, or logo files.  A
transfer package contains sanitized database records for one custom company in
JSON and CSV, plus a self-contained HTML report that opens without PayProof.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import re
import sqlite3
import zipfile
from datetime import datetime, timezone
from typing import Any, Iterable


TRANSFER_FORMAT = "payproof-company-transfer"
TRANSFER_VERSION = 1
DEFAULT_MAX_ROWS_PER_TABLE = 10_000
DEFAULT_MAX_TOTAL_ROWS = 50_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARACTERS = 1_000_000
MAX_ARCHIVE_FILES = 40


class CompanyTransferError(ValueError):
    """Base error for an export that cannot be produced safely."""


class CompanyTransferLimitError(CompanyTransferError):
    """Raised instead of silently truncating a transfer package."""


# This is an allowlist, not a list of columns to exclude.  New database columns
# therefore cannot accidentally place credentials into a transfer archive.
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "vendors": (
        "id", "workspace_id", "name", "category", "city", "lat", "lon",
        "verified_destination_masked", "verified_contact", "verified_at",
    ),
    "transactions": (
        "id", "workspace_id", "vendor_id", "merchant_raw", "amount_cents",
        "currency", "occurred_on", "office", "kind", "source_id", "reference",
    ),
    "invoices": (
        "id", "workspace_id", "vendor_id", "amount_cents", "currency",
        "invoice_date", "destination_masked", "source_id", "status",
    ),
    "receipts": (
        "id", "workspace_id", "vendor_id", "amount_cents", "currency",
        "receipt_date", "transaction_id", "source_id",
    ),
    "employees": (
        "id", "workspace_id", "name", "department", "office",
    ),
    "expense_reports": (
        "id", "workspace_id", "employee_id", "merchant", "amount_cents",
        "currency", "spent_on", "category", "purpose", "receipt_status",
        "approval_status", "source_id",
    ),
    "bank_transactions": (
        "id", "workspace_id", "provider", "account_mask", "description",
        "amount_cents", "currency", "posted_on", "direction", "reference",
        "source_id", "import_id", "is_synthetic", "imported_at",
    ),
    "email_evidence": (
        "id", "workspace_id", "provider", "sender", "subject", "received_at",
        "snippet", "source_label", "is_synthetic", "content_hash", "imported_at",
    ),
    "intake_documents": (
        "id", "workspace_id", "filename", "document_type", "source_id",
        "employee_id", "status", "is_synthetic", "content_hash", "imported_at",
    ),
    "reconciliations": (
        "id", "workspace_id", "bank_transaction_id", "evidence_type",
        "evidence_id", "evidence_source_id", "confidence", "match_basis",
        "evidence_context", "status", "created_at",
    ),
    "intake_versions": (
        "id", "workspace_id", "expense_id", "version", "snapshot_json",
        "changed_fields", "reason", "source_kind", "created_at",
    ),
    "imports": (
        "id", "workspace_id", "filename", "source_hash", "accepted", "rejected",
        "created_at",
    ),
    "audit": (
        "id", "workspace_id", "finding_id", "action", "reason", "created_at",
    ),
}

PROFILE_COLUMNS = (
    "id", "name", "kind", "is_demo", "website", "archived_at",
)

MAJOR_REPORT_TABLES = (
    "transactions", "invoices", "receipts", "bank_transactions",
    "expense_reports", "email_evidence", "intake_documents", "reconciliations",
)

_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)([\"']?\b(?:access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
    r"api[_ -]?key|password|passwd|plaid[_ -]?secret|private[_ -]?key|"
    r"authorization|secret|token)\b[\"']?)(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;\"']+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_TOKEN_SHAPES = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|access-(?:sandbox|development|production)-"
    r"[A-Za-z0-9_-]{6,}|AIza[A-Za-z0-9_-]{20,})\b"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_DANGEROUS_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _quoted(identifier: str) -> str:
    """Quote an identifier after ensuring it came from this module's allowlist."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", identifier):
        raise CompanyTransferError("Unsafe database identifier")
    return f'"{identifier}"'


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        raise CompanyTransferError(f"Required transfer table is missing: {table}")
    return tuple(str(row[1]) for row in connection.execute(
        f"PRAGMA table_info({_quoted(table)})"
    ).fetchall())


def _query_dicts(connection: sqlite3.Connection, sql: str,
                 parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, tuple(parameters))
    names = [str(item[0]) for item in cursor.description or ()]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _redact_text(value: str) -> tuple[str, int]:
    if len(value) > MAX_TEXT_CHARACTERS:
        raise CompanyTransferLimitError(
            f"A text field exceeds the {MAX_TEXT_CHARACTERS:,}-character safety limit"
        )
    value = _DANGEROUS_CONTROL.sub("�", value)
    redactions = 0
    # Remove full key blocks before assignment matching can consume only the
    # header and leave key material behind.
    value, private_key_count = _PRIVATE_KEY_BLOCK.subn(
        "[REDACTED_PRIVATE_KEY]", value,
    )
    redactions += private_key_count

    def assignment(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        original_value = match.group(3)
        if original_value.startswith('"'):
            replacement = '"[REDACTED_CREDENTIAL]"'
        elif original_value.startswith("'"):
            replacement = "'[REDACTED_CREDENTIAL]'"
        else:
            replacement = "[REDACTED_CREDENTIAL]"
        return f"{match.group(1)}{match.group(2)}{replacement}"

    value = _CREDENTIAL_ASSIGNMENT.sub(assignment, value)
    for pattern, replacement in (
        (_BEARER_TOKEN, "Bearer [REDACTED_CREDENTIAL]"),
        (_TOKEN_SHAPES, "[REDACTED_CREDENTIAL]"),
    ):
        value, count = pattern.subn(replacement, value)
        redactions += count
    return value, redactions


def _sanitize_value(value: Any) -> tuple[Any, int]:
    if value is None or isinstance(value, (bool, int)):
        return value, 0
    if isinstance(value, float):
        if math.isfinite(value):
            return value, 0
        return None, 1
    if isinstance(value, bytes):
        fingerprint = hashlib.sha256(value).hexdigest()
        return f"[BINARY OMITTED: {len(value)} bytes; sha256={fingerprint}]", 1
    if isinstance(value, str):
        return _redact_text(value)
    # SQLite should not return complex values, but fail closed without placing a
    # potentially secret object representation into the package.
    return f"[UNSUPPORTED {type(value).__name__} OMITTED]", 1


def _sanitize_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    sanitized: list[dict[str, Any]] = []
    redactions = 0
    for row in rows:
        clean: dict[str, Any] = {}
        for key, value in row.items():
            clean_value, count = _sanitize_value(value)
            clean[key] = clean_value
            redactions += count
        sanitized.append(clean)
    return sanitized, redactions


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
    ) + "\n").encode("utf-8")


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    # Prevent a spreadsheet from treating imported text as a formula.
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _csv_cell(row.get(column)) for column in columns})
    # UTF-8 BOM helps Excel recognize Unicode without changing the JSON values.
    return stream.getvalue().encode("utf-8-sig")


def _amount_label(cents: Any, currency: str) -> str:
    try:
        amount = int(cents) / 100
    except (TypeError, ValueError):
        return "Unknown"
    return f"{currency or 'UNKNOWN'} {amount:,.2f}"


def _financial_totals(records: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for table in ("transactions", "invoices", "receipts", "bank_transactions", "expense_reports"):
        for row in records.get(table, []):
            currency = str(row.get("currency") or "UNKNOWN").upper()
            dimension = ""
            if table == "transactions":
                dimension = str(row.get("kind") or "unknown")
            elif table == "bank_transactions":
                dimension = str(row.get("direction") or "unknown")
            key = (table, currency, dimension)
            group = groups.setdefault(key, {
                "dataset": table,
                "currency": currency,
                "type": dimension or "all records",
                "count": 0,
                "amount_cents": 0,
            })
            group["count"] += 1
            try:
                group["amount_cents"] += int(row.get("amount_cents") or 0)
            except (TypeError, ValueError):
                pass
    return [groups[key] for key in sorted(groups)]


def _html_cell(value: Any, column: str, row: dict[str, Any]) -> str:
    if column.endswith("amount_cents"):
        text = _amount_label(value, str(row.get("currency") or "UNKNOWN"))
    elif value is None:
        text = "—"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return html.escape(text, quote=True)


def _html_table(columns: tuple[str, ...], rows: list[dict[str, Any]], *,
                max_rows: int = 200) -> str:
    headings = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_rows: list[str] = []
    for row in rows[:max_rows]:
        cells = "".join(f"<td>{_html_cell(row.get(column), column, row)}</td>"
                        for column in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{max(1, len(columns))}" class="empty">No records</td></tr>')
    return f"<div class=\"table-wrap\"><table><thead><tr>{headings}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"


def _report_html(profile: dict[str, Any], records: dict[str, list[dict[str, Any]]],
                 columns: dict[str, tuple[str, ...]], generated_at: str) -> bytes:
    counts = "".join(
        f'<div class="stat"><strong>{len(records[table]):,}</strong><span>{html.escape(table.replace("_", " ").title())}</span></div>'
        for table in TABLE_COLUMNS
    )
    totals = _financial_totals(records)
    totals_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['dataset'].replace('_', ' ').title())}</td>"
        f"<td>{html.escape(item['type'])}</td>"
        f"<td>{item['count']:,}</td>"
        f"<td>{html.escape(_amount_label(item['amount_cents'], item['currency']))}</td>"
        "</tr>" for item in totals
    ) or '<tr><td colspan="4" class="empty">No financial totals available</td></tr>'
    profile_rows = "".join(
        f"<tr><th>{html.escape(str(key).replace('_', ' ').title())}</th><td>{_html_cell(value, str(key), profile)}</td></tr>"
        for key, value in profile.items()
    )
    sections: list[str] = []
    for table in MAJOR_REPORT_TABLES:
        rows = records[table]
        note = ""
        if len(rows) > 200:
            note = f'<p class="note">Showing the first 200 of {len(rows):,} records. Open the CSV or JSON file for the complete dataset.</p>'
        sections.append(
            f'<section><h2>{html.escape(table.replace("_", " ").title())}</h2>'
            f'<p class="count">{len(rows):,} record(s)</p>{note}'
            f'{_html_table(columns[table], rows)}</section>'
        )

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PayProof transfer — {html.escape(str(profile.get('name') or profile.get('id')))}</title>
<style>
:root{{--ink:#102032;--muted:#607084;--line:#d8e1ea;--navy:#071d32;--cyan:#19bfee;--paper:#f4f7fa;--white:#fff}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:linear-gradient(120deg,var(--navy),#0c4963);color:white;padding:36px max(24px,6vw)}}
header h1{{font-size:clamp(27px,4vw,44px);margin:.1em 0}} header p{{max-width:850px;color:#cdeafa}}
main{{max-width:1400px;margin:auto;padding:28px}} section{{background:var(--white);border:1px solid var(--line);border-radius:14px;margin:0 0 22px;padding:22px;box-shadow:0 6px 20px #0b22340c}}
h2{{margin:0 0 4px}} .notice{{border-left:5px solid var(--cyan)}} .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:18px 0}}
.stat{{background:#eaf8fc;border:1px solid #b8e7f4;border-radius:10px;padding:14px}} .stat strong{{display:block;font-size:24px}} .stat span,.note,.count{{color:var(--muted)}}
.table-wrap{{overflow:auto;max-height:470px;border:1px solid var(--line);border-radius:9px}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px 11px;max-width:420px;overflow-wrap:anywhere}} thead th{{position:sticky;top:0;background:#e9f2f7;z-index:1}} .empty{{color:var(--muted);text-align:center}} footer{{padding:10px 0 35px;color:var(--muted)}}
@media print{{body{{background:#fff}} section{{break-inside:avoid;box-shadow:none}} .table-wrap{{max-height:none;overflow:visible}} thead th{{position:static}}}}
</style></head><body>
<header><div>PAYPROOF PORTABLE TRANSFER</div><h1>{html.escape(str(profile.get('name') or profile.get('id')))}</h1>
<p>Single-company financial paperwork and evidence export generated {html.escape(generated_at)}. This report is self-contained and does not require PayProof or an internet connection.</p></header>
<main><section class="notice"><h2>Transfer safety notice</h2><p>Bank and email credentials, access tokens, connector authorization, environment files, and raw intake-folder files are not included. The new owner must reconnect authorized accounts. Totals below summarize recorded evidence; they are not audited financial statements.</p></section>
<section><h2>Company profile</h2><table><tbody>{profile_rows}</tbody></table></section>
<section><h2>Package inventory</h2><div class="stats">{counts}</div></section>
<section><h2>Recorded amounts by currency and type</h2><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Type</th><th>Records</th><th>Recorded amount</th></tr></thead><tbody>{totals_rows}</tbody></table></div></section>
{''.join(sections)}
<footer>PayProof portable transfer format v{TRANSFER_VERSION}. Verify file hashes against manifest.json before relying on the package.</footer></main></body></html>"""
    return document.encode("utf-8")


def _readme_text(profile: dict[str, Any], generated_at: str) -> bytes:
    name, _ = _redact_text(str(profile.get("name") or profile.get("id") or "Company"))
    workspace_id, _ = _redact_text(str(profile.get("id") or "unknown"))
    return f"""PayProof portable company transfer
==================================

Company: {name}
Workspace: {workspace_id}
Generated (UTC): {generated_at}

HOW TO OPEN THIS PACKAGE
------------------------
1. Open index.html in any modern web browser for a self-contained readable report.
2. Open files in csv/ with Microsoft Excel, Google Sheets, or another spreadsheet app.
3. Open files in json/ with any text editor or data tool for structured records.
4. Use manifest.json to verify the SHA-256 hash and byte count of every payload file.

PayProof is not required to read this transfer package. No external website, script,
font, image, or other asset is required by index.html.

SECURITY AND SCOPE
------------------
This archive contains database records for only the company workspace named above.
It does NOT contain bank credentials, email credentials, connector access or refresh
tokens, API keys, passwords, .env files, PayProof runtime connector stores, company
logo files, or raw files from intake folders. Credential-shaped strings found in
otherwise exportable evidence are replaced with [REDACTED_CREDENTIAL]. Spreadsheet
formula-like text is neutralized in CSV copies.

The buyer or new owner must use their own authorization to reconnect every bank and
email account. Reconnection should follow the financial institution's and email
provider's consent flows. Never send credentials inside this archive.

COMPLETENESS
------------
The exporter fails instead of silently truncating a table when a configured safety
limit is exceeded. JSON and CSV files contain the complete exported rows. For very
large datasets, index.html previews the first 200 rows while displaying full counts.
Recorded totals summarize evidence and are not audited financial statements.
""".encode("utf-8")


def _normalize_generated_at(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    cleaned, _ = _redact_text(str(value).strip())
    if not cleaned or len(cleaned) > 80:
        raise CompanyTransferError("generated_at must be a short timestamp")
    return cleaned


def suggested_transfer_filename(company_name: str, generated_at: str | datetime | None = None) -> str:
    """Return a path-safe download name; it never incorporates a workspace path."""
    safe_name = re.sub(r"[^a-z0-9]+", "-", str(company_name).lower()).strip("-")
    safe_name = (safe_name[:70].rstrip("-") or "company")
    stamp = _normalize_generated_at(generated_at)[:10].replace("-", "")
    if not re.fullmatch(r"\d{8}", stamp):
        stamp = "transfer"
    return f"payproof-{safe_name}-{stamp}.zip"


def _write_zip_entry(archive: zipfile.ZipFile, path: str, content: bytes) -> None:
    if path.startswith(("/", "\\")) or ".." in path.split("/"):
        raise CompanyTransferError("Unsafe archive path")
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    info.flag_bits |= 0x800
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_company_transfer_zip(
    connection: sqlite3.Connection,
    workspace_id: str,
    *,
    generated_at: str | datetime | None = None,
    max_rows_per_table: int = DEFAULT_MAX_ROWS_PER_TABLE,
    max_total_rows: int = DEFAULT_MAX_TOTAL_ROWS,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> bytes:
    """Build a portable ZIP for one custom company without modifying the database.

    ``connection`` remains open and retains ownership of any transaction it already
    had.  A temporary read transaction is used when the caller is not in one.
    """
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    workspace_id = str(workspace_id).strip()
    if not workspace_id or len(workspace_id) > 160:
        raise CompanyTransferError("A valid workspace ID is required")
    if not (1 <= int(max_rows_per_table) <= 1_000_000):
        raise CompanyTransferError("max_rows_per_table is outside the supported range")
    if not (1 <= int(max_total_rows) <= 2_000_000):
        raise CompanyTransferError("max_total_rows is outside the supported range")
    if not (1_024 <= int(max_uncompressed_bytes) <= 512 * 1024 * 1024):
        raise CompanyTransferError("max_uncompressed_bytes is outside the supported range")

    timestamp = _normalize_generated_at(generated_at)
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        workspace_columns = _table_columns(connection, "workspaces")
        required_profile = {"id", "name", "kind", "is_demo"}
        if not required_profile.issubset(workspace_columns):
            raise CompanyTransferError("The workspace profile schema is incomplete")
        selected_profile_columns = tuple(
            item for item in PROFILE_COLUMNS if item in workspace_columns
        )
        profile_rows = _query_dicts(
            connection,
            f"SELECT {', '.join(map(_quoted, selected_profile_columns))} "
            "FROM workspaces WHERE id=?",
            (workspace_id,),
        )
        if not profile_rows:
            raise CompanyTransferError("Unknown company workspace")
        profile, profile_redactions = _sanitize_rows(profile_rows)
        profile_row = profile[0]
        if str(profile_row.get("kind") or "").lower() != "company" or bool(profile_row.get("is_demo")):
            raise CompanyTransferError("Only custom company workspaces can be transferred")
        profile_row["is_demo"] = bool(profile_row.get("is_demo"))
        profile_row["logo_included"] = False

        records: dict[str, list[dict[str, Any]]] = {}
        selected_columns: dict[str, tuple[str, ...]] = {}
        row_total = 0
        redaction_total = profile_redactions
        for table, allowed_columns in TABLE_COLUMNS.items():
            available = _table_columns(connection, table)
            if "workspace_id" not in available:
                raise CompanyTransferError(f"Transfer table is not company-scoped: {table}")
            columns = tuple(item for item in allowed_columns if item in available)
            if not columns or "workspace_id" not in columns:
                raise CompanyTransferError(f"Transfer allowlist is incomplete for: {table}")
            count = int(connection.execute(
                f"SELECT COUNT(*) FROM {_quoted(table)} WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()[0])
            if count > max_rows_per_table:
                raise CompanyTransferLimitError(
                    f"{table} has {count:,} rows; limit is {max_rows_per_table:,}. "
                    "Increase the explicit limit rather than accepting a partial transfer."
                )
            row_total += count
            if row_total > max_total_rows:
                raise CompanyTransferLimitError(
                    f"The company has {row_total:,} export rows; total limit is {max_total_rows:,}."
                )
            order_column = "id" if "id" in columns else columns[0]
            raw_rows = _query_dicts(
                connection,
                f"SELECT {', '.join(map(_quoted, columns))} FROM {_quoted(table)} "
                f"WHERE workspace_id=? ORDER BY {_quoted(order_column)}",
                (workspace_id,),
            )
            clean_rows, redactions = _sanitize_rows(raw_rows)
            records[table] = clean_rows
            selected_columns[table] = columns
            redaction_total += redactions
    finally:
        if owns_transaction and connection.in_transaction:
            connection.rollback()

    payloads: dict[str, bytes] = {}
    payloads["company-profile.json"] = _json_bytes(profile_row)
    for table in TABLE_COLUMNS:
        envelope = {
            "record_count": len(records[table]),
            "records": records[table],
            "table": table,
            "workspace_id": workspace_id,
        }
        payloads[f"json/{table}.json"] = _json_bytes(envelope)
        payloads[f"csv/{table}.csv"] = _csv_bytes(selected_columns[table], records[table])
    payloads["index.html"] = _report_html(
        profile_row, records, selected_columns, timestamp,
    )
    payloads["README.txt"] = _readme_text(profile_row, timestamp)

    if len(payloads) + 1 > MAX_ARCHIVE_FILES:
        raise CompanyTransferLimitError("The transfer would exceed the archive file limit")
    payload_bytes = sum(len(content) for content in payloads.values())
    if payload_bytes > max_uncompressed_bytes:
        raise CompanyTransferLimitError(
            f"The transfer payload is {payload_bytes:,} bytes; limit is {max_uncompressed_bytes:,}."
        )

    file_manifest = [
        {
            "bytes": len(payloads[path]),
            "path": path,
            "record_count": (
                len(records[path.rsplit('/', 1)[-1].rsplit('.', 1)[0]])
                if path.startswith(("json/", "csv/")) else None
            ),
            "sha256": hashlib.sha256(payloads[path]).hexdigest(),
        }
        for path in sorted(payloads)
    ]
    manifest = {
        "credentials_included": False,
        "files": file_manifest,
        "format": TRANSFER_FORMAT,
        "format_version": TRANSFER_VERSION,
        "generated_at": timestamp,
        "manifest_scope": "payload files; manifest.json is excluded to avoid a circular hash",
        "redactions": redaction_total,
        "row_count": row_total,
        "workspace": {
            "archived": bool(profile_row.get("archived_at")),
            "id": workspace_id,
            "name": profile_row.get("name"),
            "website": profile_row.get("website"),
        },
    }
    manifest_bytes = _json_bytes(manifest)
    if payload_bytes + len(manifest_bytes) > max_uncompressed_bytes:
        raise CompanyTransferLimitError("The transfer including its manifest exceeds the byte limit")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=False) as archive:
        for path in sorted(payloads):
            _write_zip_entry(archive, path, payloads[path])
        _write_zip_entry(archive, "manifest.json", manifest_bytes)
    return output.getvalue()


__all__ = [
    "CompanyTransferError",
    "CompanyTransferLimitError",
    "build_company_transfer_zip",
    "suggested_transfer_filename",
]
