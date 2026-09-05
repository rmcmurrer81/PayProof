from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
DB_PATH = RUNTIME_DIR / "payproof.sqlite3"
TRACE_QUEUE_PATH = RUNTIME_DIR / "prism_queue.jsonl"
DEMO_INTAKE_DIR = PROJECT_ROOT / "data" / "demo_intake"
USER_INTAKE_DIR = PROJECT_ROOT / "intake"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def money_to_cents(value: str | int | float | Decimal) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_money(cents: int, currency: str = "USD") -> str:
    sign = "-" if cents < 0 else ""
    amount = Decimal(abs(cents)) / 100
    symbol = "$" if currency == "USD" else ("€" if currency == "EUR" else f"{currency} ")
    return f"{sign}{symbol}{amount:,.2f}"


def normalize_merchant(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    aliases = {
        "amzn marketplace": "amazon",
        "amazon marketplace": "amazon",
        "amazon com": "amazon",
        "aws": "amazon web services",
        "staples store": "staples",
        "adobe systems": "adobe",
    }
    return aliases.get(cleaned, cleaned)


def mask_destination(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return f"****{digits[-4:]}" if digits else "Unknown"


def _connect() -> sqlite3.Connection:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, is_demo INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS vendors (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
    category TEXT NOT NULL, city TEXT, lat REAL, lon REAL,
    verified_destination_hash TEXT, verified_destination_masked TEXT,
    verified_contact TEXT, verified_at TEXT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, vendor_id TEXT NOT NULL,
    merchant_raw TEXT NOT NULL, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
    occurred_on TEXT NOT NULL, office TEXT, kind TEXT NOT NULL,
    source_id TEXT NOT NULL, reference TEXT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY(vendor_id) REFERENCES vendors(id)
);
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, vendor_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, invoice_date TEXT NOT NULL,
    destination_hash TEXT, destination_masked TEXT, source_id TEXT NOT NULL,
    status TEXT NOT NULL, FOREIGN KEY(vendor_id) REFERENCES vendors(id)
);
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, vendor_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL, currency TEXT NOT NULL, receipt_date TEXT NOT NULL,
    transaction_id TEXT, source_id TEXT NOT NULL,
    FOREIGN KEY(transaction_id) REFERENCES transactions(id)
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
    severity TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
    entity_id TEXT NOT NULL, evidence_ids TEXT NOT NULL, status TEXT NOT NULL,
    basis TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL,
    finding_id TEXT, action TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, filename TEXT NOT NULL,
    source_hash TEXT NOT NULL, accepted INTEGER NOT NULL, rejected INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_evidence (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, provider TEXT NOT NULL,
    sender TEXT NOT NULL, subject TEXT NOT NULL, received_at TEXT,
    snippet TEXT, source_label TEXT NOT NULL, is_synthetic INTEGER NOT NULL,
    content_hash TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
    department TEXT NOT NULL, office TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expense_reports (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, employee_id TEXT NOT NULL,
    merchant TEXT NOT NULL, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
    spent_on TEXT NOT NULL, category TEXT NOT NULL, purpose TEXT NOT NULL,
    receipt_status TEXT NOT NULL, approval_status TEXT NOT NULL, source_id TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES employees(id)
);
CREATE TABLE IF NOT EXISTS intake_documents (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, filename TEXT NOT NULL,
    document_type TEXT NOT NULL, source_id TEXT NOT NULL, employee_id TEXT,
    status TEXT NOT NULL, is_synthetic INTEGER NOT NULL, content_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
"""


VENDORS = [
    ("northstar", "Northstar Industrial", "Operations", "New York", 40.7128, -74.0060),
    ("amazon", "Amazon Marketplace", "Retail", "Seattle", 47.6062, -122.3321),
    ("adobe", "Adobe", "Software", "San Jose", 37.3382, -121.8863),
    ("staples", "Staples", "Office", "Boston", 42.3601, -71.0589),
    ("coned", "Con Edison", "Utilities", "New York", 40.7306, -73.9352),
    ("fedex", "FedEx", "Shipping", "Memphis", 35.1495, -90.0490),
    ("datadog", "Datadog", "Software", "New York", 40.7580, -73.9855),
    ("stripe", "Stripe", "Payments", "San Francisco", 37.7749, -122.4194),
    ("wework", "WeWork", "Facilities", "New York", 40.7411, -73.9897),
    ("dell", "Dell Technologies", "Hardware", "Austin", 30.2672, -97.7431),
    ("delta", "Delta Air Lines", "Travel", "Atlanta", 33.7490, -84.3880),
    ("wholefoods", "Whole Foods", "Food", "Austin", 30.2699, -97.7428),
    ("twilio", "Twilio", "Communications", "San Francisco", 37.7890, -122.4010),
    ("notion", "Notion", "Software", "San Francisco", 37.7751, -122.4190),
    ("newwave", "NewWave Consulting", "Professional services", None, None, None),
]


def initialize_database(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    with closing(_connect()) as connection:
        connection.executescript(SCHEMA)
        count = connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        if count == 0:
            _seed_demo(connection)
        _seed_email_fixtures(connection)
        _scan_intake_directories(connection)


def _destination_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_demo(connection: sqlite3.Connection) -> None:
    rng = random.Random(240905)
    connection.executemany(
        "INSERT INTO workspaces VALUES (?, ?, ?, ?)",
        [("business", "Meridian Works", "business", 1), ("personal", "Personal Example", "personal", 1)],
    )
    verified_destination = "demo-destination-7284"
    vendor_rows = []
    for key, name, category, city, lat, lon in VENDORS:
        destination = verified_destination if key == "northstar" else f"demo-{key}-{rng.randint(1000,9999)}"
        workspace = "personal" if key in {"wholefoods", "delta", "amazon"} else "business"
        vendor_rows.append((
            key, workspace, name, category, city, lat, lon,
            _destination_hash(destination), mask_destination(destination),
            f"verified-{key}@example.invalid", "2026-08-14",
        ))
    connection.executemany(
        "INSERT INTO vendors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vendor_rows
    )

    offices = ["New York", "Austin", "Chicago"]
    start = date(2026, 4, 1)
    business_vendors = [v for v in VENDORS if v[0] not in {"wholefoods", "delta", "amazon"}]
    transaction_rows = []
    for index in range(105):
        vendor = business_vendors[index % len(business_vendors)]
        amount = rng.randint(2400, 780000)
        if index % 23 == 0:
            amount *= -1
        occurred = start + timedelta(days=(index * 3) % 150)
        merchant = vendor[1]
        tx_kind = "income" if vendor[0] == "stripe" and amount > 0 else ("refund" if amount < 0 else "payment")
        transaction_rows.append((
            f"TX-B-{index+1:03d}", "business", vendor[0], merchant, amount, "USD",
            occurred.isoformat(), offices[index % 3], "refund" if amount < 0 else "payment",
            f"SRC-TX-B-{index+1:03d}", f"REF-{1000+index}",
        ))
        transaction_rows[-1] = transaction_rows[-1][:8] + (tx_kind,) + transaction_rows[-1][9:]
    personal_names = ["AMZN Marketplace", "Amazon.com", "Whole Foods", "Delta Air Lines"]
    personal_keys = ["amazon", "amazon", "wholefoods", "delta"]
    for index in range(28):
        amount = rng.randint(899, 28500)
        if index == 9:
            amount = -4599
        occurred = start + timedelta(days=(index * 5) % 150)
        transaction_rows.append((
            f"TX-P-{index+1:03d}", "personal", personal_keys[index % 4], personal_names[index % 4],
            amount, "USD", occurred.isoformat(), "Personal", "refund" if amount < 0 else "purchase",
            f"SRC-TX-P-{index+1:03d}", f"PREF-{2000+index}",
        ))
    connection.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", transaction_rows)

    invoices = [
        ("INV-1007", "business", "northstar", money_to_cents("48750"), "USD", "2026-09-04", _destination_hash("demo-destination-9142"), "****9142", "SRC-INV-1007", "incoming"),
        ("INV-1006", "business", "northstar", money_to_cents("42100"), "USD", "2026-08-04", _destination_hash(verified_destination), "****7284", "SRC-INV-1006", "paid"),
        ("INV-2041", "business", "dell", money_to_cents("12840"), "USD", "2026-08-28", _destination_hash("demo-dell-1200"), "****1200", "SRC-INV-2041", "incoming"),
        ("INV-2041-COPY", "business", "dell", money_to_cents("12840"), "USD", "2026-08-28", _destination_hash("demo-dell-1200"), "****1200", "SRC-INV-2041-COPY", "incoming"),
        ("INV-3010", "business", "newwave", money_to_cents("9650"), "EUR", "2026-09-01", None, "Unknown", "SRC-INV-3010", "incoming"),
    ]
    connection.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", invoices)

    receipt_rows = []
    for index, tx in enumerate(transaction_rows[:20]):
        if index in {5, 13}:
            continue
        receipt_rows.append((f"REC-{index+1:03d}", tx[1], tx[2], tx[4], tx[5], tx[6], tx[0], f"SRC-REC-{index+1:03d}"))
    receipt_rows.append(("REC-AMB-01", "business", "staples", 15999, "USD", "2026-08-12", None, "SRC-REC-AMB-01"))
    connection.executemany("INSERT INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", receipt_rows)
    recompute_findings(connection)
    connection.commit()


def _seed_email_fixtures(connection: sqlite3.Connection) -> None:
    if connection.execute("SELECT COUNT(*) FROM email_evidence WHERE is_synthetic=1").fetchone()[0]:
        return
    fixtures = [
        ("EMAIL-DEMO-001", "business", "synthetic_email", "billing@northstar.example.invalid", "Northstar invoice INV-1006 confirmed", "2026-08-04T14:20:00Z", "Invoice INV-1006 for $42,100.00 uses the verified destination ending 7284.", "Synthetic email fixture", 1),
        ("EMAIL-DEMO-002", "business", "synthetic_email", "accounts@northstar-payments.example.invalid", "ACTION: Updated remittance details for INV-1007", "2026-09-04T16:45:00Z", "Please send $48,750.00 using the new destination ending 9142 shown on the attached invoice.", "Synthetic email fixture", 1),
        ("EMAIL-DEMO-003", "business", "intake_folder", "ap@dell-demo.example.invalid", "Invoice INV-2041", "2026-08-28T11:05:00Z", "Invoice for $12,840.00; reference INV-2041.", "Synthetic intake-folder fixture", 1),
        ("EMAIL-DEMO-004", "business", "intake_folder", "ap@dell-demo.example.invalid", "Invoice INV-2041 resend", "2026-08-28T11:12:00Z", "Resending invoice for $12,840.00; reference INV-2041.", "Synthetic intake-folder fixture", 1),
        ("EMAIL-DEMO-005", "personal", "synthetic_email", "shipment-tracking@amazon.example.invalid", "Your synthetic Amazon order shipped", "2026-08-28T19:02:00Z", "A synthetic demonstration order associated with TX-P-025 has shipped.", "Synthetic email fixture", 1),
    ]
    rows = [row + (hashlib.sha256("|".join(map(str, row)).encode()).hexdigest(), utc_now()) for row in fixtures]
    connection.executemany("INSERT OR IGNORE INTO email_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    connection.commit()


def _scan_intake_directories(connection: sqlite3.Connection) -> dict[str, Any]:
    """Import structured bookkeeping paperwork from local folders without cloud access."""
    accepted, skipped, errors = 0, 0, []
    for folder, synthetic in ((DEMO_INTAKE_DIR, 1), (USER_INTAKE_DIR, 0)):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                raw = path.read_bytes()
                payload = json.loads(raw.decode("utf-8"))
                required = {"id", "document_type", "employee", "department", "office", "merchant", "amount", "currency", "date", "category", "purpose", "receipt_status", "approval_status"}
                missing = sorted(required - payload.keys())
                if missing:
                    raise ValueError(f"missing fields: {', '.join(missing)}")
                content_hash = hashlib.sha256(raw).hexdigest()
                document_id = str(payload["id"])
                if connection.execute("SELECT 1 FROM intake_documents WHERE content_hash=?", (content_hash,)).fetchone():
                    skipped += 1
                    continue
                employee_id = re.sub(r"[^a-z0-9]+", "-", str(payload["employee"]).lower()).strip("-")
                source_id = f"intake:{path.name}"
                connection.execute("INSERT OR IGNORE INTO employees VALUES (?, 'business', ?, ?, ?)",
                                   (employee_id, payload["employee"], payload["department"], payload["office"]))
                connection.execute("INSERT INTO expense_reports VALUES (?, 'business', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (document_id, employee_id, payload["merchant"], money_to_cents(payload["amount"]),
                                    str(payload["currency"]).upper(), payload["date"], payload["category"], payload["purpose"],
                                    payload["receipt_status"], payload["approval_status"], source_id))
                connection.execute("INSERT INTO intake_documents VALUES (?, 'business', ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (f"DOC-{document_id}", path.name, payload["document_type"], source_id, employee_id,
                                    "processed", synthetic, content_hash, utc_now()))
                accepted += 1
            except (OSError, ValueError, json.JSONDecodeError, ArithmeticError) as exc:
                errors.append({"filename": path.name, "reason": str(exc)})
    connection.commit()
    return {"accepted": accepted, "skipped": skipped, "errors": errors}


def scan_intake_folder() -> dict[str, Any]:
    USER_INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as connection:
        return _scan_intake_directories(connection)


def recompute_findings(connection: sqlite3.Connection | None = None) -> None:
    owns = connection is None
    conn = connection or _connect()
    try:
        conn.execute("DELETE FROM findings WHERE workspace_id IN ('business', 'personal')")
        vendor = conn.execute("SELECT * FROM vendors WHERE id='northstar'").fetchone()
        invoice = conn.execute("SELECT * FROM invoices WHERE id='INV-1007'").fetchone()
        if invoice["destination_hash"] != vendor["verified_destination_hash"]:
            _add_finding(conn, "F-ROUTE-001", "business", "destination_change", "high",
                         "Payment route changed", "Northstar Industrial supplied a destination that differs from the verified baseline.",
                         "INV-1007", ["SRC-INV-1007", "SRC-INV-1006", "vendor:northstar"],
                         f"Verified {vendor['verified_destination_masked']} compared with proposed {invoice['destination_masked']}.")
        _add_finding(conn, "F-DUP-001", "business", "possible_duplicate", "medium",
                     "Possible duplicate invoice", "Two Dell invoices share vendor, amount, currency, and invoice date.",
                     "INV-2041-COPY", ["SRC-INV-2041", "SRC-INV-2041-COPY"], "Exact structured-field match; requires review.")
        _add_finding(conn, "F-NEW-001", "business", "new_vendor", "medium",
                     "Unverified new vendor", "NewWave Consulting lacks a verified payment destination and location.",
                     "INV-3010", ["SRC-INV-3010", "vendor:newwave"], "No verified vendor baseline is available.")
        _add_finding(conn, "F-REC-001", "business", "missing_receipt", "low",
                     "Missing receipt", "A recorded transaction has no linked receipt.",
                     "TX-B-006", ["SRC-TX-B-006"], "No receipt references this transaction ID.")
        conn.commit()
    finally:
        if owns:
            conn.close()


def _add_finding(conn: sqlite3.Connection, finding_id: str, workspace: str, kind: str, severity: str,
                 title: str, summary: str, entity_id: str, evidence: list[str], basis: str) -> None:
    conn.execute(
        "INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (finding_id, workspace, kind, severity, title, summary, entity_id, json.dumps(evidence), "open", basis, utc_now()),
    )


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_dashboard(workspace_id: str = "business") -> dict[str, Any]:
    initialize_database()
    with closing(_connect()) as conn:
        workspaces = _rows(conn, "SELECT * FROM workspaces ORDER BY kind")
        vendors = _rows(conn, "SELECT * FROM vendors WHERE workspace_id=? ORDER BY name", (workspace_id,))
        transactions = _rows(conn, "SELECT * FROM transactions WHERE workspace_id=? ORDER BY occurred_on DESC", (workspace_id,))
        invoices = _rows(conn, "SELECT * FROM invoices WHERE workspace_id=? ORDER BY invoice_date DESC", (workspace_id,))
        receipts = _rows(conn, "SELECT * FROM receipts WHERE workspace_id=? ORDER BY receipt_date DESC", (workspace_id,))
        findings = _rows(conn, "SELECT * FROM findings WHERE workspace_id=? ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END", (workspace_id,))
        audit = _rows(conn, "SELECT * FROM audit WHERE workspace_id=? ORDER BY id DESC LIMIT 20", (workspace_id,))
        emails = _rows(conn, "SELECT * FROM email_evidence WHERE workspace_id=? ORDER BY received_at DESC", (workspace_id,))
        employees = _rows(conn, "SELECT * FROM employees WHERE workspace_id=? ORDER BY name", (workspace_id,))
        expenses = _rows(conn, "SELECT * FROM expense_reports WHERE workspace_id=? ORDER BY spent_on DESC", (workspace_id,))
        documents = _rows(conn, "SELECT * FROM intake_documents WHERE workspace_id=? ORDER BY imported_at DESC", (workspace_id,))
    for finding in findings:
        finding["evidence_ids"] = json.loads(finding["evidence_ids"])
    recorded = sum(tx["amount_cents"] for tx in transactions)
    review_total = sum(invoice["amount_cents"] for invoice in invoices if invoice["status"] == "incoming")
    unmatched = sum(1 for receipt in receipts if not receipt["transaction_id"])
    cash_in = sum(tx["amount_cents"] for tx in transactions if tx["kind"] == "income")
    cash_out = sum(tx["amount_cents"] for tx in transactions if tx["kind"] not in {"income", "refund"} and tx["amount_cents"] > 0)
    employee_spend = sum(expense["amount_cents"] for expense in expenses)
    nodes, edges = _graph(vendors, transactions, invoices, receipts, emails, workspace_id)
    if workspace_id == "business":
        for employee in employees:
            employee_id = f"employee:{employee['id']}"
            nodes.append({"id": employee_id, "label": employee["name"], "type": "employee", "risk": "clear", "size": 9})
            edges.append({"source": "workspace:business", "target": employee_id, "type": "employee", "risk": "clear", "amount": 0})
        for expense in expenses:
            expense_id = f"expense:{expense['id']}"
            risk = "review" if expense["receipt_status"] != "matched" else "clear"
            nodes.append({"id": expense_id, "label": expense["id"], "type": "expense", "risk": risk, "size": 8, "amount": expense["amount_cents"], "currency": expense["currency"]})
            edges.append({"source": f"employee:{expense['employee_id']}", "target": expense_id, "type": "submitted", "risk": risk, "amount": expense["amount_cents"]})
    return {
        "workspace": workspace_id,
        "workspaces": workspaces,
        "metrics": {
            "recorded_spending": recorded,
            "recorded_spending_label": format_money(recorded),
            "transaction_count": len(transactions),
            "review_total": review_total,
            "review_total_label": format_money(review_total),
            "open_findings": sum(1 for finding in findings if finding["status"] == "open"),
            "unmatched_receipts": unmatched,
            "cash_in": cash_in, "cash_in_label": format_money(cash_in),
            "cash_out": cash_out, "cash_out_label": format_money(cash_out),
            "net_cash": cash_in - cash_out, "net_cash_label": format_money(cash_in - cash_out),
            "employee_spend": employee_spend, "employee_spend_label": format_money(employee_spend),
        },
        "vendors": vendors, "transactions": transactions, "invoices": invoices,
        "receipts": receipts, "emails": emails, "employees": employees, "expenses": expenses,
        "documents": documents, "findings": findings, "audit": audit,
        "graph": {"nodes": nodes, "edges": edges},
        "prism": prism_status(),
    }


def _graph(vendors: list[dict[str, Any]], transactions: list[dict[str, Any]], invoices: list[dict[str, Any]],
           receipts: list[dict[str, Any]], emails: list[dict[str, Any]], workspace_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    workspace_label = "Meridian Works" if workspace_id == "business" else "Personal Example"
    nodes = [{"id": f"workspace:{workspace_id}", "label": workspace_label, "type": "workspace", "risk": "clear", "size": 26}]
    edges: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    for tx in transactions:
        totals[tx["vendor_id"]] = totals.get(tx["vendor_id"], 0) + abs(tx["amount_cents"])
    for vendor in vendors:
        risk = "review" if vendor["id"] == "newwave" else "clear"
        nodes.append({"id": f"vendor:{vendor['id']}", "label": vendor["name"], "type": "vendor", "risk": risk,
                      "size": 10 + min(12, int(totals.get(vendor["id"], 0) / 2000000)), "city": vendor["city"], "lat": vendor["lat"], "lon": vendor["lon"]})
        edges.append({"source": f"workspace:{workspace_id}", "target": f"vendor:{vendor['id']}", "type": "history", "risk": risk, "amount": totals.get(vendor["id"], 0)})
    for invoice in invoices:
        risk = "high" if invoice["id"] == "INV-1007" else ("review" if invoice["id"] in {"INV-2041-COPY", "INV-3010"} else "clear")
        node_id = f"invoice:{invoice['id']}"
        nodes.append({"id": node_id, "label": invoice["id"], "type": "invoice", "risk": risk, "size": 9, "amount": invoice["amount_cents"], "currency": invoice["currency"]})
        edges.append({"source": f"vendor:{invoice['vendor_id']}", "target": node_id, "type": "invoice", "risk": risk, "amount": invoice["amount_cents"]})
        if invoice["id"] in {"INV-1006", "INV-1007"}:
            dest = invoice["destination_masked"]
            dest_id = f"destination:{dest}"
            if not any(node["id"] == dest_id for node in nodes):
                nodes.append({"id": dest_id, "label": dest, "type": "destination", "risk": risk, "size": 11})
            edges.append({"source": node_id, "target": dest_id, "type": "proposed" if invoice["status"] == "incoming" else "verified", "risk": risk, "amount": invoice["amount_cents"]})
    for email in emails[:8]:
        email_id = f"email:{email['id']}"
        risk = "high" if email["id"] == "EMAIL-DEMO-002" else "clear"
        nodes.append({"id": email_id, "label": email["subject"][:28], "type": "email", "risk": risk, "size": 7, "source": email["source_label"]})
        searchable = (email["sender"] + email["subject"]).lower()
        linked_vendor = "northstar" if "northstar" in searchable else ("dell" if "dell" in searchable else ("amazon" if "amazon" in searchable else None))
        edges.append({"source": f"vendor:{linked_vendor}" if linked_vendor else f"workspace:{workspace_id}", "target": email_id, "type": "evidence", "risk": risk, "amount": 0})
    return nodes, edges


def get_record(entity_id: str, workspace_id: str) -> dict[str, Any] | None:
    initialize_database()
    prefix, _, raw_id = entity_id.partition(":")
    table = {"vendor": "vendors", "invoice": "invoices", "transaction": "transactions", "receipt": "receipts", "email": "email_evidence", "employee": "employees", "expense": "expense_reports", "document": "intake_documents"}.get(prefix)
    if not table:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND workspace_id=?", (raw_id, workspace_id)).fetchone()
        return dict(row) if row else None


@dataclass
class ChatResult:
    answer: str
    evidence_ids: list[str]
    focus_ids: list[str]
    calculation: dict[str, Any] | None = None


def answer_question(question: str, workspace_id: str = "business", selected_id: str | None = None,
                    filters: dict[str, Any] | None = None) -> ChatResult:
    initialize_database()
    text = question.lower().strip()
    with closing(_connect()) as conn:
        if "what changed" in text or "why" in text and ("flag" in text or "held" in text or selected_id):
            finding = conn.execute("SELECT * FROM findings WHERE workspace_id=? AND kind='destination_change'", (workspace_id,)).fetchone()
            if finding:
                evidence = json.loads(finding["evidence_ids"])
                return ChatResult(
                    "Northstar Industrial’s incoming invoice proposes destination ****9142. The verified baseline is ****7284, last verified on August 14, 2026. This difference is a high-risk anomaly, not proof of fraud. Hold the payment and verify through the previously verified contact.",
                    evidence, ["vendor:northstar", "invoice:INV-1007", "destination:****7284", "destination:****9142"],
                    {"comparison": "****7284 → ****9142", "rule": "DESTINATION_CHANGED"},
                )
        if "duplicate" in text or "charged twice" in text:
            return ChatResult(
                "I found one possible duplicate invoice pair: INV-2041 and INV-2041-COPY. They share vendor, amount ($12,840.00), currency, and invoice date. Review both source records before deciding whether either should be removed.",
                ["SRC-INV-2041", "SRC-INV-2041-COPY"], ["invoice:INV-2041", "invoice:INV-2041-COPY"],
                {"pairs": 1, "basis": ["vendor", "amount", "currency", "invoice_date"]},
            )
        if "amazon" in text:
            rows = conn.execute("SELECT * FROM transactions WHERE workspace_id=?", (workspace_id,)).fetchall()
            matches = [row for row in rows if normalize_merchant(row["merchant_raw"]) == "amazon"]
            total = sum(row["amount_cents"] for row in matches)
            if not matches:
                return ChatResult("I found no Amazon transactions in the active workspace. Try the Personal Example workspace.", [], [])
            latest = max(matches, key=lambda row: row["occurred_on"])
            evidence = [row["source_id"] for row in matches]
            return ChatResult(
                f"I found {len(matches)} Amazon transactions totaling {format_money(total)}. The latest is {latest['id']} on {latest['occurred_on']}. Refunds and credits are included as negative amounts.",
                evidence, [f"vendor:{latest['vendor_id']}"] + [f"transaction:{row['id']}" for row in matches[:8]],
                {"count": len(matches), "total_cents": total, "currency": "USD", "refunds": "included as negative"},
            )
        if "email" in text or ("source" in text and ("show" in text or "what" in text)):
            emails = conn.execute("SELECT * FROM email_evidence WHERE workspace_id=? ORDER BY received_at DESC", (workspace_id,)).fetchall()
            if not emails:
                return ChatResult("I found no email evidence in the active workspace.", [], [])
            synthetic = sum(1 for row in emails if row["is_synthetic"])
            real = len(emails) - synthetic
            labels = sorted({row["source_label"] for row in emails})
            return ChatResult(
                f"I found {len(emails)} email evidence records: {real} imported from a connected mailbox and {synthetic} clearly labeled synthetic fixtures. Sources: {', '.join(labels)}.",
                [row["id"] for row in emails], [f"email:{row['id']}" for row in emails[:8]],
                {"email_count": len(emails), "connected_mailbox": real, "synthetic": synthetic, "sources": labels},
            )
        if "new york" in text and "austin" in text or "office" in text and ("compare" in text or "spend" in text):
            rows = conn.execute("SELECT office, SUM(amount_cents) AS total, COUNT(*) AS count FROM transactions WHERE workspace_id=? GROUP BY office", (workspace_id,)).fetchall()
            values = {row["office"]: {"cents": row["total"], "count": row["count"]} for row in rows}
            ordered = sorted(values.items(), key=lambda item: item[1]["cents"], reverse=True)
            summary = "; ".join(f"{office}: {format_money(value['cents'])} across {value['count']} transactions" for office, value in ordered)
            return ChatResult(f"Office comparison: {summary}.", [f"workspace:{workspace_id}:transactions"], [f"workspace:{workspace_id}"], {"by_office": values})
        if "largest" in text or "over $500" in text or "over 500" in text:
            threshold = 50000 if "500" in text else 0
            rows = conn.execute("SELECT * FROM transactions WHERE workspace_id=? AND amount_cents>? ORDER BY amount_cents DESC LIMIT 5", (workspace_id, threshold)).fetchall()
            if not rows:
                return ChatResult("I found no matching transactions in the active workspace.", [], [])
            listing = "; ".join(f"{row['id']} {row['merchant_raw']} {format_money(row['amount_cents'], row['currency'])}" for row in rows)
            return ChatResult(f"The largest matching transactions are: {listing}.", [row["source_id"] for row in rows], [f"transaction:{row['id']}" for row in rows], {"threshold_cents": threshold, "count_shown": len(rows)})
        if "receipt" in text:
            rows = conn.execute("SELECT * FROM receipts WHERE workspace_id=? AND transaction_id IS NULL", (workspace_id,)).fetchall()
            return ChatResult(
                f"I found {len(rows)} receipt record(s) without a linked transaction. They remain unmatched; PayProof did not invent a match.",
                [row["source_id"] for row in rows], [f"receipt:{row['id']}" for row in rows], {"unmatched_receipts": len(rows)},
            )
        if "employee" in text or "expense report" in text or "staff spend" in text:
            rows = conn.execute("SELECT e.*, p.name FROM expense_reports e JOIN employees p ON p.id=e.employee_id WHERE e.workspace_id=? ORDER BY e.spent_on DESC", (workspace_id,)).fetchall()
            total = sum(row["amount_cents"] for row in rows)
            needs_review = [row for row in rows if row["approval_status"] == "needs_review" or row["receipt_status"] == "missing"]
            if not rows:
                return ChatResult("I found no employee expense paperwork in the active workspace.", [], [])
            return ChatResult(
                f"I found {len(rows)} employee expense reports totaling {format_money(total)}. {len(needs_review)} need review; Priya Shah's $186.45 meal report is missing a receipt.",
                [row["source_id"] for row in rows], [f"expense:{row['id']}" for row in rows],
                {"report_count": len(rows), "total_cents": total, "currency": "USD", "needs_review": len(needs_review)},
            )
        if "money in" in text or "money out" in text or "cash flow" in text:
            rows = conn.execute("SELECT * FROM transactions WHERE workspace_id=?", (workspace_id,)).fetchall()
            incoming = sum(row["amount_cents"] for row in rows if row["kind"] == "income")
            outgoing = sum(row["amount_cents"] for row in rows if row["kind"] not in {"income", "refund"} and row["amount_cents"] > 0)
            return ChatResult(
                f"Recorded money in is {format_money(incoming)} and money out is {format_money(outgoing)}, for net cash of {format_money(incoming-outgoing)}. Refunds are excluded from outflow and no invoice is double-counted as spending.",
                [row["source_id"] for row in rows], [f"workspace:{workspace_id}"],
                {"money_in_cents": incoming, "money_out_cents": outgoing, "net_cash_cents": incoming-outgoing, "currency": "USD"},
            )
        if "what data" in text or "what financial" in text or "do you have" in text:
            counts = {}
            for table in ("vendors", "transactions", "invoices", "receipts", "findings"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=?", (workspace_id,)).fetchone()[0]
            return ChatResult(
                f"The active workspace contains {counts['vendors']} vendors, {counts['transactions']} transactions, {counts['invoices']} invoices, {counts['receipts']} receipts, and {counts['findings']} findings.",
                [f"workspace:{workspace_id}"], [f"workspace:{workspace_id}"], counts,
            )
        if selected_id:
            record = get_record(selected_id, workspace_id)
            if record:
                safe = {key: value for key, value in record.items() if "hash" not in key}
                return ChatResult(f"Here is the loaded evidence for {selected_id}: {json.dumps(safe, default=str)}", [record.get("source_id", selected_id)], [selected_id])
    return ChatResult(
        "I cannot answer that from the loaded evidence yet. Try asking what changed, why a payment was flagged, about duplicate invoices, office spending, receipts, largest payments, or the available financial data.",
        [], [selected_id] if selected_id else [],
    )


def record_action(workspace_id: str, finding_id: str, action: str, reason: str = "") -> dict[str, Any]:
    allowed = {"hold", "manual_review", "verified", "dismissed"}
    if action not in allowed:
        raise ValueError("Unsupported review action")
    if action == "dismissed" and not reason.strip():
        raise ValueError("A reason is required to dismiss a finding")
    initialize_database()
    with closing(_connect()) as conn:
        finding = conn.execute("SELECT * FROM findings WHERE id=? AND workspace_id=?", (finding_id, workspace_id)).fetchone()
        if not finding:
            raise ValueError("Finding not found")
        status = {"hold": "held", "manual_review": "review", "verified": "verified", "dismissed": "dismissed"}[action]
        conn.execute("UPDATE findings SET status=? WHERE id=?", (status, finding_id))
        conn.execute("INSERT INTO audit(workspace_id, finding_id, action, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                     (workspace_id, finding_id, action, reason.strip(), utc_now()))
        conn.commit()
    return {"finding_id": finding_id, "status": status, "simulated": True}


def import_transactions_csv(workspace_id: str, filename: str, content: str, commit: bool = False) -> dict[str, Any]:
    required = {"id", "merchant", "amount", "currency", "date", "office"}
    reader = csv.DictReader(io.StringIO(content))
    headers = set(reader.fieldnames or [])
    missing = sorted(required - headers)
    if missing:
        return {"accepted": [], "rejected": [], "errors": [f"Missing columns: {', '.join(missing)}"], "committed": False}
    accepted, rejected = [], []
    for line_number, row in enumerate(reader, start=2):
        try:
            cents = money_to_cents(row["amount"])
            datetime.strptime(row["date"], "%Y-%m-%d")
            currency = row["currency"].upper().strip()
            if len(currency) != 3:
                raise ValueError("currency must be a three-letter code")
            merchant = row["merchant"].strip()
            if not merchant:
                raise ValueError("merchant is required")
            accepted.append({"line": line_number, "id": row["id"].strip(), "merchant": merchant, "amount_cents": cents,
                             "currency": currency, "date": row["date"], "office": row["office"].strip()})
        except (ValueError, ArithmeticError) as exc:
            rejected.append({"line": line_number, "reason": str(exc)})
    if commit and accepted and not rejected:
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with closing(_connect()) as conn:
            if conn.execute("SELECT 1 FROM imports WHERE source_hash=?", (source_hash,)).fetchone():
                return {"accepted": [], "rejected": [], "errors": ["This exact file was already imported."], "committed": False}
            for item in accepted:
                vendor_id = normalize_merchant(item["merchant"]).replace(" ", "-")[:40]
                vendor = conn.execute("SELECT id FROM vendors WHERE id=? AND workspace_id=?", (vendor_id, workspace_id)).fetchone()
                if not vendor:
                    conn.execute("INSERT INTO vendors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (vendor_id, workspace_id, item["merchant"], "Imported", None, None, None, None, "Unknown", None, None))
                source_id = f"import:{source_hash[:10]}:row:{item['line']}"
                conn.execute("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (item["id"], workspace_id, vendor_id, item["merchant"], item["amount_cents"], item["currency"], item["date"], item["office"], "imported", source_id, None))
            conn.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (str(uuid.uuid4()), workspace_id, filename, source_hash, len(accepted), len(rejected), utc_now()))
            conn.commit()
    return {"accepted": accepted, "rejected": rejected, "errors": [], "committed": bool(commit and accepted and not rejected)}


def import_gmail_metadata(messages: list[dict[str, Any]], workspace_id: str = "personal") -> dict[str, int]:
    """Store minimal Gmail metadata and snippets locally; never stores attachments or full bodies."""
    accepted = skipped = 0
    initialize_database()
    with closing(_connect()) as conn:
        for message in messages:
            message_id = str(message.get("id", "")).strip()
            if not message_id:
                skipped += 1
                continue
            sender = str(message.get("sender", "Unknown sender"))[:500]
            subject = str(message.get("subject", "(no subject)"))[:500]
            received_at = str(message.get("received_at", ""))[:100]
            snippet = re.sub(r"\s+", " ", str(message.get("snippet", ""))).strip()[:800]
            content_hash = hashlib.sha256(f"{message_id}|{sender}|{subject}|{received_at}|{snippet}".encode("utf-8")).hexdigest()
            row_id = f"GMAIL-{message_id}"
            result = conn.execute(
                "INSERT OR IGNORE INTO email_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, workspace_id, "gmail", sender, subject, received_at, snippet, "Gmail · read-only metadata", 0, content_hash, utc_now()),
            )
            accepted += result.rowcount
            skipped += 1 - result.rowcount
        conn.commit()
    return {"accepted": accepted, "skipped": skipped}


def list_import_sources(workspace_id: str) -> list[dict[str, Any]]:
    initialize_database()
    with closing(_connect()) as conn:
        imports = _rows(conn, "SELECT id, filename, accepted, rejected, created_at FROM imports WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,))
        gmail_count = conn.execute("SELECT COUNT(*) FROM email_evidence WHERE workspace_id=? AND provider='gmail'", (workspace_id,)).fetchone()[0]
    sources = [{**item, "kind": "image" if Path(item["filename"]).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "csv",
                "label": item["filename"], "record_count": item["accepted"]} for item in imports]
    if gmail_count:
        sources.insert(0, {"id": "gmail", "kind": "gmail", "label": "Gmail · read-only metadata", "record_count": gmail_count})
    return sources


def remove_source(workspace_id: str, source_id: str) -> dict[str, Any]:
    initialize_database()
    with closing(_connect()) as conn:
        if source_id == "gmail":
            count = conn.execute("DELETE FROM email_evidence WHERE workspace_id=? AND provider='gmail'", (workspace_id,)).rowcount
            conn.commit()
            return {"removed": count, "kind": "gmail"}
        imported = conn.execute("SELECT * FROM imports WHERE id=? AND workspace_id=?", (source_id, workspace_id)).fetchone()
        if not imported:
            raise ValueError("Imported source not found")
        prefix = f"import:{imported['source_hash'][:10]}:row:"
        count = conn.execute("DELETE FROM transactions WHERE workspace_id=? AND source_id LIKE ?", (workspace_id, f"{prefix}%")).rowcount
        count += conn.execute("DELETE FROM receipts WHERE workspace_id=? AND source_id LIKE ?", (workspace_id, f"{prefix}%")).rowcount
        conn.execute("DELETE FROM imports WHERE id=?", (source_id,))
        conn.commit()
        return {"removed": count, "kind": "csv"}


def import_ocr_receipt(workspace_id: str, filename: str, source_hash: str, merchant: str,
                       amount: str, currency: str, receipt_date: str) -> dict[str, Any]:
    merchant = merchant.strip()
    if not merchant:
        raise ValueError("Merchant is required")
    cents = money_to_cents(amount)
    datetime.strptime(receipt_date, "%Y-%m-%d")
    currency = currency.strip().upper()
    if len(currency) != 3:
        raise ValueError("Currency must be a three-letter code")
    vendor_id = normalize_merchant(merchant).replace(" ", "-")[:40] or "ocr-merchant"
    receipt_id = f"OCR-{source_hash[:10].upper()}"
    source_id = f"import:{source_hash[:10]}:row:1"
    initialize_database()
    with closing(_connect()) as conn:
        if conn.execute("SELECT 1 FROM imports WHERE source_hash=?", (source_hash,)).fetchone():
            raise ValueError("This exact image was already imported")
        if not conn.execute("SELECT 1 FROM vendors WHERE id=? AND workspace_id=?", (vendor_id, workspace_id)).fetchone():
            conn.execute("INSERT INTO vendors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (vendor_id, workspace_id, merchant, "OCR receipt", None, None, None, None, "Unknown", None, None))
        conn.execute("INSERT INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (receipt_id, workspace_id, vendor_id, cents, currency, receipt_date, None, source_id))
        conn.execute("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid.uuid4()), workspace_id, filename, source_hash, 1, 0, utc_now()))
        conn.commit()
    return {"id": receipt_id, "source_id": source_id, "merchant": merchant, "amount_cents": cents,
            "currency": currency, "receipt_date": receipt_date}


def prism_status() -> dict[str, Any]:
    configured = bool(os.getenv("PRISMTRACE_PROJECT_ID") and os.getenv("PRISMTRACE_API_KEY"))
    queued = 0
    if TRACE_QUEUE_PATH.exists():
        queued = sum(1 for line in TRACE_QUEUE_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    return {"state": "configured" if configured else "not_configured", "queued": queued,
            "host": os.getenv("PRISMTRACE_HOST", "https://prism.blockconvey.com")}


def send_prism_trace(question: str, result: ChatResult, session_id: str, latency_ms: int,
                     workspace_id: str) -> dict[str, Any]:
    project_id = os.getenv("PRISMTRACE_PROJECT_ID")
    api_key = os.getenv("PRISMTRACE_API_KEY")
    host = os.getenv("PRISMTRACE_HOST", "https://prism.blockconvey.com").rstrip("/")
    trace_id = str(uuid.uuid4())
    payload = {
        "project_id": project_id, "model": "payproof-deterministic-fallback",
        "input_messages": [{"role": "user", "content": question}], "output_message": result.answer,
        "latency_ms": latency_ms, "session_id": session_id, "trace_id": trace_id,
        "agent_id": "payproof-atlas", "agent_name": "Ask PayProof",
        "metadata": {"workspace": workspace_id, "evidence_ids": result.evidence_ids,
                     "engine": "deterministic-fallback", "synthetic_demo": True},
    }
    if not project_id or not api_key:
        return {"state": "not_configured", "trace_id": trace_id}
    request = urllib.request.Request(f"{host}/api/traces", data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "X-PRISMtrace-Key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"state": "accepted", "trace_id": body.get("id", trace_id)}
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with TRACE_QUEUE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        return {"state": "queued", "trace_id": trace_id, "error": type(exc).__name__}


def trace_chat_async(question: str, result: ChatResult, session_id: str, latency_ms: int, workspace_id: str) -> None:
    threading.Thread(target=send_prism_trace, args=(question, result, session_id, latency_ms, workspace_id), daemon=True).start()
