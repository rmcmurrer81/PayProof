from __future__ import annotations

import unittest

from src.model_grounding import validate_model_rewording


class ModelGroundingValidatorUnitTests(unittest.TestCase):
    def assert_rejected(
        self,
        candidate: str,
        authoritative: str,
        evidence_ids: list[str] | None = None,
        calculation: dict | None = None,
    ) -> None:
        accepted, reason, normalized = validate_model_rewording(
            candidate,
            authoritative,
            evidence_ids or [],
            calculation,
        )
        self.assertFalse(accepted, f"unsafe candidate was accepted ({reason}): {normalized}")

    def assert_accepted(
        self,
        candidate: str,
        authoritative: str,
        evidence_ids: list[str] | None = None,
        calculation: dict | None = None,
    ) -> None:
        accepted, reason, _ = validate_model_rewording(
            candidate,
            authoritative,
            evidence_ids or [],
            calculation,
        )
        self.assertTrue(accepted, f"grounded candidate was rejected: {reason}")

    @staticmethod
    def partial_answer() -> str:
        return (
            "Partially. Policy requires MFA, but 16 of 18 production identities are enrolled; "
            "2 service accounts are exempt. Confidence is 96%. The written requirement and "
            "observed enrollment conflict. Evidence SEC-POL-001 and SEC-INF-001."
        )

    @staticmethod
    def partial_calculation() -> dict:
        return {
            "status": "partial",
            "enrolled": 16,
            "identities": 18,
            "exempt_service_accounts": 2,
            "confidence": 96,
        }

    def test_accepts_equivalent_bounded_rewording(self) -> None:
        authoritative = self.partial_answer()
        candidate = (
            "Partially: 16 of 18 production identities are enrolled in MFA, while 2 service "
            "accounts remain exempt. Confidence is 96%, and observed enrollment conflicts with "
            "the written policy. Evidence: SEC-POL-001 and SEC-INF-001."
        )
        self.assert_accepted(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            self.partial_calculation(),
        )

    def test_rejects_negated_conflict_marker(self) -> None:
        authoritative = self.partial_answer()
        candidate = (
            "Partially. Policy requires MFA for 16 of 18 production identities; 2 service "
            "accounts are exempt. Confidence is 96%. There is no conflict: the written "
            "requirement and observed enrollment fully agree. Evidence SEC-POL-001 and SEC-INF-001."
        )
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            self.partial_calculation(),
        )

    def test_rejects_positive_certification_when_source_says_not_certified(self) -> None:
        authoritative = (
            "Unknown. Meridian is not certified for SOC 2. Evidence SEC-AUDIT-001. "
            "Confidence is 70%."
        )
        candidate = (
            "Unknown was the prior assessment. Meridian is now certified for SOC 2. "
            "Evidence SEC-AUDIT-001. Confidence is 70%."
        )
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-AUDIT-001"],
            {"status": "unknown", "confidence": 70},
        )

    def test_rejects_currency_substitution_for_same_number(self) -> None:
        authoritative = "Invoice INV-001 totals USD 125.00."
        candidate = "Invoice INV-001 totals EUR 125.00."
        self.assert_rejected(
            candidate,
            authoritative,
            ["INV-001"],
            {"status": "supported", "amount_cents": 12500, "currency": "USD"},
        )

    def test_rejects_reassignment_of_authoritative_numbers(self) -> None:
        authoritative = (
            "Partially. Policy requires MFA, but 16 of 18 production identities are enrolled; "
            "2 service accounts are exempt. The confidence score is 96. The written requirement "
            "and observed enrollment conflict. Evidence SEC-POL-001 and SEC-INF-001."
        )
        candidate = (
            "Partially. Policy requires MFA, but 96 of 18 production identities are enrolled; "
            "2 service accounts are exempt. The confidence score is 16. The written requirement and "
            "observed enrollment conflict. Evidence SEC-POL-001 and SEC-INF-001."
        )
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            self.partial_calculation(),
        )

    def test_rejects_omission_of_word_form_quantity_and_qualifier(self) -> None:
        authoritative = (
            "Partially. Policy requires MFA, but 16 of 18 production identities are enrolled; "
            "two service accounts are exempt. Confidence is 96%. The written requirement and "
            "observed enrollment conflict. Evidence SEC-POL-001 and SEC-INF-001."
        )
        candidate = (
            "Partially. Policy requires MFA. 16 of 18 production identities are enrolled. "
            "Confidence is 96%. The policy and observed enrollment conflict. "
            "Evidence SEC-POL-001 and SEC-INF-001."
        )
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            {"status": "partial", "confidence": 96, "enrolled": 16, "identities": 18},
        )

    def test_rejects_evidence_id_embedded_in_a_different_identifier(self) -> None:
        authoritative = "Unknown. Source SEC-POL-001 is incomplete."
        candidate = "Unknown. Source NOT-SEC-POL-001-FAKE is incomplete."
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-POL-001"],
            {"status": "unknown"},
        )

    def test_rejects_new_spelled_out_number(self) -> None:
        authoritative = "Unknown. Current records do not establish the remediation cost."
        candidate = (
            "Unknown. Current records do not establish the remediation cost. "
            "Remediation will cost one million dollars."
        )
        self.assert_rejected(candidate, authoritative, calculation={"status": "unknown"})

    def test_rejects_appended_qualitative_claim_despite_high_word_overlap(self) -> None:
        authoritative = self.partial_answer()
        candidate = authoritative + " All contractor administrator access is unrestricted."
        self.assert_rejected(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            self.partial_calculation(),
        )

    def test_accepts_required_numeric_evidence_id_not_repeated_in_source_prose(self) -> None:
        authoritative = "Unknown. Current policy evidence is incomplete."
        candidate = "Unknown. Current policy evidence is incomplete. Source: SEC-POL-001."
        self.assert_accepted(
            candidate,
            authoritative,
            ["SEC-POL-001"],
            {"status": "unknown"},
        )

    def test_accepts_semantically_equivalent_low_lexical_overlap(self) -> None:
        authoritative = (
            "Unknown. The currently loaded documentation does not establish whether the "
            "organization maintains effective multi-factor authentication across every privileged "
            "production account. Evidence SEC-IAM-001 was collected on 2026-08-31."
        )
        candidate = (
            "Unknown: records cannot substantiate universal MFA coverage for all privileged "
            "production users. Evidence SEC-IAM-001 is dated 2026-08-31."
        )
        self.assert_accepted(
            candidate,
            authoritative,
            ["SEC-IAM-001"],
            {"status": "unknown", "collected_on": "2026-08-31"},
        )

    def test_accepts_matching_plain_text_status_label(self) -> None:
        authoritative = self.partial_answer()
        candidate = (
            "Status: partial. Policy requires MFA, but 16 of 18 production identities are enrolled; "
            "2 service accounts are exempt. Confidence is 96%. The written requirement and observed "
            "enrollment conflict. Evidence SEC-POL-001 and SEC-INF-001."
        )
        self.assert_accepted(
            candidate,
            authoritative,
            ["SEC-POL-001", "SEC-INF-001"],
            self.partial_calculation(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
