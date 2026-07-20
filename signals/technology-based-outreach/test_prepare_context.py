from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from extract_contacts import MemorySheet


MODULE_PATH = Path(__file__).with_name("prepare_context.py")
SPEC = importlib.util.spec_from_file_location("technology_prepare_context", MODULE_PATH)
assert SPEC and SPEC.loader
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


class PrepareContextTests(unittest.TestCase):
    def test_clickup_slack_copy_is_short_and_specific(self) -> None:
        result = context.generated_context({"selected_outreach_tools": "Slack, ClickUp"})
        self.assertEqual(result["technologies"], "Slack, ClickUp")
        self.assertEqual(result["opener"], "Saw your team is using Slack and ClickUp.")
        self.assertIn("new ClickUp leads", result["automation_opportunity_1"])
        self.assertIn("Slack actions", result["automation_opportunity_2"])
        self.assertIn("one workflow", result["outreach_angle"])

    def test_json_tool_list_is_supported(self) -> None:
        result = context.generated_context({"selected_outreach_tools": '["HubSpot", "Calendly", "Apollo"]'})
        self.assertEqual(result["technologies"], "HubSpot, Calendly, Apollo")

    def test_no_tools_produces_no_context(self) -> None:
        self.assertEqual(context.generated_context({}), {})

    def test_researched_automation_examples_are_preserved(self) -> None:
        result = context.generated_context({
            "selected_outreach_tools": "HubSpot, Calendly, Apollo",
            "automation_example_1": "Route Apollo-qualified accounts into HubSpot with an owner assigned.",
            "automation_example_2": "Update HubSpot when a qualified buyer books through Calendly.",
            "automation_example_3": "Alert the account owner with booking and account context.",
        })
        self.assertEqual(
            result["automation_opportunity_1"],
            "Route Apollo-qualified accounts into HubSpot with an owner assigned.",
        )
        self.assertIn("books through Calendly", result["automation_opportunity_2"])

    def test_blank_confidence_does_not_become_outreach_ready(self) -> None:
        rows = [
            {"status": "queued", "confidence": "", "selected_outreach_tools": "Slack, ClickUp"},
            {"status": "queued", "confidence": "medium", "selected_outreach_tools": "Slack, ClickUp"},
        ]
        sheet = MemorySheet(headers=list(rows[0]), rows=rows)
        result = context.prepare_context(
            sheet,
            {"qualified_confidences": ["high", "medium"]},
            dry_run=False,
            limit=None,
        )
        self.assertEqual(result["updated"], 1)
        self.assertEqual(sheet.rows()[0].data["status"], "queued")
        self.assertEqual(sheet.rows()[1].data["status"], "outreach_ready")


if __name__ == "__main__":
    unittest.main()
