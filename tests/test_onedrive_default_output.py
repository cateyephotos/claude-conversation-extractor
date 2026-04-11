#!/usr/bin/env python3
"""Tests for the Windows OneDrive-aware default output directory logic.

Covers CCE-5 (SUPP-183): on Windows 11 with Known Folder Move enabled, the
``~/Desktop`` path resolves under an ``OneDrive`` folder, which would cause
the extractor to silently upload conversation history to OneDrive. The
default output selection must skip that path and prefer ``Documents``.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src directory to path before local imports (mirrors conftest.py so
# this file can also be run directly via ``python -m unittest``).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extract_claude_logs import (  # noqa: E402
    ClaudeConversationExtractor,
    _default_output_candidates,
    _is_onedrive_path,
)


class TestIsOneDrivePath(unittest.TestCase):
    """Unit tests for the :func:`_is_onedrive_path` helper."""

    def test_detects_plain_onedrive_component(self):
        p = Path("C:/Users/alice/OneDrive/Desktop/Claude logs")
        self.assertTrue(_is_onedrive_path(p))

    def test_detects_tenant_branded_onedrive(self):
        # Enterprise tenants typically land in "OneDrive - Contoso".
        p = Path("C:/Users/alice/OneDrive - Contoso/Desktop/Claude logs")
        self.assertTrue(_is_onedrive_path(p))

    def test_detects_hyphenated_onedrive(self):
        # Some tenants use the hyphenated form without spaces.
        p = Path("C:/Users/alice/OneDrive-Personal/Desktop/Claude logs")
        self.assertTrue(_is_onedrive_path(p))

    def test_detects_case_insensitively(self):
        p = Path("C:/Users/alice/onedrive/Desktop/Claude logs")
        self.assertTrue(_is_onedrive_path(p))

    def test_plain_desktop_is_not_onedrive(self):
        p = Path("C:/Users/alice/Desktop/Claude logs")
        self.assertFalse(_is_onedrive_path(p))

    def test_unrelated_path_component_does_not_match(self):
        # Legitimate folder whose name happens to contain the substring
        # "onedrive" should not match — we only accept exact matches or
        # the ``OneDrive - *`` / ``OneDrive-*`` tenant forms.
        p = Path("C:/Users/alice/my-onedrive-backups/Claude logs")
        self.assertFalse(_is_onedrive_path(p))


class TestDefaultOutputCandidatesWindows(unittest.TestCase):
    """Platform-specific tests for the candidate path ordering on Windows."""

    def test_documents_precedes_desktop_when_desktop_is_safe(self):
        """Even on a Desktop-is-safe Windows, Documents should be tried first."""
        fake_home = Path("C:/Users/alice")
        with patch("extract_claude_logs.sys.platform", "win32"), patch(
            "extract_claude_logs.Path.home", return_value=fake_home
        ), patch("extract_claude_logs._is_onedrive_path", return_value=False):
            candidates = _default_output_candidates()

        # Documents/Claude logs must be the first candidate on Windows.
        self.assertEqual(candidates[0], fake_home / "Documents" / "Claude logs")
        # Desktop/Claude logs must still appear somewhere in the list when
        # it is NOT OneDrive-redirected, so users with a plain Desktop keep
        # backwards-compatible behavior.
        self.assertIn(fake_home / "Desktop" / "Claude logs", candidates)

    def test_onedrive_redirected_desktop_is_skipped_and_notice_is_printed(self):
        """OneDrive-redirected Desktop must be dropped from candidates."""
        fake_home = Path("C:/Users/alice")
        with patch("extract_claude_logs.sys.platform", "win32"), patch(
            "extract_claude_logs.Path.home", return_value=fake_home
        ), patch(
            "extract_claude_logs._is_onedrive_path", return_value=True
        ), patch(
            "builtins.print"
        ) as mock_print:
            candidates = _default_output_candidates()

        self.assertNotIn(
            fake_home / "Desktop" / "Claude logs",
            candidates,
            "Desktop under OneDrive must not appear in default candidates",
        )
        # Documents must still be first.
        self.assertEqual(candidates[0], fake_home / "Documents" / "Claude logs")
        # A one-line notice must be emitted so the user understands the skip.
        print_calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(
            any("OneDrive" in call for call in print_calls),
            f"Expected a OneDrive notice to be printed, got: {print_calls}",
        )

    def test_non_windows_keeps_desktop_first(self):
        """macOS/Linux must keep the historical Desktop-first ordering."""
        fake_home = Path("/Users/alice")
        with patch("extract_claude_logs.sys.platform", "darwin"), patch(
            "extract_claude_logs.Path.home", return_value=fake_home
        ):
            candidates = _default_output_candidates()

        self.assertEqual(candidates[0], fake_home / "Desktop" / "Claude logs")
        self.assertIn(fake_home / "Documents" / "Claude logs", candidates)


class TestExtractorIntegration(unittest.TestCase):
    """End-to-end test: an extractor constructed on a simulated Windows host
    with an OneDrive-redirected Desktop must land in Documents, not Desktop.
    """

    def setUp(self):
        self._fake_home = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self._fake_home, ignore_errors=True)

    def test_extractor_lands_in_documents_when_desktop_is_onedrive(self):
        documents_target = self._fake_home / "Documents" / "Claude logs"
        with patch("extract_claude_logs.sys.platform", "win32"), patch(
            "extract_claude_logs.Path.home", return_value=self._fake_home
        ), patch(
            "extract_claude_logs._is_onedrive_path",
            side_effect=lambda p: "Desktop" in str(p),
        ):
            extractor = ClaudeConversationExtractor(None)

        self.assertEqual(extractor.output_dir, documents_target)
        self.assertTrue(documents_target.exists())


if __name__ == "__main__":
    unittest.main()
