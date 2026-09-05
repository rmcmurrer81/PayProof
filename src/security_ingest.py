"""Deterministic security-questionnaire ingestion with source-level provenance.

This module intentionally has no dependency on PayProof's database, Flask app,
runtime model, or network integrations.  It is designed to be integrated into
``src.core`` after its behavior has been reviewed independently.

The engine treats every company document as untrusted data.  It extracts only
statements found in the supplied files, removes instructions aimed at an AI or
attempts to bypass controls, and will not produce a supported answer without a
resolvable citation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".json"})
OCR_REQUIRED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"})
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 250_000
MAX_TOTAL_EXTRACTED_CHARACTERS = 2_000_000
MAX_SOURCE_FILES = 250
MAX_DISCOVERED_FILES = 500
MAX_QUESTIONNAIRE_ITEMS = 250


class SecurityIngestError(ValueError):
    """Raised when a questionnaire or evidence folder cannot be ingested."""


@dataclass(frozen=True)
class QuestionnaireItem:
    id: str
    question: str
    priority: str = "normal"

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "question": self.question, "priority": self.priority}


@dataclass(frozen=True)
class EvidenceStatement:
    source_id: str
    text: str
    line_start: int | None = None
    json_path: str | None = None

    @property
    def normalized(self) -> str:
        return _normalize_text(self.text)


@dataclass(frozen=True)
class IgnoredFragment:
    source_id: str
    excerpt: str
    reason: str
    line_start: int | None = None
    json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "excerpt": self.excerpt,
            "reason": self.reason,
            "line_start": self.line_start,
            "json_path": self.json_path,
        }


@dataclass(frozen=True)
class SourceDocument:
    id: str
    filename: str
    basename: str
    title: str
    sha256: str
    source_date: str
    date_basis: str
    statements: tuple[EvidenceStatement, ...]
    ignored_fragments: tuple[IgnoredFragment, ...] = ()
    extracted_character_count: int = 0

    def to_dict(
        self,
        *,
        include_statements: bool = False,
        include_ignored_content: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "filename": self.filename,
            "basename": self.basename,
            "title": self.title,
            "sha256": self.sha256,
            "source_date": self.source_date,
            "date_basis": self.date_basis,
            "statement_count": len(self.statements),
            "extracted_character_count": self.extracted_character_count,
            "ignored_untrusted_count": len(self.ignored_fragments),
        }
        if include_statements:
            result["statements"] = [
                {
                    "text": statement.text,
                    "line_start": statement.line_start,
                    "json_path": statement.json_path,
                }
                for statement in self.statements
            ]
        if include_ignored_content:
            result["ignored_fragments"] = [fragment.to_dict() for fragment in self.ignored_fragments]
        return result


@dataclass(frozen=True)
class EvidenceCitation:
    source_id: str
    filename: str
    source_date: str
    sha256: str
    excerpt: str
    line_start: int | None = None
    json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "filename": self.filename,
            "source_date": self.source_date,
            "sha256": self.sha256,
            "excerpt": self.excerpt,
            "line_start": self.line_start,
            "json_path": self.json_path,
        }


@dataclass(frozen=True)
class QuestionnaireAnswer:
    question_id: str
    question: str
    control_id: str | None
    status: str
    answer: str
    evidence_ids: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...]
    follow_up: str | None
    confidence_score: float
    confidence_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "control_id": self.control_id,
            "status": self.status,
            "answer": self.answer,
            "evidence_ids": list(self.evidence_ids),
            "citations": [citation.to_dict() for citation in self.citations],
            "follow_up": self.follow_up,
            "confidence_score": self.confidence_score,
            "confidence_basis": self.confidence_basis,
        }


@dataclass(frozen=True)
class EvidenceCatalog:
    root: str
    sources: tuple[SourceDocument, ...]
    errors: tuple[str, ...] = ()

    @property
    def source_index(self) -> dict[str, SourceDocument]:
        return {source.id: source for source in self.sources}

    @property
    def statements(self) -> tuple[EvidenceStatement, ...]:
        return tuple(statement for source in self.sources for statement in source.statements)

    def resolve(self, source_id: str) -> SourceDocument | None:
        return self.source_index.get(source_id)

    def to_dict(
        self,
        *,
        include_statements: bool = False,
        include_ignored_content: bool = False,
    ) -> dict[str, Any]:
        return {
            "root": self.root,
            "sources": [
                source.to_dict(
                    include_statements=include_statements,
                    include_ignored_content=include_ignored_content,
                )
                for source in self.sources
            ],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class SecurityAssessmentReport:
    questionnaire_filename: str
    questionnaire_sha256: str
    questions: tuple[QuestionnaireItem, ...]
    answers: tuple[QuestionnaireAnswer, ...]
    catalog: EvidenceCatalog

    def validate_citations(self) -> bool:
        source_ids = set(self.catalog.source_index)
        for answer in self.answers:
            if set(answer.evidence_ids) - source_ids:
                return False
            if any(citation.source_id not in source_ids for citation in answer.citations):
                return False
            if set(answer.evidence_ids) != {citation.source_id for citation in answer.citations}:
                return False
        return True

    def to_dict(
        self,
        *,
        include_source_statements: bool = False,
        include_ignored_content: bool = False,
    ) -> dict[str, Any]:
        if not self.validate_citations():
            raise SecurityIngestError("Assessment contains an unresolved evidence citation")
        return {
            "questionnaire": {
                "filename": self.questionnaire_filename,
                "sha256": self.questionnaire_sha256,
                "question_count": len(self.questions),
            },
            "summary": {
                "supported": sum(answer.status == "supported" for answer in self.answers),
                "partial": sum(answer.status == "partial" for answer in self.answers),
                "conflict": sum(answer.status == "conflict" for answer in self.answers),
                "unknown": sum(answer.status == "unknown" for answer in self.answers),
                "ignored_untrusted_fragments": sum(
                    len(source.ignored_fragments) for source in self.catalog.sources
                ),
            },
            "answers": [answer.to_dict() for answer in self.answers],
            "evidence_catalog": self.catalog.to_dict(
                include_statements=include_source_statements,
                include_ignored_content=include_ignored_content,
            ),
        }


@dataclass(frozen=True)
class _ControlRule:
    id: str
    question_terms: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    positive_patterns: tuple[str, ...]
    negative_patterns: tuple[str, ...]
    unknown_follow_up: str
    conflict_follow_up: str


CONTROL_RULES: tuple[_ControlRule, ...] = (
    _ControlRule(
        "mfa",
        ("mfa", "multi factor", "multi-factor", "two factor", "2fa"),
        ("mfa", "multi factor", "multi-factor", "two factor", "2fa", "production identities"),
        (
            r"\b(?:mfa|multi[ -]?factor|two[ -]?factor|2fa)\b.{0,80}\b(?:enabled|required|enforced|true|all)\b",
            r"\b(?:enabled|required|enforced)\b.{0,80}\b(?:mfa|multi[ -]?factor|two[ -]?factor|2fa)\b",
        ),
        (
            r"\b(?:mfa|multi[ -]?factor|two[ -]?factor|2fa)\b.{0,80}\b(?:disabled|false|exempt|optional|not enabled|not required|without)\b",
            r"\b(?:disabled|exempt|without)\b.{0,80}\b(?:mfa|multi[ -]?factor|two[ -]?factor|2fa)\b",
        ),
        "Ask the identity or security owner for a current identity-provider export showing MFA enrollment, exceptions, exception owners, and expiration dates.",
        "Ask the identity or security owner to reconcile the MFA requirement with the observed exception or disabled state, then attach a current identity-provider export and approved exception records.",
    ),
    _ControlRule(
        "customer_data_storage",
        ("where is customer data", "customer data stored", "data storage", "storage location"),
        ("customer data", "customer database", "support attachment", "storage region", "data inventory", "database"),
        (),
        (),
        "Ask the data or infrastructure owner for a current data inventory listing every customer-data store, provider, and region.",
        "Ask the data or infrastructure owner to reconcile the conflicting storage locations and identify which system, environment, and date each location applies to.",
    ),
    _ControlRule(
        "encryption_at_rest",
        ("encryption at rest", "encrypt data at rest", "encrypted at rest", "storage encryption", "encrypt", "encryption"),
        ("encryption at rest", "encrypted at rest", "storage encryption", "disk encryption", "database encryption"),
        (
            r"\b(?:encryption|encrypted)\b.{0,80}\b(?:enabled|true|active|at rest)\b",
            r"\b(?:enabled|true|active)\b.{0,80}\b(?:encryption|encrypted)\b",
        ),
        (
            r"\b(?:encryption|encrypted)\b.{0,80}\b(?:disabled|false|not encrypted|unencrypted)\b",
            r"\b(?:disabled|false|unencrypted)\b.{0,80}\b(?:encryption|encrypted|storage)\b",
        ),
        "Ask each system owner for current configuration evidence proving encryption at rest for every customer-data store, including third-party providers.",
        "Ask the system owners to reconcile the conflicting encryption states and attach current configuration evidence for each affected data store.",
    ),
    _ControlRule(
        "backups",
        ("backup", "backups", "recovery copy"),
        ("backup", "backups", "recovery copy", "restore job"),
        (
            r"\b(?:backup|backups|restore job)\b.{0,100}\b(?:successful|succeeded|completed|current|enabled|daily|true)\b",
            r"\b(?:successful|succeeded|completed|current|enabled|daily|true)\b.{0,100}\b(?:backup|backups|restore job)\b",
        ),
        (
            r"\b(?:backup|backups|restore job|job)\b.{0,100}\b(?:failed|failing|overdue|disabled|not current|false)\b",
            r"\b(?:failed|failing|overdue|disabled|not current|false)\b.{0,100}\b(?:backup|backups|restore job|job)\b",
        ),
        "Ask the backup owner for the configured schedule, encryption setting, most recent successful job, failed jobs, and latest restore-test evidence.",
        "Ask the backup owner to reconcile the stated schedule or healthy state with the failed or overdue job evidence, then attach a successful rerun and restore-test result.",
    ),
    _ControlRule(
        "vulnerability_scanning",
        ("vulnerability scan", "vulnerability scanning", "security scan", "vulnerability assessment"),
        ("vulnerability scan", "vulnerability scanning", "scanner report", "external scan", "security scan"),
        (
            r"\b(?:scan|scanning|scanner)\b.{0,100}\b(?:completed|enabled|monthly|weekly|daily|true)\b",
            r"\b(?:completed|enabled|monthly|weekly|daily|true)\b.{0,100}\b(?:scan|scanning|scanner)\b",
        ),
        (
            r"\b(?:scan|scanning|scanner)\b.{0,100}\b(?:disabled|failed|overdue|never|not performed|false)\b",
            r"\b(?:disabled|failed|overdue|never|false)\b.{0,100}\b(?:scan|scanning|scanner)\b",
        ),
        "Ask the security owner for the scanner scope, schedule, most recent completed scan, unresolved high-severity findings, and remediation owners.",
        "Ask the security owner to reconcile the claimed scanning practice with the failed, disabled, or overdue scan evidence and attach the latest complete report.",
    ),
    _ControlRule(
        "production_access",
        ("production access", "access to production", "who has access", "access production"),
        ("production access", "production user", "production identity", "break glass", "break-glass", "deployment token"),
        (),
        (),
        "Ask the security or infrastructure owner for a current production-access roster including people, service accounts, emergency accounts, owners, and review dates.",
        "Ask the security or infrastructure owner to reconcile the conflicting production-access rosters and confirm the owner and review date for every account.",
    ),
    _ControlRule(
        "offboarding",
        ("offboard", "offboarding", "employee departure", "termination", "former employee", "former contractor"),
        ("offboard", "offboarding", "departure", "termination", "former employee", "former contractor", "access removal", "deployment token"),
        (
            r"\b(?:access|account|credential|token)\b.{0,100}\b(?:removed|revoked|disabled|terminated)\b",
            r"\b(?:offboard|offboarding)\b.{0,100}\b(?:complete|completed|within|required|removed|revoked)\b",
        ),
        (
            r"\b(?:access|account|credential|token)\b.{0,100}\b(?:still active|not removed|not revoked|remained active|overdue)\b",
            r"\b(?:former|departed|terminated)\b.{0,120}\b(?:active|access|credential|token)\b",
        ),
        "Ask HR and IT for the offboarding policy, the latest departure roster, access-removal timestamps, outstanding credentials, and the responsible owner.",
        "Ask HR and IT to reconcile the required offboarding timing with the remaining active access and attach revocation evidence plus the incident owner.",
    ),
)


_METADATA_KEYS = {
    "id", "title", "name", "filename", "date", "as_of", "asof", "effective",
    "effective_date", "generated", "generated_at", "updated", "updated_at", "timestamp",
}
_CONTENT_KEYS = {"statement", "text", "content", "description", "details", "observation", "finding", "message"}
_UNCERTAINTY_PATTERNS = (
    r"\bunknown\b",
    r"\bnot documented\b",
    r"\bno (?:attached )?evidence\b",
    r"\bevidence (?:is )?not attached\b",
    r"\bnot provided\b",
    r"\bnot present\b",
    r"\bunavailable\b",
    r"\bcould not (?:confirm|determine|verify)\b",
)
_UNTRUSTED_INSTRUCTION_PATTERNS = (
    r"\b(?:ignore|disregard|override)\b.{0,100}\b(?:previous|prior|instruction|policy|control|evidence|rule)\b",
    r"\b(?:assistant|chatbot|language model|ai model)\b.{0,100}\b(?:must|should|ignore|approve|mark|send|transfer|execute|reveal)\b",
    r"\bmark\b.{0,80}\b(?:verified|compliant|approved)\b",
    r"\bbypass\b.{0,80}\b(?:control|review|approval|verification)\b",
    r"\breveal\b.{0,80}\b(?:system prompt|hidden instruction|secret)\b",
    r"\bsend (?:the )?payment\b",
)
_GENERIC_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "company", "conduct",
        "data", "do", "does", "for", "from", "have", "how", "i", "in", "is", "it",
        "of", "on", "or", "our", "the", "their", "this", "to", "we", "what", "when",
        "where", "which", "who", "with", "you", "your",
    }
)


def load_questionnaire(path: str | Path) -> tuple[QuestionnaireItem, ...]:
    """Load questionnaire questions from JSON, Markdown, or plain text.

    JSON accepts a top-level list or an object containing ``questions``,
    ``questionnaire``, ``items``, or ``controls``.  Markdown/text accepts
    numbered or bulleted questions and unadorned lines ending in ``?``.
    Existing answers in a questionnaire are deliberately ignored.
    """

    source_path = Path(path)
    if not source_path.is_file():
        raise SecurityIngestError(f"Questionnaire not found: {source_path}")
    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise SecurityIngestError("Questionnaire must be .json, .md, or .txt")
    raw = _read_source_bytes(source_path)
    text = _decode_utf8(raw, source_path)
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise SecurityIngestError(
            f"Questionnaire exceeds {MAX_EXTRACTED_CHARACTERS} character limit"
        )
    if source_path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SecurityIngestError(f"Invalid questionnaire JSON: {exc.msg}") from exc
        raw_items = list(_question_items_from_json(payload))
    else:
        raw_items = list(_question_items_from_text(text))

    questions: list[QuestionnaireItem] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_items, start=1):
        question = re.sub(r"\s+", " ", str(raw_item.get("question", ""))).strip()
        if not question:
            continue
        supplied_id = str(raw_item.get("id", "")).strip()
        item_id = _stable_question_id(supplied_id, question, index)
        if item_id in seen_ids:
            base_id = f"{item_id}-{hashlib.sha256(question.encode('utf-8')).hexdigest()[:6].upper()}"
            item_id = base_id
            duplicate_number = 2
            while item_id in seen_ids:
                item_id = f"{base_id}-{duplicate_number}"
                duplicate_number += 1
        seen_ids.add(item_id)
        priority = str(raw_item.get("priority", "normal")).strip().lower() or "normal"
        questions.append(QuestionnaireItem(item_id, question, priority))
        if len(questions) > MAX_QUESTIONNAIRE_ITEMS:
            raise SecurityIngestError(
                f"Questionnaire contains more than {MAX_QUESTIONNAIRE_ITEMS} questions"
            )
    if not questions:
        raise SecurityIngestError("Questionnaire contains no questions")
    return tuple(questions)


def ingest_company_evidence(
    folder: str | Path,
    *,
    exclude_paths: Iterable[str | Path] = (),
) -> EvidenceCatalog:
    """Ingest supported company evidence files beneath ``folder``.

    Malformed or oversized evidence is surfaced through ``catalog.errors`` and
    is never silently cited. Symlinks are ignored so an evidence folder cannot
    unexpectedly read outside its declared boundary.
    """

    root = Path(folder).resolve()
    if not root.is_dir():
        raise SecurityIngestError(f"Evidence folder not found: {root}")
    excluded = {Path(item).resolve() for item in exclude_paths}
    sources: list[SourceDocument] = []
    errors: list[str] = []
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )
    if len(paths) > MAX_DISCOVERED_FILES:
        raise SecurityIngestError(
            f"Evidence folder contains {len(paths)} files; discovery limit is {MAX_DISCOVERED_FILES}"
        )
    supported_paths = [path for path in paths if path.suffix.lower() in SUPPORTED_EXTENSIONS]
    if len(supported_paths) > MAX_SOURCE_FILES:
        raise SecurityIngestError(
            f"Evidence folder contains {len(supported_paths)} supported files; limit is {MAX_SOURCE_FILES}"
        )
    total_extracted_characters = 0
    for path in paths:
        if path.resolve() in excluded:
            continue
        relative = path.relative_to(root).as_posix()
        extension = path.suffix.lower()
        if extension in OCR_REQUIRED_EXTENSIONS:
            errors.append(
                f"{relative}: OCR_REQUIRED; preserve the original and provide reviewed UTF-8 .txt or .json extraction"
            )
            continue
        if extension not in SUPPORTED_EXTENSIONS:
            errors.append(f"{relative}: UNSUPPORTED_EXTENSION")
            continue
        try:
            source = _ingest_source(path, relative)
        except (OSError, SecurityIngestError) as exc:
            errors.append(f"{relative}: {exc}")
            continue
        total_extracted_characters += source.extracted_character_count
        if total_extracted_characters > MAX_TOTAL_EXTRACTED_CHARACTERS:
            errors.append(
                f"{relative}: total extracted text exceeds {MAX_TOTAL_EXTRACTED_CHARACTERS} character limit"
            )
            break
        sources.append(source)
    return EvidenceCatalog(root=str(root), sources=tuple(sources), errors=tuple(errors))


def assess_questionnaire(
    questionnaire_path: str | Path,
    evidence_folder: str | Path,
    *,
    exclude_paths: Iterable[str | Path] = (),
) -> SecurityAssessmentReport:
    """Assess every questionnaire item against only the supplied evidence."""

    questionnaire = Path(questionnaire_path).resolve()
    questions = load_questionnaire(questionnaire)
    catalog = ingest_company_evidence(
        evidence_folder,
        exclude_paths=(questionnaire, *tuple(exclude_paths)),
    )
    answers = tuple(_assess_item(item, catalog) for item in questions)
    report = SecurityAssessmentReport(
        questionnaire_filename=questionnaire.name,
        questionnaire_sha256=hashlib.sha256(_read_source_bytes(questionnaire)).hexdigest(),
        questions=questions,
        answers=answers,
        catalog=catalog,
    )
    if not report.validate_citations():
        raise SecurityIngestError("Assessment contains an unresolved evidence citation")
    return report


class SecurityIngestionEngine:
    """Small integration-friendly facade around the module-level API."""

    def __init__(self, evidence_folder: str | Path):
        self.evidence_folder = Path(evidence_folder)

    def ingest(self, *, exclude_paths: Iterable[str | Path] = ()) -> EvidenceCatalog:
        return ingest_company_evidence(self.evidence_folder, exclude_paths=exclude_paths)

    def assess(
        self,
        questionnaire_path: str | Path,
        *,
        exclude_paths: Iterable[str | Path] = (),
    ) -> SecurityAssessmentReport:
        return assess_questionnaire(
            questionnaire_path,
            self.evidence_folder,
            exclude_paths=exclude_paths,
        )


def _ingest_source(path: Path, relative_filename: str) -> SourceDocument:
    raw = _read_source_bytes(path)
    text = _decode_utf8(raw, path)
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise SecurityIngestError(
            f"extracted text exceeds {MAX_EXTRACTED_CHARACTERS} character limit"
        )
    source_id = _stable_source_id(relative_filename)
    sha256 = hashlib.sha256(raw).hexdigest()
    suffix = path.suffix.lower()
    payload: Any = None
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SecurityIngestError(f"invalid JSON: {exc.msg}") from exc
        title = _json_title(payload) or path.stem
        source_date, date_basis = _date_from_json(payload) or _filesystem_date(path)
        candidates = list(_statements_from_json(payload, source_id))
    else:
        title = _text_title(text) or path.stem
        source_date, date_basis = _date_from_text(text) or _filesystem_date(path)
        candidates = list(_statements_from_text(text, source_id))

    statements: list[EvidenceStatement] = []
    ignored: list[IgnoredFragment] = []
    seen: set[str] = set()
    source_contains_instruction = any(_is_untrusted_instruction(statement.text) for statement in candidates)
    if source_contains_instruction:
        # Do not surface an attacker-controlled heading in the default safe
        # serialization. Reviewers can explicitly request ignored content.
        title = Path(relative_filename).stem
    for statement in candidates:
        normalized = statement.normalized
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if source_contains_instruction:
            direct_instruction = _is_untrusted_instruction(statement.text)
            ignored.append(
                IgnoredFragment(
                    source_id=source_id,
                    excerpt=_excerpt(statement.text),
                    reason=(
                        "Document-embedded instruction was treated as untrusted content and excluded from assessment."
                        if direct_instruction
                        else "Source statement was quarantined because the same document contains an instruction aimed at the assistant."
                    ),
                    line_start=statement.line_start,
                    json_path=statement.json_path,
                )
            )
            continue
        statements.append(statement)
    return SourceDocument(
        id=source_id,
        filename=relative_filename,
        basename=Path(relative_filename).name,
        title=str(title).strip()[:200],
        sha256=sha256,
        source_date=source_date,
        date_basis=date_basis,
        statements=tuple(statements),
        ignored_fragments=tuple(ignored),
        extracted_character_count=len(text),
    )


def _assess_item(item: QuestionnaireItem, catalog: EvidenceCatalog) -> QuestionnaireAnswer:
    rule = _match_control_rule(item.question)
    source_context_ids = {
        source.id
        for source in catalog.sources
        if _statement_is_relevant(
            item.question,
            f"{source.title} {source.filename}",
            rule,
        )
    }
    candidates = [
        statement
        for statement in catalog.statements
        if not _is_document_metadata(statement.text)
        and (
            statement.source_id in source_context_ids
            or _statement_is_relevant(item.question, statement.text, rule)
        )
    ]
    candidates.sort(key=lambda statement: _statement_sort_key(statement, catalog))

    if not candidates:
        follow_up = rule.unknown_follow_up if rule else _generic_follow_up(item.question)
        return QuestionnaireAnswer(
            question_id=item.id,
            question=item.question,
            control_id=rule.id if rule else None,
            status="unknown",
            answer=f"Unknown. No loaded evidence supports an answer to: {item.question}",
            evidence_ids=(),
            citations=(),
            follow_up=follow_up,
            confidence_score=0.0,
            confidence_basis="No relevant, trusted source statement was found.",
        )

    positive = [statement for statement in candidates if _polarity(statement.text, rule) in {"positive", "mixed"}]
    negative = [statement for statement in candidates if _polarity(statement.text, rule) in {"negative", "mixed"}]
    uncertain = [statement for statement in candidates if _is_uncertain(statement.text)]
    conflict_pair = _conflict_pair(positive, negative)
    if not conflict_pair and rule:
        conflict_pair = _value_conflict_pair(rule.id, candidates)

    if conflict_pair:
        conflict_sources = {statement.source_id for statement in conflict_pair}
        context = [statement for statement in candidates if statement.source_id in conflict_sources]
        # Include bounded same-source context so a conflict answer does not hide
        # nearby observed totals or qualifiers that explain the discrepancy.
        selected = _unique_statements((*conflict_pair, *context))[:6]
        citations = _citations(selected, catalog)
        follow_up = rule.conflict_follow_up if rule else _generic_conflict_follow_up(item.question)
        answer = "Conflicting evidence found. " + _quoted_evidence_summary(citations)
        return _make_answer(
            item,
            rule,
            "conflict",
            answer,
            citations,
            follow_up,
            0.35,
            "Relevant trusted sources contain explicit opposing assertions or incompatible values.",
        )

    substantive = [statement for statement in candidates if statement not in uncertain]
    if not substantive:
        citations = _citations(candidates[:3], catalog)
        follow_up = rule.unknown_follow_up if rule else _generic_follow_up(item.question)
        return _make_answer(
            item,
            rule,
            "unknown",
            "Unknown. Loaded evidence explicitly says the information is unavailable or undocumented. "
            + _quoted_evidence_summary(citations),
            citations,
            follow_up,
            0.2,
            "Relevant sources describe the answer as unknown, undocumented, unavailable, or unsupported.",
        )

    selected = _unique_statements((*substantive[:4], *uncertain[:2]))[:6]
    citations = _citations(selected, catalog)
    if uncertain:
        status = "partial"
        answer = "Available evidence is incomplete. " + _quoted_evidence_summary(citations)
        follow_up = rule.unknown_follow_up if rule else _generic_follow_up(item.question)
        confidence = min(0.7, 0.5 + 0.05 * len({citation.source_id for citation in citations}))
        basis = "At least one relevant trusted statement is present, but another states that coverage or documentation is incomplete."
    else:
        status = "supported"
        answer = "Evidence states: " + _quoted_evidence_summary(citations)
        follow_up = None
        confidence = min(0.95, 0.72 + 0.06 * (len({citation.source_id for citation in citations}) - 1))
        basis = "The answer is limited to consistent statements found in the loaded trusted evidence."
    return _make_answer(item, rule, status, answer, citations, follow_up, confidence, basis)


def _make_answer(
    item: QuestionnaireItem,
    rule: _ControlRule | None,
    status: str,
    answer: str,
    citations: Sequence[EvidenceCitation],
    follow_up: str | None,
    confidence: float,
    confidence_basis: str,
) -> QuestionnaireAnswer:
    evidence_ids = tuple(dict.fromkeys(citation.source_id for citation in citations))
    return QuestionnaireAnswer(
        question_id=item.id,
        question=item.question,
        control_id=rule.id if rule else None,
        status=status,
        answer=answer,
        evidence_ids=evidence_ids,
        citations=tuple(citations),
        follow_up=follow_up,
        confidence_score=round(confidence, 2),
        confidence_basis=confidence_basis,
    )


def _citations(statements: Sequence[EvidenceStatement], catalog: EvidenceCatalog) -> tuple[EvidenceCitation, ...]:
    citations: list[EvidenceCitation] = []
    seen: set[tuple[str, str]] = set()
    for statement in statements:
        source = catalog.resolve(statement.source_id)
        if source is None:
            continue
        excerpt = _excerpt(statement.text)
        key = (source.id, excerpt)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            EvidenceCitation(
                source_id=source.id,
                filename=source.filename,
                source_date=source.source_date,
                sha256=source.sha256,
                excerpt=excerpt,
                line_start=statement.line_start,
                json_path=statement.json_path,
            )
        )
    return tuple(citations)


def _statement_sort_key(statement: EvidenceStatement, catalog: EvidenceCatalog) -> tuple[str, int, str]:
    source = catalog.resolve(statement.source_id)
    return (
        source.filename.casefold() if source else statement.source_id,
        statement.line_start or 0,
        statement.json_path or "",
    )


def _match_control_rule(question: str) -> _ControlRule | None:
    normalized = _normalize_text(question)
    matches: list[tuple[int, int, _ControlRule]] = []
    for index, rule in enumerate(CONTROL_RULES):
        matched_lengths = [len(_normalize_text(term)) for term in rule.question_terms if _normalize_text(term) in normalized]
        if matched_lengths:
            matches.append((max(matched_lengths), -index, rule))
    return max(matches, default=(0, 0, None), key=lambda value: (value[0], value[1]))[2]


def _statement_is_relevant(question: str, statement: str, rule: _ControlRule | None) -> bool:
    normalized_statement = _normalize_text(statement)
    if rule:
        return any(_normalize_text(term) in normalized_statement for term in rule.evidence_terms)
    question_tokens = _content_tokens(question)
    statement_tokens = _content_tokens(statement)
    overlap = question_tokens & statement_tokens
    return len(overlap) >= 2 or any(len(token) >= 8 for token in overlap)


def _polarity(text: str, rule: _ControlRule | None) -> str:
    if rule is None:
        return "neutral"
    normalized = _normalize_text(text)
    # Structured JSON commonly renders as ``mfa enabled: false``.  Treat the
    # explicit boolean as authoritative for polarity so the word "enabled"
    # does not accidentally turn a false value into a mixed assertion.
    if re.search(r"\b(?:enabled|required|enforced|encrypted|current|completed)\s*:\s*false\b", normalized):
        return "negative"
    if re.search(r"\b(?:enabled|required|enforced|encrypted|current|completed)\s*:\s*true\b", normalized):
        return "positive"
    positive = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in rule.positive_patterns)
    negative = any(re.search(pattern, normalized, re.IGNORECASE) for pattern in rule.negative_patterns)
    if positive and negative:
        return "mixed"
    if positive:
        return "positive"
    if negative:
        return "negative"
    return "neutral"


def _conflict_pair(
    positive: Sequence[EvidenceStatement],
    negative: Sequence[EvidenceStatement],
) -> tuple[EvidenceStatement, EvidenceStatement] | None:
    for left in positive:
        for right in negative:
            if left is not right:
                return left, right
    mixed = next((statement for statement in positive if statement in negative), None)
    return (mixed, mixed) if mixed else None


def _value_conflict_pair(
    control_id: str,
    statements: Sequence[EvidenceStatement],
) -> tuple[EvidenceStatement, EvidenceStatement] | None:
    values: dict[str, EvidenceStatement] = {}
    for statement in statements:
        for value in _control_values(control_id, statement.text):
            if value not in values:
                values[value] = statement
    if len(values) < 2:
        return None
    ordered = sorted(values.items(), key=lambda item: item[0])
    return ordered[0][1], ordered[1][1]


def _control_values(control_id: str, text: str) -> set[str]:
    normalized = _normalize_text(text)
    if control_id == "customer_data_storage":
        return set(re.findall(r"\b(?:us|eu|ap|ca|sa|me|af)-(?:north|south|east|west|central|southeast|northeast)-\d\b", normalized))
    if control_id in {"backups", "vulnerability_scanning"}:
        return set(re.findall(r"\b(?:hourly|daily|weekly|monthly|quarterly|annually|annual)\b", normalized))
    return set()


def _is_uncertain(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _UNCERTAINTY_PATTERNS)


def _is_document_metadata(text: str) -> bool:
    stripped = text.strip()
    normalized = _normalize_text(stripped)
    if not stripped:
        return True
    if len(stripped) < 120 and stripped == stripped.upper() and any(character.isalpha() for character in stripped):
        return True
    return bool(re.match(r"^(?:generated|effective|as of|date)\s*:", normalized, re.IGNORECASE))


def _is_untrusted_instruction(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS)


def _quoted_evidence_summary(citations: Sequence[EvidenceCitation]) -> str:
    return " ".join(f'[{citation.source_id}] "{citation.excerpt}"' for citation in citations)


def _generic_follow_up(question: str) -> str:
    return (
        f"Identify the accountable owner for '{question}' and request a dated policy plus current operating evidence that directly answers it."
    )


def _generic_conflict_follow_up(question: str) -> str:
    return (
        f"Ask the accountable owner to reconcile the conflicting evidence for '{question}', identify which source is current, and attach dated operating proof."
    )


def _stable_source_id(relative_filename: str) -> str:
    normalized = relative_filename.replace("\\", "/").casefold().strip("/")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()
    return f"SEC-SRC-{digest}"


def _stable_question_id(supplied_id: str, question: str, index: int) -> str:
    if supplied_id:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", supplied_id).strip("-.")
        if cleaned:
            return cleaned[:80]
    digest = hashlib.sha256(_normalize_text(question).encode("utf-8")).hexdigest()[:8].upper()
    return f"Q-{index:03d}-{digest}"


def _read_source_bytes(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SecurityIngestError(f"could not stat file: {exc}") from exc
    if size > MAX_SOURCE_BYTES:
        raise SecurityIngestError(f"file exceeds {MAX_SOURCE_BYTES} byte limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SecurityIngestError(f"could not read file: {exc}") from exc


def _decode_utf8(raw: bytes, path: Path) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SecurityIngestError(f"{path.name} must be UTF-8 text") from exc


def _question_items_from_json(payload: Any) -> Iterator[dict[str, Any]]:
    items: Any = payload
    if isinstance(payload, Mapping):
        items = next(
            (payload[key] for key in ("questions", "questionnaire", "items", "controls") if key in payload),
            None,
        )
        if items is None:
            for key, value in payload.items():
                if isinstance(value, str):
                    yield {"id": str(key), "question": value}
            return
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return
    for index, item in enumerate(items, start=1):
        if isinstance(item, str):
            yield {"question": item}
        elif isinstance(item, Mapping):
            question = next(
                (item[key] for key in ("question", "prompt", "text", "name") if item.get(key)),
                "",
            )
            yield {
                "id": item.get("id") or item.get("key") or item.get("control_id") or "",
                "question": question,
                "priority": item.get("priority", "normal"),
            }
        else:
            yield {"id": f"Q-{index}", "question": ""}


def _question_items_from_text(text: str) -> Iterator[dict[str, str]]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|Q\s*\d+[:.)]\s*)", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"^question\s*:\s*", "", stripped, flags=re.IGNORECASE)
        if "?" not in stripped:
            continue
        question = stripped[: stripped.rfind("?") + 1].strip()
        if question:
            yield {"question": question}


def _statements_from_text(text: str, source_id: str) -> Iterator[EvidenceStatement]:
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or re.fullmatch(r"[-=_*`\s]+", stripped):
            continue
        cleaned = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", stripped)
        # Keep a physical line as the trust boundary. If any part of that line
        # is an instruction aimed at the assistant, the whole line is excluded
        # instead of allowing a later sentence on it to become evidence.
        if cleaned:
            yield EvidenceStatement(source_id=source_id, text=cleaned, line_start=line_number)


def _statements_from_json(payload: Any, source_id: str) -> Iterator[EvidenceStatement]:
    def walk(value: Any, json_path: str, key_name: str | None = None) -> Iterator[EvidenceStatement]:
        if isinstance(value, Mapping):
            for key in sorted(value, key=lambda item: str(item).casefold()):
                yield from walk(value[key], f"{json_path}.{key}", str(key))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                yield from walk(item, f"{json_path}[{index}]", key_name)
            return
        if key_name and key_name.casefold() in _METADATA_KEYS:
            return
        if value is None:
            rendered = "unknown"
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (str, int, float)):
            rendered = str(value).strip()
        else:
            return
        if not rendered:
            return
        if key_name and key_name.casefold() in _CONTENT_KEYS and isinstance(value, str):
            text_value = rendered
        elif key_name:
            label = re.sub(r"[_-]+", " ", key_name).strip()
            text_value = f"{label}: {rendered}"
        else:
            text_value = rendered
        yield EvidenceStatement(source_id=source_id, text=text_value, json_path=json_path)

    yield from walk(payload, "$")


def _json_title(payload: Any) -> str | None:
    if isinstance(payload, Mapping):
        for key in ("title", "name", "document_title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _text_title(text: str) -> str | None:
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        heading = re.sub(r"^#+\s*", "", stripped).strip()
        return heading[:200] if heading else None
    return None


def _date_from_json(payload: Any) -> tuple[str, str] | None:
    date_keys = {"date", "as_of", "asof", "effective", "effective_date", "generated", "generated_at", "updated", "updated_at"}

    def walk(value: Any) -> Iterator[tuple[str, Any]]:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).casefold() in date_keys:
                    yield str(key), child
                yield from walk(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                yield from walk(child)

    for key, value in walk(payload):
        normalized = _normalize_date(str(value))
        if normalized:
            return normalized, f"json:{key}"
    return None


def _date_from_text(text: str) -> tuple[str, str] | None:
    pattern = re.compile(
        r"(?im)^\s*(date|as of|effective|generated|last updated)\s*:\s*([^\r\n]+?)\s*$"
    )
    for match in pattern.finditer(text):
        normalized = _normalize_date(match.group(2))
        if normalized:
            return normalized, f"text:{match.group(1).lower().replace(' ', '_')}"
    return None


def _filesystem_date(path: Path) -> tuple[str, str]:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
    return modified, "filesystem_modified"


def _normalize_date(value: str) -> str | None:
    cleaned = value.strip()
    iso_match = re.search(r"\b(20\d{2}-[01]\d-[0-3]\d)\b", cleaned)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    for date_format in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_text(value: str) -> str:
    lowered = value.casefold().replace("_", "-")
    lowered = re.sub(r"[^a-z0-9./:-]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _content_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) > 1 and token not in _GENERIC_STOPWORDS
    }


def _excerpt(text: str, limit: int = 360) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _unique_statements(statements: Sequence[EvidenceStatement]) -> tuple[EvidenceStatement, ...]:
    result: list[EvidenceStatement] = []
    seen: set[tuple[str, str]] = set()
    for statement in statements:
        key = (statement.source_id, statement.normalized)
        if key not in seen:
            seen.add(key)
            result.append(statement)
    return tuple(result)


__all__ = [
    "EvidenceCatalog",
    "EvidenceCitation",
    "EvidenceStatement",
    "IgnoredFragment",
    "QuestionnaireAnswer",
    "QuestionnaireItem",
    "SecurityAssessmentReport",
    "SecurityIngestError",
    "SecurityIngestionEngine",
    "SourceDocument",
    "assess_questionnaire",
    "ingest_company_evidence",
    "load_questionnaire",
]
