"""Fail-closed adapter from security evidence ingestion to PayProof's UI API.

The deterministic ingestion engine is the authority.  This module only shapes
its output for the dashboard, record inspector, graph, questionnaire, and chat.
It deliberately returns no positive claim if the packet cannot be assessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .security_ingest import SecurityIngestError, SecurityIngestionEngine


CONTROL_METADATA = {
    "mfa": ("CTRL-MFA", "Multi-factor authentication"),
    "customer_data_storage": ("CTRL-STORAGE", "Customer data storage"),
    "encryption_at_rest": ("CTRL-ENCRYPT", "Encryption at rest"),
    "backups": ("CTRL-BACKUP", "Backup operations"),
    "vulnerability_scanning": ("CTRL-SCAN", "Vulnerability scanning"),
    "production_access": ("CTRL-ACCESS", "Production access"),
    "offboarding": ("CTRL-OFFBOARD", "Employee offboarding"),
}

STATUS_TO_UI = {
    "supported": "clear",
    "partial": "partial",
    "conflict": "gap",
    "unknown": "review",
}

QUESTION_PRIORITY = {"critical": 0, "high": 1, "normal": 2, "low": 3}
STATUS_PRIORITY = {"conflict": 0, "unknown": 1, "partial": 2, "supported": 3}


def _source_type(filename: str) -> str:
    lowered = filename.casefold()
    for needle, source_type in (
        ("policy", "policy"),
        ("identity", "infrastructure"),
        ("inventory", "infrastructure"),
        ("backup", "operations"),
        ("scan", "scan"),
        ("roster", "employee"),
        ("message", "message"),
    ):
        if needle in lowered:
            return source_type
    return "document"


def _statement_preview(source: dict[str, Any]) -> str:
    statements = source.get("statements") or []
    for item in statements:
        text = str(item.get("text") or "").strip()
        lowered = text.casefold()
        if not text or lowered.startswith("synthetic ") or lowered.startswith("generated:"):
            continue
        if lowered.startswith("effective:") or lowered.startswith("as of:"):
            continue
        if len(text) == len(text.upper()) and len(text) < 100:
            continue
        return text[:320]
    return "No reviewed statement preview is available; open the source record for provenance."


def _unavailable_view(error_code: str) -> dict[str, Any]:
    return {
        "available": False,
        "error_code": error_code,
        "notice": "Security assessment unavailable. No claim was inferred from an unreadable or invalid packet.",
        "controls": [],
        "evidence": [],
        "metrics": {
            "controls_assessed": 0,
            "gaps": 0,
            "needs_review": 0,
            "evidence_sources": 0,
            "supported": 0,
            "unknown": 0,
        },
        "graph": {"nodes": [], "edges": []},
        "questionnaire": None,
        "answers": [],
        "ingest_errors": [],
    }


def build_security_view(
    questionnaire_path: str | Path,
    evidence_folder: str | Path,
) -> dict[str, Any]:
    """Build a bounded, compatible dashboard view from the reviewed packet."""

    questionnaire = Path(questionnaire_path)
    evidence_root = Path(evidence_folder)
    metadata_paths = tuple(evidence_root.glob("*MANIFEST*.json"))
    try:
        report = SecurityIngestionEngine(evidence_root).assess(
            questionnaire,
            exclude_paths=metadata_paths,
        )
        payload = report.to_dict(include_source_statements=True)
    except (OSError, SecurityIngestError, ValueError):
        return _unavailable_view("assessment_failed")

    source_rows: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for source in payload["evidence_catalog"]["sources"]:
        source_id = str(source["id"])
        source_ids.add(source_id)
        source_rows.append({
            "id": source_id,
            "type": _source_type(str(source["filename"])),
            "title": source["title"],
            "source": source["filename"],
            "statement": _statement_preview(source),
            "as_of": source["source_date"],
            "sha256": source["sha256"],
            "date_basis": source["date_basis"],
            "statement_count": source["statement_count"],
            "ignored_untrusted_count": source["ignored_untrusted_count"],
        })

    question_priority = {
        question.id: QUESTION_PRIORITY.get(question.priority, QUESTION_PRIORITY["normal"])
        for question in report.questions
    }
    controls: list[dict[str, Any]] = []
    raw_answers: list[dict[str, Any]] = []
    for answer in payload["answers"]:
        raw_status = str(answer["status"])
        internal_control = str(answer.get("control_id") or answer["question_id"])
        control_id, control_name = CONTROL_METADATA.get(
            internal_control,
            (f"CTRL-{str(answer['question_id']).upper()}", str(answer["question"])),
        )
        evidence_ids = [item for item in answer["evidence_ids"] if item in source_ids]
        citations = [item for item in answer["citations"] if item["source_id"] in source_ids]
        confidence = max(0, min(100, round(float(answer["confidence_score"]) * 100)))
        limitation = answer.get("follow_up") or answer["confidence_basis"]
        controls.append({
            "id": control_id,
            "engine_control_id": answer.get("control_id"),
            "question_id": answer["question_id"],
            "name": control_name,
            "question": answer["question"],
            "status": STATUS_TO_UI.get(raw_status, "review"),
            "assessment_status": raw_status,
            "confidence": confidence,
            "confidence_basis": answer["confidence_basis"],
            "answer": answer["answer"],
            "evidence": evidence_ids,
            "citations": citations,
            "contradiction": limitation,
            "follow_up": answer.get("follow_up"),
        })
        raw_answers.append({
            **answer,
            "control_id": control_id,
            "engine_control_id": answer.get("control_id"),
            "name": control_name,
            "confidence": confidence,
            "conflict_or_gap": limitation,
            "evidence_ids": evidence_ids,
            "citations": citations,
        })

    order = {
        answer["question_id"]: (
            STATUS_PRIORITY.get(str(answer["status"]), 9),
            question_priority.get(answer["question_id"], 9),
            str(answer["question"]),
        )
        for answer in raw_answers
    }
    raw_answers.sort(key=lambda answer: order[answer["question_id"]])

    nodes: list[dict[str, Any]] = [
        {"id": "workspace:security", "label": "Meridian Security", "type": "workspace", "risk": "clear", "size": 26}
    ]
    edges: list[dict[str, Any]] = []
    risk_map = {"clear": "clear", "partial": "review", "review": "review", "gap": "high"}
    for control in controls:
        risk = risk_map[control["status"]]
        control_node = f"control:{control['id']}"
        nodes.append({
            "id": control_node,
            "label": control["name"],
            "type": "control",
            "risk": risk,
            "size": 13,
            "confidence": control["confidence"],
            "assessment_status": control["assessment_status"],
        })
        edges.append({"source": "workspace:security", "target": control_node, "type": "assessment", "risk": risk, "amount": 0})
    for source in source_rows:
        source_node = f"security:{source['id']}"
        nodes.append({
            "id": source_node,
            "label": source["title"],
            "type": source["type"],
            "risk": "clear",
            "size": 8,
            "source": source["source"],
        })
        for control in controls:
            if source["id"] in control["evidence"]:
                edges.append({
                    "source": f"control:{control['id']}",
                    "target": source_node,
                    "type": "evidence",
                    "risk": risk_map[control["status"]],
                    "amount": 0,
                })

    summary = payload["summary"]
    return {
        "available": True,
        "controls": controls,
        "evidence": source_rows,
        "metrics": {
            "controls_assessed": len(controls),
            "gaps": summary["conflict"],
            "needs_review": summary["partial"] + summary["unknown"],
            "evidence_sources": len(source_rows),
            "supported": summary["supported"],
            "unknown": summary["unknown"],
        },
        "graph": {"nodes": nodes, "edges": edges},
        "questionnaire": payload["questionnaire"],
        "answers": raw_answers,
        "summary": summary,
        "ingest_errors": payload["evidence_catalog"]["errors"],
    }


def questionnaire_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": "Meridian Works (synthetic example)",
        "generated_from_evidence": bool(view.get("available")),
        "golden_rule": "Unavailable claims remain unknown; conflicts remain conflicts.",
        "available": bool(view.get("available")),
        "questionnaire": view.get("questionnaire"),
        "summary": view.get("summary", {}),
        "answers": view.get("answers", []),
        "ingest_errors": view.get("ingest_errors", []),
        **({"error_code": view["error_code"], "notice": view["notice"]} if not view.get("available") else {}),
    }


__all__ = [
    "CONTROL_METADATA",
    "build_security_view",
    "questionnaire_payload",
]
