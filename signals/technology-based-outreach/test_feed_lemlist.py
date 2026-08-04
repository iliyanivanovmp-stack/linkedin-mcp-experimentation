from __future__ import annotations

import unittest

from feed_lemlist import (
    attempt_count,
    build_payload,
    custom_variables,
    retryable_row,
    variable_aliases,
)


class FeedLemlistRetryTests(unittest.TestCase):
    def test_transient_failures_retry_up_to_three_attempts(self) -> None:
        self.assertTrue(retryable_row("failed", 1))
        self.assertTrue(retryable_row("failed", 2))
        self.assertFalse(retryable_row("failed", 3))

    def test_validation_failures_are_terminal(self) -> None:
        self.assertFalse(retryable_row("validation_failed", 1))

    def test_malformed_attempt_count_recovers_safely(self) -> None:
        self.assertEqual(attempt_count("not-a-number"), 0)

    def test_contrarian_hook_is_derived_from_technologies(self) -> None:
        aliases = variable_aliases({
            "custom_variables": {"contrarianHook": ["contrarian_hook"]},
        })
        variables = custom_variables({"technologies": "HubSpot, Slack"}, aliases)
        self.assertIn("HubSpot and Slack", variables["contrarianHook"])

    def test_missing_message_variable_fails_validation(self) -> None:
        aliases = variable_aliases({
            "custom_variables": {
                "technologies": ["technologies"],
                "automationOpportunity1": ["automation_opportunity_1"],
            },
        })
        _, missing = build_payload(
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "company_name": "Analytical Engines",
                "company_domain": "analytical.example",
                "source_url": "https://analytical.example",
                "icebreaker": "Saw your team is using HubSpot and Slack.",
                "technologies": "HubSpot, Slack",
            },
            "Europe/Sofia",
            aliases,
            ["technologies", "automationOpportunity1"],
        )
        self.assertIn("custom variable automationOpportunity1", missing)


if __name__ == "__main__":
    unittest.main()
