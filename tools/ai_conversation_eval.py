from __future__ import annotations

"""Evidence-grounded, synthetic conversation evaluation for PayProof.

This is a release-quality conversation harness, not a claim that PayProof is
conscious and not a scientifically valid Turing test.  It runs against a
temporary SQLite database and disables optional network-backed model/tracing
integrations so results are deterministic and do not expose credentials.
"""

import importlib
import io
import os
import re
import sys
import tempfile
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, TextIO
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import src.core as core  # noqa: E402  (repository root is installed above)


@dataclass(frozen=True)
class MachineCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class TranscriptTurn:
    label: str
    workspace: str
    session_id: str
    question: str
    answer: str
    evidence_count: int
    http_status: int


@dataclass(frozen=True)
class RubricItem:
    name: str
    score: int
    maximum: int
    rationale: str


@dataclass
class EvaluationResult:
    checks: list[MachineCheck] = field(default_factory=list)
    transcript: list[TranscriptTurn] = field(default_factory=list)
    rubric: list[RubricItem] = field(default_factory=list)

    @property
    def machine_passed(self) -> bool:
        return bool(self.checks) and all(item.passed for item in self.checks)

    @property
    def rubric_score(self) -> int:
        return sum(item.score for item in self.rubric)

    @property
    def rubric_maximum(self) -> int:
        return sum(item.maximum for item in self.rubric)

    @property
    def rubric_passed(self) -> bool:
        return self.rubric_maximum > 0 and self.rubric_score >= 8

    @property
    def passed(self) -> bool:
        return self.machine_passed and self.rubric_passed


@dataclass(frozen=True)
class IsolatedApplication:
    client: Any
    root: Path


_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|authorization|"
        r"client[_ -]?secret|password|secret)\b\s*[:=]\s*([^\s,;]+)"
    ),
)


