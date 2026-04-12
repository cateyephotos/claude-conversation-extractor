#!/usr/bin/env python3
"""Tests for CCE-16 (SUPP-194): ``claude-extract --install-hook``.

Ships a CLI command that writes a Claude Code ``Stop`` hook into
``~/.claude/settings.json`` so every session exit runs
``claude-extract --recent 1 --detailed`` and archives the session
outside ``~/.claude/projects/``, which Claude Code may prune.

Requirements:
- Create ``settings.json`` if it doesn't exist.
- Merge into an existing ``settings.json`` without clobbering other
  hooks or unrelated config keys.
- Prompt before writing; declining is a no-op.
- Re-running is idempotent (does not duplicate the hook).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extract_claude_logs import install_hook  # noqa: E402


class TestInstallHook(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = self.tmp / "settings.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_creates_file_when_absent_on_yes(self):
        self.assertFalse(self.settings.exists())
        with patch("builtins.input", return_value="y"):
            result = install_hook(settings_path=self.settings)
        self.assertTrue(result)
        self.assertTrue(self.settings.exists())
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertIn("hooks", data)
        self.assertIn("Stop", data["hooks"])
        # Shape matches Claude Code hooks schema: a list of groups,
        # each with its own inner "hooks" list of {type, command}.
        self.assertIsInstance(data["hooks"]["Stop"], list)
        self.assertGreaterEqual(len(data["hooks"]["Stop"]), 1)
        inner = data["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(inner["type"], "command")
        self.assertIn("claude-extract", inner["command"])
        self.assertIn("--recent 1", inner["command"])
        self.assertIn("--detailed", inner["command"])

    def test_declining_prompt_writes_nothing(self):
        with patch("builtins.input", return_value="n"):
            result = install_hook(settings_path=self.settings)
        self.assertFalse(result)
        self.assertFalse(self.settings.exists())

    def test_preserves_unrelated_keys(self):
        self.settings.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Read", "Edit"]},
                    "theme": "dark",
                }
            ),
            encoding="utf-8",
        )
        with patch("builtins.input", return_value="y"):
            result = install_hook(settings_path=self.settings)
        self.assertTrue(result)
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        # Pre-existing keys are kept.
        self.assertEqual(data["permissions"], {"allow": ["Read", "Edit"]})
        self.assertEqual(data["theme"], "dark")
        # New hook section exists.
        self.assertIn("hooks", data)

    def test_preserves_existing_hooks_of_other_events(self):
        self.settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {"type": "command", "command": "echo pre"}
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        with patch("builtins.input", return_value="y"):
            result = install_hook(settings_path=self.settings)
        self.assertTrue(result)
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        # PreToolUse hook was not touched.
        self.assertIn("PreToolUse", data["hooks"])
        pre = data["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(pre["command"], "echo pre")
        # Stop hook was added alongside.
        self.assertIn("Stop", data["hooks"])

    def test_is_idempotent(self):
        with patch("builtins.input", return_value="y"):
            install_hook(settings_path=self.settings)
            install_hook(settings_path=self.settings)
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        # Running twice should not duplicate the command entry.
        inner_commands = [
            h["command"]
            for group in data["hooks"]["Stop"]
            for h in group.get("hooks", [])
            if "claude-extract" in h.get("command", "")
        ]
        self.assertEqual(len(inner_commands), 1, inner_commands)

    def test_returns_false_when_already_installed_without_reprompting(self):
        # First install.
        with patch("builtins.input", return_value="y"):
            install_hook(settings_path=self.settings)
        # Second install: input() must not be called because the hook
        # is already present. Patching it to raise verifies that.
        with patch("builtins.input", side_effect=AssertionError("prompted")):
            result = install_hook(settings_path=self.settings)
        self.assertFalse(result)


class TestCliInstallHookFlag(unittest.TestCase):
    def test_cli_flag_invokes_install_hook(self):
        from extract_claude_logs import main

        with patch("sys.argv", ["prog", "--install-hook"]):
            with patch(
                "extract_claude_logs.install_hook",
                return_value=True,
            ) as mock_install:
                with patch("builtins.print"):
                    main()
        mock_install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
