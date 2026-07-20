from __future__ import annotations

import unittest

from feed_lemlist import attempt_count, retryable_row


class FeedLemlistRetryTests(unittest.TestCase):
    def test_transient_failures_retry_up_to_three_attempts(self) -> None:
        self.assertTrue(retryable_row("failed", 1))
        self.assertTrue(retryable_row("failed", 2))
        self.assertFalse(retryable_row("failed", 3))

    def test_validation_failures_are_terminal(self) -> None:
        self.assertFalse(retryable_row("validation_failed", 1))

    def test_malformed_attempt_count_recovers_safely(self) -> None:
        self.assertEqual(attempt_count("not-a-number"), 0)


if __name__ == "__main__":
    unittest.main()
