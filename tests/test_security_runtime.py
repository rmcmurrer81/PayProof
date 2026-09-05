from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.security_runtime import build_security_view, questionnaire_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SecurityRuntimeTests(unittest.TestCase):
    def test_real_synthetic_packet_drives_dashboard_and_questionnaire(self) -> None:
        view = build_security_view(
            PROJECT_ROOT / "data" / "security_questionnaire" / "SYNTHETIC-security-questionnaire.json",
            PROJECT_ROOT / "data" / "security_evidence",
        )
        self.assertTrue(view["available"])
        self.assertEqual(view["metrics"]["controls_assessed"], 7)
        self.assertEqual(view["metrics"]["gaps"], 2)
        self.assertEqual(view["metrics"]["needs_review"], 4)
        self.assertEqual(view["metrics"]["evidence_sources"], 8)
        self.assertFalse(any("MANIFEST" in item["source"] for item in view["evidence"]))
        self.assertEqual(view["answers"][0]["status"], "conflict")
        self.assertTrue(all(item["citations"] for item in view["answers"]))
        self.assertTrue(all(
            citation["source_id"] in {source["id"] for source in view["evidence"]}
            for answer in view["answers"]
            for citation in answer["citations"]
        ))
        questionnaire = questionnaire_payload(view)
        self.assertEqual(questionnaire["questionnaire"]["question_count"], 7)
        self.assertTrue(questionnaire["generated_from_evidence"])

    def test_missing_packet_fails_closed_without_claims(self) -> None:
        with tempfile.TemporaryDirectory(prefix="payproof-security-runtime-") as folder:
            view = build_security_view(Path(folder) / "missing.json", folder)
        self.assertFalse(view["available"])
        self.assertEqual(view["controls"], [])
        self.assertEqual(view["evidence"], [])
        self.assertEqual(view["metrics"]["controls_assessed"], 0)
        self.assertIn("unknown", questionnaire_payload(view)["golden_rule"].casefold())

    def test_control_and_graph_evidence_are_the_same_dynamic_ids(self) -> None:
        view = build_security_view(
            PROJECT_ROOT / "data" / "security_questionnaire" / "SYNTHETIC-security-questionnaire.json",
            PROJECT_ROOT / "data" / "security_evidence",
        )
        graph_ids = {node["id"] for node in view["graph"]["nodes"]}
        for control in view["controls"]:
            self.assertIn(f"control:{control['id']}", graph_ids)
            for source_id in control["evidence"]:
                self.assertIn(f"security:{source_id}", graph_ids)

    def test_reassessment_reflects_changed_evidence_without_code_edit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="payproof-security-reassess-") as folder:
            root = Path(folder)
            questionnaire = root / "questionnaire.json"
            evidence = root / "evidence"
            evidence.mkdir()
            questionnaire.write_text(json.dumps({
                "questions": [{"id": "Q-MFA", "question": "Is MFA enabled?"}],
            }), encoding="utf-8")
            source = evidence / "identity.txt"
            source.write_text("Generated: 2026-09-01\nMFA is enabled for all production identities.\n", encoding="utf-8")
            before = build_security_view(questionnaire, evidence)
            source.write_text("Generated: 2026-09-02\nMFA status is not documented.\n", encoding="utf-8")
            after = build_security_view(questionnaire, evidence)

        self.assertEqual(before["answers"][0]["status"], "supported")
        self.assertEqual(after["answers"][0]["status"], "unknown")
        self.assertNotEqual(before["answers"][0]["answer"], after["answers"][0]["answer"])
        self.assertNotEqual(before["evidence"][0]["sha256"], after["evidence"][0]["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
