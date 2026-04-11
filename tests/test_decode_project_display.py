#!/usr/bin/env python3
"""Tests for CCE-10 (SUPP-188): _decode_project_name is wired into the
session listings shown by ``list_recent_sessions`` and the interactive UI.

Before CCE-10 the listing did::

    project = session.parent.name.replace('-', ' ').strip()
    if project.startswith("Users"):
        ...

which produced unreadable output like ``C  code myapp`` for the
encoded folder name ``C--code-myapp``. After CCE-10 the listing
should route through ``_decode_project_name`` so the user sees the
real path ``C:/code/myapp``.

The fixture names used here (``C--code-myapp``, ``/code/myapp``) are
arbitrary — the test creates a fake folder with that name inside a
``tempfile.mkdtemp()`` temp dir and never touches the real filesystem.
The decoder is purely string-level; nothing in the extractor or the
test is tied to a specific username, drive, or path layout.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extract_claude_logs import (  # noqa: E402
    ClaudeConversationExtractor,
    _decode_project_name,
)


def _write_fake_session(session_path: Path) -> None:
    """Write a minimal but valid JSONL file the extractor can read."""
    session_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "type": "user",
        "uuid": "u1",
        "parentUuid": None,
        "isSidechain": False,
        "cwd": "C:/code/myapp",
        "gitBranch": "main",
        "version": "2.1.3",
        "entrypoint": "claude-desktop",
        "userType": "external",
        "timestamp": "2026-04-10T00:00:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        },
    }
    session_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")


class TestListRecentSessionsDecodesProjectName(unittest.TestCase):
    """``list_recent_sessions`` must display decoded project folder names."""

    def setUp(self):
        self.tmp_root = Path(tempfile.mkdtemp())
        # Emulate ~/.claude/projects/<encoded>/<session>.jsonl with a
        # generic fixture name. The folder lives inside self.tmp_root,
        # not the real home directory.
        self.encoded_project = "C--code-myapp"
        self.fake_claude = self.tmp_root / ".claude" / "projects"
        session_path = (
            self.fake_claude / self.encoded_project / "abcdef1234567890.jsonl"
        )
        _write_fake_session(session_path)
        self.session_path = session_path

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_decoded_project_name_appears_in_listing(self):
        """The decoded path must appear in the printed listing."""
        # Build an extractor pointed at our fake home; output_dir must be
        # a writable temp path so __init__ does not touch the real home.
        extractor = ClaudeConversationExtractor(self.tmp_root / "out")
        # Redirect the extractor's claude_dir to our fake fixture.
        extractor.claude_dir = self.fake_claude

        with patch("builtins.print") as mock_print:
            extractor.list_recent_sessions()

        printed = "\n".join(str(call) for call in mock_print.call_args_list)
        expected = _decode_project_name(self.encoded_project)
        self.assertIn(
            expected,
            printed,
            f"Expected decoded project path {expected!r} in listing output, "
            f"got:\n{printed}",
        )
        # And it must NOT fall back to the old hyphen-replacement display
        # (``C  code myapp``) which was ambiguous and ugly.
        self.assertNotIn("C  code myapp", printed)


class TestInteractiveUiDecodesProjectName(unittest.TestCase):
    """The interactive UI's ``show_sessions_menu`` must also decode names."""

    def setUp(self):
        self.tmp_root = Path(tempfile.mkdtemp())
        self.encoded_project = "C--code-myapp"
        self.fake_claude = self.tmp_root / ".claude" / "projects"
        session_path = (
            self.fake_claude / self.encoded_project / "abcdef1234567890.jsonl"
        )
        _write_fake_session(session_path)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_interactive_listing_uses_decoded_name(self):
        # Import lazily so that if interactive_ui ever gains import-time
        # side effects they don't affect other tests.
        from interactive_ui import InteractiveUI

        # InteractiveUI(output_dir) builds its own extractor; we then
        # redirect that extractor's claude_dir to the fake projects tree
        # so only our fixture session is discovered.
        ui = InteractiveUI(str(self.tmp_root / "out"))
        ui.extractor.claude_dir = self.fake_claude

        # Stub input() so the menu loop exits immediately.
        with patch("builtins.input", return_value="Q"), patch(
            "builtins.print"
        ) as mock_print:
            ui.show_sessions_menu()

        printed = "\n".join(str(call) for call in mock_print.call_args_list)
        expected = _decode_project_name(self.encoded_project)
        self.assertIn(
            expected[:30],  # the UI truncates to 30 chars
            printed,
            f"Expected decoded project prefix in interactive listing, "
            f"got:\n{printed}",
        )


if __name__ == "__main__":
    unittest.main()