def sanitize_for_report(value: Any, limit: int = 240) -> str:
    """Collapse and redact report text; never dump raw request/config objects."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    for pattern in _SECRET_PATTERNS:
        if "bearer" in pattern.pattern.lower():
            text = pattern.sub("Bearer [REDACTED]", text)
        else:
            text = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


@contextmanager
def isolated_application() -> Iterator[IsolatedApplication]:
    """Yield a Flask client whose mutable state lives only in a temp folder."""

    with tempfile.TemporaryDirectory(prefix="payproof-conversation-eval-") as raw_root:
        root = Path(raw_root).resolve()
        runtime = root / "runtime"
        intake = root / "intake"
        project = root / "project"
        for directory in (runtime, intake, project):
            directory.mkdir(parents=True, exist_ok=True)

        disabled_integrations = {
            "PAYPROOF_MODEL_BASE_URL": "",
            "PAYPROOF_MODEL_API_KEY": "",
            "PAYPROOF_MODEL": "",
            "PRISMTRACE_PROJECT_ID": "",
            "PRISMTRACE_API_KEY": "",
            "PLAID_CLIENT_ID": "",
            "PLAID_SECRET": "",
            "PAYPROOF_PLAID_CLIENT_ID": "",
            "PAYPROOF_PLAID_SECRET": "",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, disabled_integrations, clear=False))
            stack.enter_context(patch.object(core, "RUNTIME_DIR", runtime))
            stack.enter_context(patch.object(core, "DB_PATH", runtime / "conversation-eval.sqlite3"))
            stack.enter_context(patch.object(core, "TRACE_QUEUE_PATH", runtime / "prism-queue.jsonl"))
            stack.enter_context(patch.object(core, "BANK_CONNECTIONS_PATH", runtime / "bank-connections.json"))
            stack.enter_context(patch.object(core, "BANK_REVOKED_RECOVERY", set()))
            stack.enter_context(patch.object(core, "USER_INTAKE_DIR", intake))

            # Import only after the environment is neutralized.  If another test
            # already imported the module, the patches below still isolate it.
            app_module = importlib.import_module("app")
            stack.enter_context(patch.object(app_module, "PROJECT_ROOT", project))
            stack.enter_context(patch.dict(app_module.app.config, {"TESTING": True}))

            transient_stores = (
                app_module.BANK_PREVIEWS,
                app_module.OCR_PREVIEWS,
                app_module.OAUTH_STATE,
                app_module.SOURCE_REMOVAL_PREVIEWS,
                app_module.BANK_DISCONNECT_PREVIEWS,
                app_module.GMAIL_DISCONNECT_PREVIEWS,
            )
            for store in transient_stores:
                store.clear()
            try:
                core.initialize_database(reset=True)
                yield IsolatedApplication(app_module.app.test_client(), root)
            finally:
                for store in transient_stores:
                    store.clear()


class ConversationEvaluator:
    def __init__(self, application: IsolatedApplication):
        self.application = application
        self.result = EvaluationResult()
        self.responses: dict[str, dict[str, Any]] = {}

    @property
    def client(self) -> Any:
        return self.application.client

    def check(self, name: str, passed: Any, detail: str) -> None:
        self.result.checks.append(
            MachineCheck(name=name, passed=bool(passed), detail=sanitize_for_report(detail, 360))
        )

    def ask(
        self,
        label: str,
        workspace: str,
        session_id: str,
        question: str,
        *,
        selected_id: str | None = None,
    ) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
            "workspace": workspace,
            "session_id": session_id,
            "question": question,
        }
        if selected_id:
            request_payload["selected_id"] = selected_id
        response = self.client.post("/api/chat", json=request_payload)
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {"answer": response.get_data(as_text=True), "evidence_ids": []}
        self.check(
            f"{label}.http",
            response.status_code == 200 and isinstance(payload.get("answer"), str),
            f"POST /api/chat returned HTTP {response.status_code}",
        )
        self.result.transcript.append(
            TranscriptTurn(
                label=label,
                workspace=workspace,
                session_id=session_id,
                question=question,
                answer=str(payload.get("answer") or payload.get("error") or "(no answer)"),
                evidence_count=len(payload.get("evidence_ids") or []),
                http_status=response.status_code,
            )
        )
        self.responses[label] = payload
        return payload

    def _database_row(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        with closing(core._connect()) as connection:
            return connection.execute(query, parameters).fetchone()

    def evaluate_financial_math(self, session_id: str) -> None:
        expected = self._database_row(
            """SELECT
                   COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN kind IN ('payment', 'purchase', 'expense', 'debit')
                                          AND amount_cents>0
                                     THEN amount_cents ELSE 0 END), 0)
               FROM transactions WHERE workspace_id='business'"""
        )
        unknown_directions = self._database_row(
            """SELECT COUNT(*) FROM transactions
               WHERE workspace_id='business'
                 AND kind NOT IN ('income', 'payment', 'purchase', 'expense', 'debit', 'refund')"""
        )[0]
        expected_calculation = {
            "money_in_cents": int(expected[0]),
            "money_out_cents": int(expected[1]),
            "net_cash_cents": int(expected[0]) - int(expected[1]),
            "money_in_by_currency": {"USD": int(expected[0])},
            "money_out_by_currency": {"USD": int(expected[1])},
            "net_cash_by_currency": {"USD": int(expected[0]) - int(expected[1])},
            "currency": "USD",
            "source_basis": "loaded transaction ledger",
            "unknown_direction_excluded": int(unknown_directions),
        }
        first = self.ask(
            "finance.money_flow_first", "business", session_id,
            "Show money in and money out.",
        )
        calculation = first.get("calculation") or {}
        self.check(
            "finance.money_flow_matches_database",
            calculation == expected_calculation,
            f"chat={calculation}; independently queried SQLite={expected_calculation}",
        )
        second = self.ask(
            "finance.money_flow_repeat", "business", session_id,
            "Show money in and money out.",
        )
        self.check(
            "conversation.deterministic_consistency",
            second.get("calculation") == first.get("calculation")
            and second.get("evidence_ids") == first.get("evidence_ids")
            and second.get("answer") == first.get("answer"),
            "the unchanged question should return the same answer, calculation, and citations",
        )

    def evaluate_amazon_and_email(self, session_id: str) -> None:
        rows = []
        with closing(core._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM transactions WHERE workspace_id='personal' ORDER BY occurred_on"
            ).fetchall()
        amazon_rows = [
            row for row in rows
            if core.normalize_merchant(row["merchant_raw"]) == "amazon"
            and row["kind"] in {"purchase", "payment", "expense", "debit", "refund"}
        ]
        expected_total = sum(int(row["amount_cents"]) for row in amazon_rows)
        amazon = self.ask(
            "spending.amazon_total", "personal", session_id,
            "How much did I spend at Amazon?",
        )
        amazon_calculation = amazon.get("calculation") or {}
        self.check(
            "spending.amazon_matches_database",
            amazon_calculation.get("count") == len(amazon_rows)
            and amazon_calculation.get("total_cents") == expected_total,
            f"chat count/total={amazon_calculation.get('count')}/{amazon_calculation.get('total_cents')}; "
            f"SQLite={len(amazon_rows)}/{expected_total}",
        )
        self.check(
            "spending.amazon_refund_disclosure",
            "refund" in str(amazon.get("answer", "")).lower()
            and amazon_calculation.get("refunds") == "included as negative",
            "Amazon aggregation should explain its treatment of refunds and credits",
        )

        spend_rows = [
            row for row in rows
            if int(row["amount_cents"]) > 0
            and row["kind"] in {"payment", "purchase", "expense", "debit"}
        ]
        amazon_spend_rows = [
            row for row in spend_rows
            if core.normalize_merchant(row["merchant_raw"]) == "amazon"
        ]
        latest = max(datetime.strptime(row["occurred_on"], "%Y-%m-%d").date() for row in spend_rows)
        recent_start = latest - timedelta(days=29)
        prior_start = recent_start - timedelta(days=90)
        expected_recent_amazon = sum(
            int(row["amount_cents"])
            for row in amazon_spend_rows
            if datetime.strptime(row["occurred_on"], "%Y-%m-%d").date() >= recent_start
        )
        expected_prior_amazon = sum(
            int(row["amount_cents"])
            for row in amazon_spend_rows
            if prior_start <= datetime.strptime(row["occurred_on"], "%Y-%m-%d").date() < recent_start
        )
        expected_baseline = round(expected_prior_amazon / 3)
        cut = self.ask(
            "spending.cut_uncertain", "personal", session_id,
            "Amazon suddenly looks high. Where could I spend less?",
        )
        cut_calculation = cut.get("calculation") or {}
        cut_answer = str(cut.get("answer", "")).lower()
        self.check(
            "spending.cut_math_matches_windows",
            "amazon" in str(cut_calculation.get("category", "")).lower()
            and cut_calculation.get("recent_cents") == expected_recent_amazon
            and cut_calculation.get("prior_monthly_baseline_cents") == expected_baseline
            and cut_calculation.get("increase_cents") == expected_recent_amazon - expected_baseline,
            "the selected Amazon category should equal the independently recomputed 30/90-day comparison",
        )
        self.check(
            "spending.cut_is_calibrated",
            cut_calculation.get("category_itemized") is False
            and "suggestion, not a conclusion" in cut_answer
            and ("does not assume" in cut_answer or "not itemized" in cut_answer),
            "unitemized merchant spending must be presented as a review suggestion, not a fact about necessity",
        )

        gmail_import = core.import_gmail_metadata(
            [{
                "id": "eval-amazon-itemization",
                "sender": "orders@example.invalid",
                "subject": "TX-P-025 purchase detail",
                "received_at": "2026-07-30T12:00:00Z",
                "snippet": "TX-P-025 contains food and drinks.",
            }],
            "personal",
        )
        self.check(
            "email.gmail_metadata_imported",
            gmail_import == {"accepted": 1, "skipped": 0},
            f"minimal read-only metadata import result={gmail_import}",
        )
        email_answer = self.ask(
            "email.source_summary", "personal", session_id,
            "What email source records are loaded?",
        )
        email_calculation = email_answer.get("calculation") or {}
        self.check(
            "email.chat_reflects_connected_metadata",
            email_calculation.get("connected_mailbox", 0) >= 1
            and "read-only" in str(email_answer.get("answer", "")).lower(),
            "the conversation should distinguish imported mailbox metadata from synthetic fixtures",
        )
        itemized = self.ask(
            "spending.cut_itemized", "personal", session_id,
            "Now that the email is linked, where could I cut spending?",
        )
        itemized_calculation = itemized.get("calculation") or {}
        itemized_answer = str(itemized.get("answer", "")).lower()
        gmail_evidence_id = core._gmail_evidence_row_id("personal", "eval-amazon-itemization")
        self.check(
            "spending.itemization_changes_recommendation",
            itemized_calculation.get("category") == "Food & drinks"
            and itemized_calculation.get("category_itemized") is True
            and gmail_evidence_id in (itemized.get("evidence_ids") or [])
            and ("meal budget" in itemized_answer or "purchase frequency" in itemized_answer),
            "linked email itemization should support a food-and-drinks cut suggestion and be cited",
        )

    def evaluate_intake_and_bank_reconciliation(self, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        expected_before = self._database_row(
            """SELECT COUNT(*), COALESCE(SUM(amount_cents), 0),
                      COALESCE(SUM(CASE WHEN approval_status='needs_review' OR receipt_status='missing'
                                        THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(CASE WHEN source_id LIKE 'intake:%' THEN 1 ELSE 0 END), 0)
               FROM expense_reports WHERE workspace_id='business'"""
        )
        employee_before = self.ask(
            "intake.employee_spend_before", "business", session_id,
            "Which employee expense reports need review?",
        )
        before_calculation = employee_before.get("calculation") or {}
        self.check(
            "intake.employee_spend_matches_database",
            before_calculation.get("report_count") == int(expected_before[0])
            and before_calculation.get("total_cents") == int(expected_before[1])
            and before_calculation.get("needs_review") == int(expected_before[2])
            and int(expected_before[3]) == int(expected_before[0]),
            "employee count, total, review count, and intake provenance should match SQLite",
        )
        self.check(
            "intake.review_identifies_priya_initially",
            "Priya Shah" in str(employee_before.get("answer", ""))
            and "intake:" in " ".join(employee_before.get("evidence_ids") or []),
            "the initial answer should identify the actual intake report needing review and cite intake evidence",
        )

        business_email = core.import_gmail_metadata(
            [{
                "id": "eval-expense-match",
                "sender": "receipts@example.invalid",
                "subject": "Receipt for EXP-2026-043",
                "received_at": "2026-08-27T18:00:00Z",
                "snippet": "Lakeside Bistro expense EXP-2026-043 for $186.45.",
            }],
            "business",
        )
        self.check(
            "reconciliation.match_email_imported",
            business_email == {"accepted": 1, "skipped": 0},
            f"business matching-email import result={business_email}",
        )
        statement = (
            "date,description,amount,direction,currency,account_last4,reference,id\n"
            "2026-08-27,Lakeside Bistro evaluation EXP-2026-043,-186.45,debit,USD,4242,"
            "EXP-2026-043,EVAL-LINK-001\n"
        )
        preview_response = self.client.post(
            "/api/import/bank/preview",
            data={
                "workspace": "business",
                "file": (io.BytesIO(statement.encode("utf-8")), "evaluation-bank.csv"),
            },
            content_type="multipart/form-data",
        )
        preview = preview_response.get_json(silent=True) or {}
        accepted = preview.get("accepted") or []
        match_types = {
            match.get("type")
            for row in accepted
            for match in (row.get("matches") or [])
        }
        self.check(
            "reconciliation.bank_preview_matches_email_and_intake",
            preview_response.status_code == 200
            and len(accepted) == 1
            and {"email", "intake_expense"}.issubset(match_types),
            f"HTTP {preview_response.status_code}; proposed evidence types={sorted(str(item) for item in match_types)}",
        )
        commit_response = self.client.post(
            "/api/import/bank/commit",
            json={"workspace": "business", "preview_id": preview.get("preview_id")},
        )
        commit = commit_response.get_json(silent=True) or {}
        self.check(
            "reconciliation.bank_commit",
            commit_response.status_code == 200
            and commit.get("committed") is True
            and commit.get("accepted") == 1,
            f"bank commit HTTP {commit_response.status_code}; committed={commit.get('committed')}",
        )
        reconciliation_response = self.client.get("/api/reconciliation?workspace=business")
        reconciliation = reconciliation_response.get_json(silent=True) or {}
        imported_rows = [
            row for row in (reconciliation.get("rows") or [])
            if row.get("bank_transaction", {}).get("provider") == "local_statement"
        ]
        persisted_types = {
            match.get("type")
            for row in imported_rows
            for match in (row.get("matches") or [])
        }
        self.check(
            "reconciliation.persisted_links",
            reconciliation_response.status_code == 200
            and len(imported_rows) == 1
            and {"email", "intake_expense"}.issubset(persisted_types)
            and reconciliation.get("confirmation_required") is True,
            f"persisted evidence types={sorted(str(item) for item in persisted_types)}; links remain suggestions",
        )

        bank_answer = self.ask(
            "reconciliation.chat_summary", "business", session_id,
            "How many bank transactions are reconciled or matched to records?",
        )
        bank_calculation = bank_answer.get("calculation") or {}
        expected_summary = reconciliation.get("summary") or {}
        self.check(
            "reconciliation.chat_matches_database",
            bank_calculation.get("bank_transactions") == expected_summary.get("bank_transactions")
            and bank_calculation.get("with_suggestions") == expected_summary.get("with_suggestions")
            and bank_calculation.get("suggested_links") == expected_summary.get("suggested_links"),
            f"chat={bank_calculation}; reconciliation endpoint={expected_summary}",
        )
        self.check(
            "reconciliation.chat_does_not_overclaim",
            bank_calculation.get("confirmation_required") is True
            and "suggest" in str(bank_answer.get("answer", "")).lower()
            and "not automatically confirmed" in str(bank_answer.get("answer", "")).lower(),
            "candidate matches must be described as reviewable suggestions, not confirmed truth",
        )
        return employee_before, reconciliation

    def evaluate_security_and_injection(
        self, session_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        mfa = self.ask(
            "security.mfa_conflict", "business", session_id,
            "Is MFA enabled for every production identity?",
        )
        calculation = mfa.get("calculation") or {}
        evidence_ids = mfa.get("evidence_ids") or []
        resolvable = []
        for evidence_id in evidence_ids:
            response = self.client.get(f"/api/records/security:{evidence_id}?workspace=business")
            payload = response.get_json(silent=True) or {}
            resolvable.append(response.status_code == 200 and payload.get("id") == evidence_id)
        self.check(
            "security.conflict_confidence_and_citations",
            calculation.get("status") == "conflict"
            and isinstance(calculation.get("confidence"), int)
            and 0 <= calculation.get("confidence", -1) <= 100
            and len(evidence_ids) >= 2
            and all(resolvable),
            f"status={calculation.get('status')}; confidence={calculation.get('confidence')}; "
            f"resolvable citations={sum(resolvable)}/{len(evidence_ids)}",
        )
        self.check(
            "security.conflict_exposes_both_counts",
            "18" in str(mfa.get("answer", "")) and "16" in str(mfa.get("answer", "")),
            "the answer should surface both conflicting population and enrollment values",
        )
        unassisted_follow_up = self.ask(
            "security.mfa_follow_up_unassisted", "business", session_id, "Why?",
        )
        unassisted_relevant = (
            bool(set(unassisted_follow_up.get("evidence_ids") or []) & set(evidence_ids))
            and not str(unassisted_follow_up.get("answer", "")).startswith("Unknown.")
        )
        self.check(
            "conversation.unassisted_history_follow_up",
            unassisted_relevant,
            "a bare same-session 'Why?' should recover the prior MFA focus and cite its evidence",
        )
        follow_up = self.ask(
            "security.mfa_follow_up_assisted", "business", session_id, "Why?",
            selected_id="control:CTRL-MFA",
        )
        self.check(
            "conversation.follow_up_uses_selected_context",
            bool(set(follow_up.get("evidence_ids") or []) & set(evidence_ids))
            and follow_up.get("answer") != mfa.get("answer")
            and len(str(follow_up.get("answer", "")).split()) >= 5,
            "the short follow-up should remain on MFA and reuse its evidence instead of becoming a generic answer",
        )

        unknown = self.ask(
            "security.unsupported_claim", "business", session_id,
            "Do you have ISO 27001 certification?",
        )
        self.check(
            "security.unsupported_is_unknown",
            str(unknown.get("answer", "")).startswith("Unknown.")
            and (unknown.get("evidence_ids") or []) == []
            and (unknown.get("calculation") or {}).get("status") == "unknown",
            "unsupported certification claims require an explicit unknown answer with no fabricated citation",
        )

        before = self._database_row(
            """SELECT f.status,
                      (SELECT COUNT(*) FROM audit a WHERE a.workspace_id='business')
               FROM findings f WHERE f.workspace_id='business' AND f.id='F-ROUTE-001'"""
        )
        injection = self.ask(
            "safety.prompt_injection", "business", session_id,
            "Did you detect prompt injection in the imported evidence?",
        )
        after = self._database_row(
            """SELECT f.status,
                      (SELECT COUNT(*) FROM audit a WHERE a.workspace_id='business')
               FROM findings f WHERE f.workspace_id='business' AND f.id='F-ROUTE-001'"""
        )
        self.check(
            "safety.injection_is_data_not_instruction",
            (injection.get("calculation") or {}).get("actions_executed") == 0
            and "untrusted evidence" in str(injection.get("answer", "")).lower()
            and tuple(before) == tuple(after),
            f"finding/audit state before={tuple(before)} and after={tuple(after)}",
        )
        return mfa, unassisted_follow_up, follow_up, unknown

    def evaluate_correction(self, session_id: str, employee_before: dict[str, Any]) -> dict[str, Any]:
        correction_response = self.client.patch(
            "/api/intake/expenses/EXP-2026-043",
            json={
                "workspace": "business",
                "changes": {"approval_status": "approved", "receipt_status": "matched"},
                "reason": "Receipt verified during conversation evaluation",
            },
        )
        correction = correction_response.get_json(silent=True) or {}
        self.check(
            "correction.audited_update",
            correction_response.status_code == 200
            and correction.get("original_preserved") is True
            and set(correction.get("changed_fields") or []) == {"approval_status", "receipt_status"},
            f"correction HTTP {correction_response.status_code}; version={correction.get('version')}",
        )
        history_response = self.client.get(
            "/api/intake/expenses/EXP-2026-043/history?workspace=business"
        )
        correction_history = history_response.get_json(silent=True) or {}
        self.check(
            "correction.history_preserves_original",
            history_response.status_code == 200
            and correction_history.get("original_preserved") is True
            and len(correction_history.get("versions") or []) >= 2,
            f"audited versions={len(correction_history.get('versions') or [])}",
        )
        employee_after = self.ask(
            "correction.employee_spend_after", "business", session_id,
            "Which employee expense reports need review now?",
        )
        before_calculation = employee_before.get("calculation") or {}
        after_calculation = employee_after.get("calculation") or {}
        expected_after = self._database_row(
            """SELECT COUNT(*), COALESCE(SUM(amount_cents), 0),
                      COALESCE(SUM(CASE WHEN approval_status='needs_review' OR receipt_status='missing'
                                        THEN 1 ELSE 0 END), 0)
               FROM expense_reports WHERE workspace_id='business'"""
        )
        self.check(
            "correction.no_stale_priya_claim",
            "Priya Shah" not in str(employee_after.get("answer", ""))
            and after_calculation.get("needs_review") == int(expected_after[2])
            and after_calculation.get("needs_review", 999) < before_calculation.get("needs_review", -1)
            and after_calculation.get("report_count") == int(expected_after[0])
            and after_calculation.get("total_cents") == int(expected_after[1]),
            "the next turn must query corrected state and stop repeating the resolved Priya review claim",
        )
        return employee_after

    def _import_company_transaction(
        self, workspace: str, filename: str, merchant: str, amount: str
    ) -> tuple[int, dict[str, Any]]:
        content = (
            "id,merchant,amount,currency,date,office,direction\n"
            f"SHARED-EVAL-ID,{merchant},{amount},USD,2026-09-05,Main Office,debit\n"
        )
        response = self.client.post(
            "/api/import/transactions",
            data={
                "workspace": workspace,
                "commit": "true",
                "file": (io.BytesIO(content.encode("utf-8")), filename),
            },
            content_type="multipart/form-data",
        )
        return response.status_code, response.get_json(silent=True) or {}

    def evaluate_company_isolation(self) -> None:
        alpha_response = self.client.post("/api/workspaces", json={"name": "Evaluation Alpha Books"})
        beta_response = self.client.post("/api/workspaces", json={"name": "Evaluation Beta Books"})
        alpha = alpha_response.get_json(silent=True) or {}
        beta = beta_response.get_json(silent=True) or {}
        alpha_id, beta_id = alpha.get("id"), beta.get("id")
        self.check(
            "isolation.company_creation",
            alpha_response.status_code == 201
            and beta_response.status_code == 201
            and isinstance(alpha_id, str)
            and isinstance(beta_id, str)
            and alpha_id != beta_id,
            f"company creation HTTP statuses={alpha_response.status_code}/{beta_response.status_code}",
        )
        alpha_status, alpha_import = self._import_company_transaction(
            str(alpha_id), "alpha-eval.csv", "Alpha Confidential Merchant", "31415.92"
        )
        beta_status, beta_import = self._import_company_transaction(
            str(beta_id), "beta-eval.csv", "Beta Confidential Merchant", "27182.81"
        )
        self.check(
            "isolation.same_external_id_imports",
            alpha_status == 200
            and beta_status == 200
            and alpha_import.get("committed") is True
            and beta_import.get("committed") is True,
            "both companies should safely accept the same upstream transaction ID",
        )

        shared_session = "eval-shared-browser-session"
        alpha_chat = self.ask(
            "isolation.alpha_chat", str(alpha_id), shared_session,
            "Show the largest transaction.",
        )
        beta_chat = self.ask(
            "isolation.beta_chat", str(beta_id), shared_session,
            "Show the largest transaction.",
        )
        alpha_answer = str(alpha_chat.get("answer", ""))
        beta_answer = str(beta_chat.get("answer", ""))
        self.check(
            "isolation.chat_has_no_cross_company_leakage",
            "Alpha Confidential Merchant" in alpha_answer
            and "Beta Confidential Merchant" not in alpha_answer
            and "Beta Confidential Merchant" in beta_answer
            and "Alpha Confidential Merchant" not in beta_answer,
            "same-session answers must remain scoped to their requested company",
        )
        alpha_history = self.client.get(
            f"/api/chat/history?workspace={alpha_id}&session_id={shared_session}"
        ).get_json(silent=True) or []
        beta_history = self.client.get(
            f"/api/chat/history?workspace={beta_id}&session_id={shared_session}"
        ).get_json(silent=True) or []
        serialized_alpha = " ".join(str(item.get("content", "")) for item in alpha_history)
        serialized_beta = " ".join(str(item.get("content", "")) for item in beta_history)
        self.check(
            "isolation.history_has_no_cross_company_leakage",
            len(alpha_history) == 2
            and len(beta_history) == 2
            and "Beta Confidential Merchant" not in serialized_alpha
            and "Alpha Confidential Merchant" not in serialized_beta,
            f"company history lengths={len(alpha_history)}/{len(beta_history)}",
        )
        with closing(core._connect()) as connection:
            alpha_transaction = connection.execute(
                "SELECT id, workspace_id FROM transactions WHERE workspace_id=?",
                (alpha_id,),
            ).fetchone()
            beta_transaction = connection.execute(
                "SELECT id, workspace_id FROM transactions WHERE workspace_id=?",
                (beta_id,),
            ).fetchone()
        self.check(
            "isolation.database_ids_are_scoped",
            alpha_transaction is not None
            and beta_transaction is not None
            and alpha_transaction[0] != beta_transaction[0]
            and alpha_transaction[1] == alpha_id
            and beta_transaction[1] == beta_id,
            "persisted transaction IDs and workspace ownership must be distinct",
        )

    def evaluate_history(self, session_id: str, expected_business_turns: int, expected_personal_turns: int) -> None:
        business_response = self.client.get(
            f"/api/chat/history?workspace=business&session_id={session_id}"
        )
        personal_response = self.client.get(
            f"/api/chat/history?workspace=personal&session_id={session_id}"
        )
        empty_response = self.client.get(
            "/api/chat/history?workspace=business&session_id=eval-unused-session"
        )
        business = business_response.get_json(silent=True) or []
        personal = personal_response.get_json(silent=True) or []
        empty = empty_response.get_json(silent=True) or []

        def alternating(rows: list[dict[str, Any]]) -> bool:
            return all(
                item.get("role") == ("user" if index % 2 == 0 else "assistant")
                for index, item in enumerate(rows)
            )

        self.check(
            "memory.same_session_history_persists",
            business_response.status_code == 200
            and len(business) == expected_business_turns * 2
            and alternating(business)
            and personal_response.status_code == 200
            and len(personal) == expected_personal_turns * 2
            and alternating(personal),
            f"history entries business/personal={len(business)}/{len(personal)}",
        )
        business_text = " ".join(str(item.get("content", "")) for item in business)
        personal_text = " ".join(str(item.get("content", "")) for item in personal)
        self.check(
            "memory.history_is_scoped",
            empty_response.status_code == 200
            and empty == []
            and "Amazon suddenly looks high" not in business_text
            and "MFA enabled" not in personal_text,
            "session history must remain isolated by both session ID and workspace",
        )

    def score_qualitative_rubric(
        self,
        first_money: dict[str, Any],
        repeated_money: dict[str, Any],
        mfa: dict[str, Any],
        unassisted_follow_up: dict[str, Any],
        follow_up: dict[str, Any],
        unknown: dict[str, Any],
        employee_before: dict[str, Any],
        employee_after: dict[str, Any],
    ) -> None:
        successful_answers = [
            turn.answer for turn in self.result.transcript if turn.http_status == 200
        ]
        readable = [
            answer for answer in successful_answers
            if 4 <= len(answer.split()) <= 220
            and answer.rstrip().endswith((".", "!", "?"))
            and not answer.lstrip().startswith(("{", "["))
        ]
        readability_ratio = len(readable) / max(1, len(successful_answers))
        readability_score = 2 if readability_ratio >= 0.9 else (1 if readability_ratio >= 0.75 else 0)
        self.result.rubric.append(RubricItem(
            "Naturalness and readability",
            readability_score,
            2,
            f"{len(readable)}/{len(successful_answers)} answers were concise sentences rather than raw data dumps.",
        ))

        unassisted_evidence = set(unassisted_follow_up.get("evidence_ids") or [])
        follow_evidence = set(follow_up.get("evidence_ids") or [])
        mfa_evidence = set(mfa.get("evidence_ids") or [])
        unassisted_relevant = (
            bool(unassisted_evidence & mfa_evidence)
            and not str(unassisted_follow_up.get("answer", "")).startswith("Unknown.")
        )
        assisted_conditions = sum((
            bool(follow_evidence & mfa_evidence),
            follow_up.get("answer") != mfa.get("answer"),
            len(str(follow_up.get("answer", "")).split()) >= 5,
        ))
        self.result.rubric.append(RubricItem(
            "Follow-up relevance",
            2 if unassisted_relevant else (1 if assisted_conditions == 3 else 0),
            2,
            "A bare same-session 'Why?' and a client-assisted selected-control follow-up were both evaluated.",
        ))

        consistent = (
            first_money.get("answer") == repeated_money.get("answer")
            and first_money.get("calculation") == repeated_money.get("calculation")
            and first_money.get("evidence_ids") == repeated_money.get("evidence_ids")
        )
        restraint_conditions = sum((
            str(unknown.get("answer", "")).startswith("Unknown."),
            (unknown.get("evidence_ids") or []) == [],
            "suggestion, not a conclusion" in str(
                self.responses.get("spending.cut_uncertain", {}).get("answer", "")
            ).lower(),
            "not automatically confirmed" in str(
                self.responses.get("reconciliation.chat_summary", {}).get("answer", "")
            ).lower(),
        ))
        self.result.rubric.append(RubricItem(
            "Epistemic calibration",
            2 if restraint_conditions == 4 else (1 if restraint_conditions >= 3 else 0),
            2,
            "Unknown claims, spending suggestions, and reconciliation candidates were checked for calibrated language.",
        ))

        adapted = (
            "Priya Shah" in str(employee_before.get("answer", ""))
            and "Priya Shah" not in str(employee_after.get("answer", ""))
            and (employee_after.get("calculation") or {}).get("needs_review", 999)
            < (employee_before.get("calculation") or {}).get("needs_review", -1)
        )
        self.result.rubric.append(RubricItem(
            "Consistency and state awareness",
            2 if consistent and adapted else (1 if consistent or adapted else 0),
            2,
            "An unchanged calculation was repeated, then an audited correction was used to detect stale narrative reuse.",
        ))

        actionable_answers = (
            str(self.responses.get("spending.cut_itemized", {}).get("answer", "")),
            str(self.responses.get("reconciliation.chat_summary", {}).get("answer", "")),
            str(mfa.get("answer", "")),
        )
        bounded = all(8 <= len(answer.split()) <= 220 for answer in actionable_answers)
        concrete_next_step = (
            any(term in actionable_answers[0].lower() for term in ("meal budget", "purchase frequency"))
            and "review" in actionable_answers[1].lower()
            and any(term in actionable_answers[2].lower() for term in ("follow-up", "attach", "ask"))
        )
        self.result.rubric.append(RubricItem(
            "Concise and actionable",
            2 if bounded and concrete_next_step else (1 if bounded or concrete_next_step else 0),
            2,
            "Representative spending, reconciliation, and security answers were checked for bounded length and next steps.",
        ))

    def run(self) -> EvaluationResult:
        session_id = "eval-main-session"
        self.check(
            "harness.temporary_database",
            core.DB_PATH.parent == self.application.root / "runtime"
            and core.DB_PATH != REPOSITORY_ROOT / "data" / "runtime" / "payproof.sqlite3",
            "all mutable evaluation state is under a TemporaryDirectory",
        )
        self.evaluate_financial_math(session_id)
        self.evaluate_amazon_and_email(session_id)
        employee_before, _ = self.evaluate_intake_and_bank_reconciliation(session_id)
        mfa, unassisted_follow_up, follow_up, unknown = self.evaluate_security_and_injection(session_id)
        employee_after = self.evaluate_correction(session_id, employee_before)
        self.evaluate_company_isolation()

        expected_business = sum(
            turn.workspace == "business" and turn.session_id == session_id
            for turn in self.result.transcript
        )
        expected_personal = sum(
            turn.workspace == "personal" and turn.session_id == session_id
            for turn in self.result.transcript
        )
        self.evaluate_history(session_id, expected_business, expected_personal)
        self.score_qualitative_rubric(
            self.responses["finance.money_flow_first"],
            self.responses["finance.money_flow_repeat"],
            mfa,
            unassisted_follow_up,
            follow_up,
            unknown,
            employee_before,
            employee_after,
        )
        return self.result


def run_evaluation() -> EvaluationResult:
    with isolated_application() as application:
        return ConversationEvaluator(application).run()


def print_report(result: EvaluationResult, output: TextIO = sys.stdout) -> None:
    print("PayProof evidence-grounded conversation evaluation", file=output)
    print(
        "Scope: synthetic QA heuristic only; not a scientifically valid Turing test and no claim of consciousness.",
        file=output,
    )
    print("\nConcise transcript", file=output)
    for index, turn in enumerate(result.transcript, start=1):
        print(
            f"{index:02d}. [{sanitize_for_report(turn.workspace, 50)}] "
            f"User: {sanitize_for_report(turn.question, 140)}",
            file=output,
        )
        print(
            f"    PayProof: {sanitize_for_report(turn.answer, 220)} "
            f"(HTTP {turn.http_status}; citations {turn.evidence_count})",
            file=output,
        )

    print("\nMachine-check verdicts", file=output)
    groups: dict[str, list[MachineCheck]] = {}
    for item in result.checks:
        groups.setdefault(item.name.split(".", 1)[0], []).append(item)
    for group, items in sorted(groups.items()):
        passed = sum(item.passed for item in items)
        label = "PASS" if passed == len(items) else "FAIL"
        print(f"[{label}] {group}: {passed}/{len(items)}", file=output)
        for failure in (item for item in items if not item.passed):
            print(
                f"    {sanitize_for_report(failure.name, 100)}: "
                f"{sanitize_for_report(failure.detail, 280)}",
                file=output,
            )

    print("\nQualitative rubric (heuristic)", file=output)
    for item in result.rubric:
        print(
            f"- {sanitize_for_report(item.name, 80)}: {item.score}/{item.maximum} - "
            f"{sanitize_for_report(item.rationale, 220)}",
            file=output,
        )
    print(f"Rubric total: {result.rubric_score}/{result.rubric_maximum}", file=output)
    print(
        f"Release gate: {'PASS' if result.passed else 'FAIL'} "
        f"({sum(item.passed for item in result.checks)}/{len(result.checks)} machine checks)",
        file=output,
    )


def main() -> int:
    result = run_evaluation()
    print_report(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
