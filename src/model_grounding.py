"""Fail-closed validation for optional model rewording.

The deterministic PayProof result is authoritative. A runtime model may make
that result easier to read, but it may not add or reassign quantities, change
units, reverse uncertainty, omit material limitations, add source references,
or introduce new domain claims.

This module deliberately prefers a deterministic fallback over accepting an
ambiguous paraphrase. It is a validation boundary, not a general-purpose
semantic entailment engine.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


MAX_MODEL_EXPLANATION_CHARS = 6_000

_IDENTIFIER_BOUNDARY = r"A-Za-z0-9_-"
_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")
_CONTROL_STATE_PATTERN = re.compile(
    r'(?i)["\']?(?:calculation|evidence_ids|focus_ids)["\']?\s*:',
)
_ANY_STATUS_FIELD_PATTERN = re.compile(r'(?i)["\']?status["\']?\s*:')
_STATUS_LABEL_PATTERN = re.compile(
    r"(?is)^\s*(?:[-*]\s*)?status\s*:\s*([a-z][a-z_-]*)\b[.\s:;-]*",
)
_REFERENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:SEC|SRC|CTRL|INV|TX|EMAIL|BANK|EXP|DOC)-[A-Za-z0-9_-]+(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

_DATE_PATTERN = re.compile(r"(?<![A-Za-z0-9])\d{4}-\d{2}-\d{2}(?![A-Za-z0-9])")
_MONEY_PREFIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<currency>USD|EUR|GBP|CAD|AUD|JPY|CNY|CHF|\$|€|£)\s*"
    r"(?P<amount>-?\d[\d,]*(?:\.\d+)?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_MONEY_SUFFIX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<amount>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<currency>USD|EUR|GBP|CAD|AUD|JPY|CNY|CHF)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_DIGIT_QUANTITY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<amount>-?\d[\d,]*(?:\.\d+)?)"
    r"\s*(?P<percent>%|percent|per\s+cent)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_NUMBER_WORD_VALUES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_NUMBER_WORD_ALTERNATIVES = sorted(
    [*_NUMBER_WORD_VALUES, *_NUMBER_SCALES],
    key=len,
    reverse=True,
)
_NUMBER_WORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(_NUMBER_WORD_ALTERNATIVES) + r")"
    r"(?:[\s-]+(?:and[\s-]+)?(?:" + "|".join(_NUMBER_WORD_ALTERNATIVES) + r"))*\b",
    re.IGNORECASE,
)

_CURRENCY_CODES = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "CAD": "CAD",
    "AUD": "AUD",
    "JPY": "JPY",
    "CNY": "CNY",
    "CHF": "CHF",
}

_ASSURANCE_PATTERNS = {
    "compliance": re.compile(r"\b(?:compliant|compliance)\b", re.IGNORECASE),
    "certification": re.compile(r"\b(?:certified|certification)\b", re.IGNORECASE),
    "verification": re.compile(r"\bverified\b", re.IGNORECASE),
    "security": re.compile(r"\bsecure\b", re.IGNORECASE),
    "safety": re.compile(r"\b(?:safe|guaranteed)\b", re.IGNORECASE),
    "requirements_met": re.compile(
        r"\b(?:meets?|satisf(?:y|ies|ied)|conforms?)\s+(?:the\s+)?(?:[A-Za-z0-9-]+\s+){0,3}(?:requirements?|standard)\b",
        re.IGNORECASE,
    ),
}

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "because", "been", "being",
        "but", "by", "can", "could", "did", "do", "does", "for", "from", "had",
        "has", "have", "having", "however", "if", "in", "into", "is", "it", "its",
        "may", "might", "must", "nevertheless", "of", "on", "or", "result", "remain",
        "remains", "remaining", "so", "source", "sources", "status", "still", "than",
        "that", "the", "their", "them", "then", "there", "these", "they", "this", "to",
        "was", "were", "while", "will", "with", "would", "your", "whether", "according",
        "indicates", "shows", "states",
    }
)

_CANONICAL_WORDS = {
    "cannot": "not",
    "partially": "partial",
    "incomplete": "incomplete",
    "incompletely": "incomplete",
    "requires": "require",
    "required": "require",
    "requirement": "require",
    "requirements": "require",
    "multi-factor": "mfa",
    "multifactor": "mfa",
    "authentication": "mfa",
    "identities": "identity",
    "accounts": "identity",
    "account": "identity",
    "users": "identity",
    "user": "identity",
    "principals": "identity",
    "principal": "identity",
    "enrolled": "enroll",
    "enrollment": "enroll",
    "enrollments": "enroll",
    "exceptions": "exempt",
    "exception": "exempt",
    "exemptions": "exempt",
    "exemption": "exempt",
    "conflicts": "conflict",
    "conflicting": "conflict",
    "contradiction": "conflict",
    "contradictions": "conflict",
    "contradicts": "conflict",
    "disagrees": "conflict",
    "disagreement": "conflict",
    "documentation": "evidence",
    "documents": "evidence",
    "document": "evidence",
    "records": "evidence",
    "record": "evidence",
    "reports": "report",
    "establishes": "support",
    "established": "support",
    "establish": "support",
    "substantiates": "support",
    "substantiated": "support",
    "substantiate": "support",
    "supported": "support",
    "supports": "support",
    "currently": "current",
    "loaded": "current",
    "universal": "all",
    "every": "all",
    "maintains": "coverage",
    "maintain": "coverage",
    "effective": "coverage",
    "across": "coverage",
    "collected": "dated",
    "dated": "dated",
    "expired": "expired",
    "expires": "expired",
    "lapsed": "expired",
    "certainty": "confidence",
    "written": "policy",
    "policies": "policy",
    "observations": "observed",
    "failures": "failed",
    "failure": "failed",
    "failing": "failed",
}

_LIMITATION_GROUPS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("conflict", (
        re.compile(r"\bconflict(?:s|ing|ed)?\b", re.IGNORECASE),
        re.compile(r"\bcontradict(?:s|ed|ing|ion|ions)?\b", re.IGNORECASE),
        re.compile(r"\bdisagree(?:s|d|ment)?\b", re.IGNORECASE),
        re.compile(r"\binconsisten(?:t|cy|cies)\b", re.IGNORECASE),
        re.compile(r"\b(?:does?|do|did)\s+not\s+(?:fully\s+)?agree\b", re.IGNORECASE),
    )),
    ("exemption", (
        re.compile(r"\bexempt(?:ed|ion|ions)?\b", re.IGNORECASE),
        re.compile(r"\bexception(?:s)?\b", re.IGNORECASE),
    )),
    ("missing", (
        re.compile(r"\bmissing\b", re.IGNORECASE),
        re.compile(r"\babsent\b", re.IGNORECASE),
        re.compile(r"\bunavailable\b", re.IGNORECASE),
    )),
    ("incomplete", (
        re.compile(r"\bincomplete\b", re.IGNORECASE),
        re.compile(r"\bnot\s+(?:fully\s+)?complete\b", re.IGNORECASE),
    )),
    ("documentation_gap", (
        re.compile(r"\bnot\s+documented\b", re.IGNORECASE),
        re.compile(r"\bno\s+attached\s+evidence\b", re.IGNORECASE),
        re.compile(r"\bevidence\s+is\s+not\s+attached\b", re.IGNORECASE),
    )),
    ("failure", (
        re.compile(r"\bfailed\b", re.IGNORECASE),
        re.compile(r"\bfailure(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bnot\s+(?:currently\s+)?operating\b", re.IGNORECASE),
    )),
    ("unresolved", (
        re.compile(r"\b(?:unresolved|outstanding)\b", re.IGNORECASE),
        re.compile(r"\bremains?\s+open\b", re.IGNORECASE),
    )),
    ("expired", (
        re.compile(r"\b(?:expired|lapsed|out[- ]of[- ]date)\b", re.IGNORECASE),
    )),
    ("unmatched", (
        re.compile(r"\bunmatched\b", re.IGNORECASE),
        re.compile(r"\bnot\s+(?:yet\s+)?matched\b", re.IGNORECASE),
    )),
    ("review_required", (
        re.compile(r"\brequires?\s+review\b", re.IGNORECASE),
        re.compile(r"\breview\s+(?:the\s+)?(?:underlying\s+)?[A-Za-z-]+\s+first\b", re.IGNORECASE),
        re.compile(r"\bnot\s+(?:automatically\s+)?confirmed\b", re.IGNORECASE),
    )),
    ("not_a_conclusion", (
        re.compile(r"\bnot\s+(?:proof|a\s+conclusion)\b", re.IGNORECASE),
        re.compile(r"\bsuggestion,?\s+not\s+a\s+conclusion\b", re.IGNORECASE),
    )),
)


def _status(calculation: Mapping[str, Any] | None, answer: str) -> str:
    if calculation:
        explicit = str(calculation.get("status") or "").strip().lower()
        if explicit:
            return explicit
    normalized = answer.strip().lower()
    if normalized.startswith("unknown"):
        return "unknown"
    if normalized.startswith("partially") or normalized.startswith("partial"):
        return "partial"
    if "conflicting evidence" in normalized or "evidence conflict" in normalized:
        return "conflict"
    return "supported"


def _canonical_status(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return {
        "partially": "partial",
        "incomplete": "partial",
        "failed": "gap",
        "failure": "gap",
        "unverified": "review",
    }.get(normalized, normalized)


def _evidence_regex(evidence_id: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY}]){re.escape(evidence_id)}(?![{_IDENTIFIER_BOUNDARY}])",
        re.IGNORECASE,
    )


def _mask_evidence_ids(value: str, evidence_ids: Sequence[str]) -> str:
    masked = value
    for evidence_id in sorted({str(item) for item in evidence_ids if str(item)}, key=len, reverse=True):
        masked = _evidence_regex(evidence_id).sub(lambda match: " " * len(match.group(0)), masked)
    return masked


def _span_is_occupied(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and span[1] > start for start, end in occupied)


def _decimal_key(raw: str) -> str:
    try:
        value = Decimal(raw.replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("invalid quantity") from exc
    if value == 0:
        value = abs(value)
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _parse_number_words(raw: str) -> int:
    words = [word for word in re.split(r"[\s-]+", raw.casefold()) if word and word != "and"]
    total = 0
    current = 0
    for word in words:
        if word in _NUMBER_WORD_VALUES:
            current += _NUMBER_WORD_VALUES[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        elif word in {"thousand", "million", "billion"}:
            total += max(current, 1) * _NUMBER_SCALES[word]
            current = 0
    return total + current


def _fact_quantities(value: str, evidence_ids: Sequence[str]) -> tuple[tuple[str, str], ...]:
    """Extract quantities in source order, with dates/currencies/units bound."""

    text = _mask_evidence_ids(value, evidence_ids)
    found: list[tuple[int, tuple[str, str]]] = []
    occupied: list[tuple[int, int]] = []

    for match in _DATE_PATTERN.finditer(text):
        occupied.append(match.span())
        found.append((match.start(), ("date", match.group(0))))

    for pattern in (_MONEY_PREFIX_PATTERN, _MONEY_SUFFIX_PATTERN):
        for match in pattern.finditer(text):
            if _span_is_occupied(match.span(), occupied):
                continue
            currency = _CURRENCY_CODES[match.group("currency").upper() if match.group("currency").isalpha() else match.group("currency")]
            occupied.append(match.span())
            found.append((match.start(), (f"money:{currency}", _decimal_key(match.group("amount")))))

    for match in _DIGIT_QUANTITY_PATTERN.finditer(text):
        if _span_is_occupied(match.span(), occupied):
            continue
        occupied.append(match.span())
        unit = "percent" if match.group("percent") else "number"
        found.append((match.start(), (unit, _decimal_key(match.group("amount")))))

    for match in _NUMBER_WORD_PATTERN.finditer(text):
        if _span_is_occupied(match.span(), occupied):
            continue
        occupied.append(match.span())
        found.append((match.start(), ("number", str(_parse_number_words(match.group(0))))))

    found.sort(key=lambda item: item[0])
    return tuple(item for _, item in found)


def _is_negated_or_resolved(value: str, start: int, end: int) -> bool:
    prefix = value[max(0, start - 55):start].casefold()
    suffix = value[end:end + 55].casefold()
    if re.search(r"\b(?:no|not|never|without|zero)\b(?:\W+\w+){0,3}\W*$", prefix):
        return True
    if re.match(
        r"\W*(?:(?:is|are|was|were|has|have|had|been)\W+){0,3}"
        r"(?:resolved|closed|cleared|fixed|gone|absent|removed|ended)\b",
        suffix,
    ):
        return True
    return False


def _has_positive_pattern(value: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    for pattern in patterns:
        for match in pattern.finditer(value):
            phrase = match.group(0).casefold()
            # These phrases express an absence as the limitation itself.
            absence_is_limitation = phrase.startswith(("not documented", "no attached", "evidence is not", "not operating", "not matched", "not confirmed", "not proof", "not a conclusion"))
            if absence_is_limitation or not _is_negated_or_resolved(value, match.start(), match.end()):
                return True
    return False


def _claim_polarity(value: str, start: int) -> str:
    prefix = value[max(0, start - 90):start].casefold()
    clause = re.split(r"[.!?;]", prefix)[-1]
    if re.search(
        r"\b(?:unknown|unclear|insufficient)\b|"
        r"\b(?:does?|do|did|can|could)\s+not\s+(?:establish|support|confirm|determine)\b|"
        r"\bcannot\s+(?:establish|support|confirm|determine)\b|"
        r"\bnot\s+(?:established|supported|confirmed)\b",
        clause,
    ):
        return "uncertain"
    if re.search(r"\b(?:no|not|never|without)\b(?:\W+\w+){0,4}\W*$", clause):
        return "negative"
    return "positive"


def _assurance_claims(value: str) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    for claim, pattern in _ASSURANCE_PATTERNS.items():
        for match in pattern.finditer(value):
            claims.add((claim, _claim_polarity(value, match.start())))
    return claims


def _canonical_concepts(value: str, evidence_ids: Sequence[str]) -> set[str]:
    text = _mask_evidence_ids(value, evidence_ids)
    concepts: set[str] = set()
    for raw_word in _WORD_PATTERN.findall(text):
        word = raw_word.casefold()
        if word in _STOPWORDS:
            continue
        canonical = _CANONICAL_WORDS.get(word, word)
        if canonical in _STOPWORDS or canonical in _NUMBER_WORD_VALUES or canonical in _NUMBER_SCALES:
            continue
        concepts.add(canonical)
    return concepts


def _unknown_is_retired(value: str) -> bool:
    return bool(re.search(
        r"(?is)^\s*(?:status\s*:\s*unknown[.\s:;-]*)?unknown\b[^.!?]{0,70}"
        r"\b(?:was|prior|previous|earlier|old|outdated|no\s+longer)\b",
        value,
    ))


def validate_model_rewording(
    candidate: Any,
    authoritative_answer: str,
    evidence_ids: Sequence[str],
    calculation: Mapping[str, Any] | None = None,
) -> tuple[bool, str, str | None]:
    """Return ``(accepted, reason, normalized_candidate)``.

    Reasons are fixed diagnostic codes so rejected model text is never echoed
    into logs or the interface.
    """

    if not isinstance(candidate, str):
        return False, "non_text_output", None
    normalized = "\n".join(line.rstrip() for line in candidate.strip().splitlines()).strip()
    if not normalized:
        return False, "empty_output", None
    if len(normalized) > MAX_MODEL_EXPLANATION_CHARS:
        return False, "oversized_output", None
    if len(normalized) > max(1_500, len(authoritative_answer) * 3):
        return False, "disproportionate_output", None
    if any(ord(character) < 32 and character not in "\n\r\t" for character in normalized):
        return False, "control_characters", None

    stripped = normalized.lstrip()
    if stripped.startswith("```"):
        return False, "structured_override", None
    if stripped[:1] in {"{", "["}:
        try:
            if isinstance(json.loads(stripped), (dict, list)):
                return False, "structured_override", None
        except json.JSONDecodeError:
            # A malformed structured-looking response is not safe prose.
            return False, "structured_override", None
    if _CONTROL_STATE_PATTERN.search(normalized):
        return False, "structured_override", None

    result_status = _canonical_status(_status(calculation, authoritative_answer))
    status_label_match = _STATUS_LABEL_PATTERN.match(normalized)
    label_status: str | None = None
    structure_remainder = normalized
    if status_label_match:
        label_status = _canonical_status(status_label_match.group(1))
        if label_status != result_status:
            return False, "status_override", None
        structure_remainder = normalized[status_label_match.end():]
    if _ANY_STATUS_FIELD_PATTERN.search(structure_remainder):
        return False, "structured_override", None

    expected_evidence = [str(item) for item in evidence_ids if str(item)]
    for evidence_id in expected_evidence:
        if not _evidence_regex(evidence_id).search(normalized):
            return False, "missing_evidence_reference", None

    allowed_references = {item.casefold() for item in expected_evidence}
    allowed_references.update(match.group(0).casefold() for match in _REFERENCE_PATTERN.finditer(authoritative_answer))
    candidate_references = {match.group(0).casefold() for match in _REFERENCE_PATTERN.finditer(normalized)}
    if candidate_references - allowed_references:
        return False, "unsupported_evidence_reference", None

    try:
        authoritative_quantities = _fact_quantities(authoritative_answer, expected_evidence)
        candidate_quantities = _fact_quantities(normalized, expected_evidence)
    except ValueError:
        return False, "invalid_quantity", None
    if candidate_quantities != authoritative_quantities:
        authoritative_set = set(authoritative_quantities)
        candidate_set = set(candidate_quantities)
        if candidate_set - authoritative_set:
            return False, "invented_or_changed_quantity", None
        if authoritative_set - candidate_set or len(candidate_quantities) < len(authoritative_quantities):
            return False, "missing_authoritative_quantity", None
        return False, "quantity_reassigned", None

    lower_candidate = normalized.casefold()
    lower_authoritative = authoritative_answer.casefold()

    if result_status == "unknown":
        conveys_unknown = label_status == "unknown" or bool(re.match(r"(?is)^\s*unknown\b", normalized))
        if not conveys_unknown or _unknown_is_retired(normalized):
            return False, "uncertainty_removed", None
    elif result_status == "partial":
        partial_patterns = (
            re.compile(r"\bpartial(?:ly)?\b", re.IGNORECASE),
            re.compile(r"\bincomplete\b", re.IGNORECASE),
            re.compile(r"\bgap\b", re.IGNORECASE),
            re.compile(r"\bconflict(?:s|ing|ed)?\b", re.IGNORECASE),
            re.compile(r"\bexception(?:s)?\b", re.IGNORECASE),
        )
        if label_status != "partial" and not _has_positive_pattern(normalized, partial_patterns):
            return False, "uncertainty_removed", None
    elif result_status == "conflict":
        conflict_patterns = _LIMITATION_GROUPS[0][1]
        if label_status != "conflict" and not _has_positive_pattern(normalized, conflict_patterns):
            return False, "uncertainty_removed", None
    elif result_status == "gap":
        gap_patterns = (
            re.compile(r"\bgap\b", re.IGNORECASE),
            re.compile(r"\bfailed\b", re.IGNORECASE),
            re.compile(r"\bfailure(?:s)?\b", re.IGNORECASE),
            re.compile(r"\bnot\s+(?:currently\s+)?operating\b", re.IGNORECASE),
            re.compile(r"\boverdue\b", re.IGNORECASE),
        )
        if label_status != "gap" and not _has_positive_pattern(normalized, gap_patterns):
            return False, "uncertainty_removed", None
    elif result_status == "review":
        review_patterns = (
            re.compile(r"\breview\b", re.IGNORECASE),
            re.compile(r"\b(?:unclear|incomplete|unknown|unresolved)\b", re.IGNORECASE),
            re.compile(r"\bremains?\s+open\b", re.IGNORECASE),
        )
        if label_status != "review" and not _has_positive_pattern(normalized, review_patterns):
            return False, "uncertainty_removed", None

    for _, patterns in _LIMITATION_GROUPS:
        if _has_positive_pattern(authoritative_answer, patterns) and not _has_positive_pattern(normalized, patterns):
            return False, "limitation_removed", None

    authoritative_assurances = _assurance_claims(authoritative_answer)
    candidate_assurances = _assurance_claims(normalized)
    if candidate_assurances - authoritative_assurances:
        return False, "unsupported_assurance", None

    authoritative_concepts = _canonical_concepts(authoritative_answer, expected_evidence)
    candidate_concepts = _canonical_concepts(normalized, expected_evidence)
    novel_concepts = candidate_concepts - authoritative_concepts
    if novel_concepts:
        return False, "unsupported_new_content", None
    if authoritative_concepts:
        coverage = len(authoritative_concepts & candidate_concepts) / len(authoritative_concepts)
        if coverage < 0.72:
            return False, "insufficient_fact_coverage", None

    # If the authoritative response explicitly limits its conclusion, a model
    # may not turn that into an action or retrospective assertion by adding a
    # temporal resolution cue even when it repeats the original vocabulary.
    if re.search(r"\b(?:now|formerly|previously|used\s+to)\b", lower_candidate) and not re.search(
        r"\b(?:now|formerly|previously|used\s+to)\b",
        lower_authoritative,
    ):
        return False, "unsupported_temporal_change", None

    return True, "accepted", normalized


__all__ = ["MAX_MODEL_EXPLANATION_CHARS", "validate_model_rewording"]
