#!/usr/bin/env python3
"""Tests for CCE-12 (SUPP-190): --after / --before date filters.

``ClaudeConversationExtractor.find_sessions`` takes optional ``after`` and
``before`` arguments (ISO dates, ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM:SS``)
and filters the returned list of session paths by their filesystem
modification time. The CLI exposes matching ``--after`` / ``--before``
flags that are applied to every command that walks sessions.
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extract_claude_logs import ClaudeConversationExtractor  # noqa: E402


def _touch_with_mtime(path: Path, when: datetime) -> None:
    """Create ``path`` (including parents) and set its mtime to ``when``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    epoch = when.replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (epoch, epoch))


class TestFindSessionsDateFilters(unittest.TestCase):
    """find_sessions honors ``after`` and ``before`` arguments."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake_claude = self.tmp / ".claude" / "projects"
        # Three sessions at known-old, mid-old, and fresh mtimes.
        now = datetime(2026, 4, 10, 12, 0, 0)
        self.now = now
        self.fresh = self.fake_claude / "proj" / "fresh.jsonl"
        self.mid = self.fake_claude / "proj" / "mid.jsonl"
        self.old = self.fake_claude / "proj" / "old.jsonl"
        _touch_with_mtime(self.fresh, now - timedelta(hours=1))
        _touch_with_mtime(self.mid, now - timedelta(days=5))
        _touch_with_mtime(self.old, now - timedelta(days=60))

        self.extractor = ClaudeConversationExtractor(self.tmp / "out")
        self.extractor.claude_dir = self.fake_claude

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_filter_returns_all(self):
        found = self.extractor.find_sessions()
        self.assertEqual(sorted(p.name for p in found),
                         ["fresh.jsonl", "mid.jsonl", "old.jsonl"])

    def test_after_filter_keeps_only_recent(self):
        cutoff = (self.now - timedelta(days=2)).strftime("%Y-%m-%d")
        found = self.extractor.find_sessions(after=cutoff)
        self.assertEqual([p.name for p in found], ["fresh.jsonl"])

    def test_before_filter_keeps_only_older(self):
        cutoff = (self.now - timedelta(days=2)).strftime("%Y-%m-%d")
        found = self.extractor.find_sessions(before=cutoff)
        self.assertEqual(
            sorted(p.name for p in found),
            ["mid.jsonl", "old.jsonl"],
        )

    def test_combined_after_and_before_window(self):
        after = (self.now - timedelta(days=10)).strftime("%Y-%m-%d")
        before = (self.now - timedelta(days=2)).strftime("%Y-%m-%d")
        found = self.extractor.find_sessions(after=after, before=before)
        self.assertEqual([p.name for p in found], ["mid.jsonl"])

    def test_iso_datetime_format_is_accepted(self):
        cutoff = (self.now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
        found = self.extractor.find_sessions(after=cutoff)
        self.assertEqual([p.name for p in found], ["fresh.jsonl"])

    def test_invalid_date_string_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.extractor.find_sessions(after="notadate")
        self.assertIn("Invalid", str(ctx.exception))


class TestCliDateFilters(unittest.TestCase):
    """``--after`` / ``--before`` flags route through to find_sessions."""

    def test_cli_flags_are_forwarded_to_find_sessions(self):
        from extract_claude_logs import main

        captured = {}

        def fake_find(self, project_path=None, after=None, before=None):
            captured["after"] = after
            captured["before"] = before
            return []  # Empty list short-circuits extract_multiple

        with patch("sys.argv", ["prog", "--extract", "1",
                                "--after", "2026-03-01",
                                "--before", "2026-04-01"]):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                fake_find,
            ):
                with patch("builtins.print"):
                    main()

        self.assertEqual(captured.get("after"), "2026-03-01")
        self.assertEqual(captured.get("before"), "2026-04-01")


if __name__ == "__main__":
    unittest.main()
