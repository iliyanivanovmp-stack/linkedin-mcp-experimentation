from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extract_contacts import CsvSheet
from prepare_outreach_context import prepare_context


class PrepareOutreachContextTests(unittest.TestCase):
    def test_fills_exact_opener_and_solution_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companies.csv"
            path.write_text(
                "company_name,company_domain,audit_status,gap_reason,outreach_reason\n"
                "Acme,acme.com,outreach_ready,Demo form does not confirm,They are leaking demo intent\n",
                encoding="utf-8",
            )
            result = prepare_context(
                CsvSheet(path),
                {"qualified_statuses": ["outreach_ready"]},
                dry_run=False,
                limit=None,
            )
            self.assertEqual(result["updated"], 1)
            text = path.read_text(encoding="utf-8-sig")
            self.assertIn("opener", text)
            self.assertIn("solution_angle", text)
            self.assertIn("Quick note on the funnel gap for Acme", text)
            self.assertIn("clearer next steps", text)

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companies.csv"
            original = (
                "company_name,company_domain,audit_status,gap_reason,outreach_reason\n"
                "Acme,acme.com,outreach_ready,Demo form does not confirm,They are leaking demo intent\n"
            )
            path.write_text(original, encoding="utf-8")
            result = prepare_context(
                CsvSheet(path),
                {"qualified_statuses": ["outreach_ready"]},
                dry_run=True,
                limit=None,
            )
            self.assertEqual(result["updated"], 1)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
