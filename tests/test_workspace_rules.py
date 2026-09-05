from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.workspace_rules import (
    discover_intake_json,
    new_company_workspace_id,
    normalize_company_name,
    scoped_external_id,
    validate_intake_root,
    validate_workspace_id,
)


class WorkspaceRuleTests(unittest.TestCase):
    def test_company_name_and_generated_id_are_bounded(self) -> None:
        self.assertEqual(normalize_company_name("  Acme   Repair  "), "Acme Repair")
        workspace_id = new_company_workspace_id("Acme Repair")
        self.assertTrue(workspace_id.startswith("company-acme-repair-"))
        self.assertEqual(validate_workspace_id(workspace_id), workspace_id)
        with self.assertRaises(ValueError):
            normalize_company_name(" ")
        with self.assertRaises(ValueError):
            validate_workspace_id("../company")

    def test_external_ids_are_company_scoped_but_demo_ids_stay_stable(self) -> None:
        self.assertEqual(scoped_external_id("business", "EXP-1"), "EXP-1")
        self.assertEqual(scoped_external_id("personal", "TX-1"), "TX-1")
        first = scoped_external_id("company-first-12345678", "EXP-1")
        second = scoped_external_id("company-second-12345678", "EXP-1")
        self.assertNotEqual(first, second)
        self.assertTrue(first.endswith("--EXP-1"))

    def test_custom_intake_root_can_scan_subfolders_with_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="payproof-intake-root-") as folder:
            root = Path(folder)
            nested = root / "department" / "receipts"
            nested.mkdir(parents=True)
            (root / "top.json").write_text("{}", encoding="utf-8")
            (nested / "nested.json").write_text("{}", encoding="utf-8")
            validated = validate_intake_root(root)
            flat, flat_errors = discover_intake_json(validated, include_subfolders=False)
            recursive, recursive_errors = discover_intake_json(validated, include_subfolders=True)
        self.assertEqual([path.name for path in flat], ["top.json"])
        self.assertEqual({path.name for path in recursive}, {"top.json", "nested.json"})
        self.assertEqual(flat_errors, [])
        self.assertEqual(recursive_errors, [])

    def test_broad_or_missing_intake_roots_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_intake_root(Path("Z:/this-folder-does-not-exist"))
        with self.assertRaises(ValueError):
            validate_intake_root(Path(Path.cwd().anchor))


if __name__ == "__main__":
    unittest.main(verbosity=2)
