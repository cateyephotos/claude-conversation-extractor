# Changelog - Claude Conversation Extractor Updates

All notable changes to the Claude Code export tool will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-04-10 - Current JSONL Schema Support & Claude Code Desktop Adaptation

### Fixed
- **Detailed mode now captures tool_result blocks.** User messages were
  parsed without `detailed=True`, silently dropping every `tool_result`
  block (which lives inside `user.message.content[]` in the current
  Claude Code schema). Detailed exports on a typical session now include
  ~70+ previously-missing tool_result blocks.
- **Removed dead top-level `tool_use` / `tool_result` / `system` handling.**
  These branches expected a pre-v2.0 format where tool calls were stored
  as their own JSONL entries; current Claude Code embeds them inside
  message content arrays instead. The old branches never fired on modern
  data.
- **Filename UUID truncation raised from 8 to 12 chars** to reduce
  collisions when exporting many sessions.

### Added
- **Thinking block support.** `type: "thinking"` content blocks from
  extended-thinking models are now extracted and rendered:
  - Markdown: collapsed `<details><summary>Thinking</summary>` block
  - HTML: collapsible purple-bordered panel
  - JSON: dedicated `thinking` role
  - Terminal viewer: labeled section
- **Tool call / tool result pairing.** Detailed exports now match each
  `tool_use` block to its `tool_result` by `tool_use_id` and render them
  inline, even when other blocks appear between them in the raw JSONL.
- **Session metadata in exports.** `cwd`, `git_branch`, `claude_version`,
  `entrypoint`, and `user_type` are extracted from the JSONL envelope
  and surfaced as:
  - Markdown: YAML frontmatter + human-readable header block
  - HTML: dedicated metadata panel
  - JSON: top-level `metadata` object
- **New public method `extract_session(path, detailed=False)`** returning
  a `(messages, metadata)` tuple. Existing `extract_conversation()` is
  preserved as a backward-compatible wrapper.
- **Tool payload truncation.** `tool_use` inputs and `tool_result`
  contents are capped at 2000 chars in detailed mode with a clear
  `[truncated N chars]` marker, preventing runaway exports on large
  Read/Write/Edit calls.
- **Noise filtering.** Top-level `queue-operation`, `last-prompt`, and
  `attachment` entries are explicitly skipped rather than parsed and
  ignored.
- **Project folder decoder.** Helper `_decode_project_name()` converts
  `~/.claude/projects/` encoded folder names (`C--Users-thomasc8` →
  `C:/Users/thomasc8`) for display.

### Changed
- `save_as_markdown`, `save_as_json`, `save_as_html`, and
  `save_conversation` all accept an optional `metadata` parameter.
- `extract_multiple` and the `--search` + `claude-start` search flows
  now read session metadata and thread it to the writers.
- Unknown content block types are preserved as `role: "unknown"` messages
  in detailed mode instead of being silently dropped — future Claude
  Code schema additions will appear in exports instead of disappearing.

### Known Limitations
- Sidechain sessions (files under `**/subagents/` or entries with
  `isSidechain: true`) are still mixed into the main session list;
  separation is tracked for 1.3.0.
- `parentUuid` branching (conversation rewinds) is not yet reconstructed
  as a tree.
- System hook telemetry is only exposed in `--detailed` mode.

## [1.1.1] - 2025-08-28 - View Conversations & Better Search Experience

### Added
- **Conversation Viewer** - View conversations directly in terminal without extracting files
- **JSON export format** - Export conversations as structured JSON with metadata (Issue #6)
- **HTML export format** - Beautiful web-viewable format with syntax highlighting (Issue #6)
- **--format flag** - Choose between markdown, json, or html output formats
- **--detailed flag** - Include tool use, MCP responses, and system messages (Issue #19)
- **claude-search command** - Search and view conversations without extraction
- Complete transcript export showing all conversation details as in Ctrl+R view
- Pagination support for viewing long conversations

### Fixed
- Fixed missing `claude-logs` command in PyPI package (Issue #31)
- Fixed arrow key handling in real-time search (no more weird characters)
- Fixed search functionality to VIEW conversations instead of forcing extraction
- All search commands now allow viewing before optional extraction
- All three commands now work properly: `claude-extract`, `claude-logs`, `claude-start`
- Updated documentation to clarify `claude-start` vs `claude-extract` usage

### Changed
- `claude-start` launches interactive UI with ASCII art logo and real-time search
- `claude-extract` runs standard CLI interface
- `claude-search` now offers view/extract options instead of auto-extracting
- Interactive UI search (option F) now views conversations instead of extracting
- `--search` flag now allows viewing conversations before extraction
- Simplified README with clear command distinctions at the top

## [Unreleased] - Features to Export Claude Code Conversations

### Planned
- Export Claude conversations to PDF format
- Export Claude Code logs to HTML with syntax highlighting
- Chrome extension to add export button to Claude Code
- Automated daily backup of Claude conversations
- Integration with Obsidian for Claude chat archiving

## [1.1.0] - 2025-06-05 - Interactive UI to Export Claude Conversations

### Added - New Ways to Extract Claude Code Logs

- **Interactive UI** for easy Claude conversation extraction
- New `claude-start` command for quick access to Claude export
- Support for `--interactive` / `-i` flag to launch UI
- Support for `--export logs` syntax to extract Claude sessions
- Beautiful ASCII art banner when exporting Claude Code
- Interactive selection of multiple Claude conversations
- Progress tracking during batch Claude exports
- Colorful terminal output showing Claude extraction status
- Professional badges showing downloads and GitHub stars
- Comprehensive test suite for reliable Claude export

### Changed - Improved Claude Code Export Experience

- Updated setup.py to include interactive Claude export UI
- Enhanced entry points with claude-start shortcut
- Improved code formatting for better Claude extractor maintenance
- Better error messages when Claude Code logs not found

### Fixed - Claude Export Bug Fixes

- Line length issues in Claude conversation formatting
- Trailing whitespace in exported Claude markdown files
- Version consistency for Claude Conversation Extractor
- Windows compatibility for Claude Code export paths

## [1.0.0] - 2025-05-25 - First Tool to Export Claude Code Conversations

### 🎉 Initial Release - The ONLY Claude Code Export Solution

- **First tool** to extract conversations from Claude Code
- Finds Claude logs in ~/.claude/projects automatically
- Converts Claude JSONL to clean, readable markdown
- List all Claude Code sessions with metadata
- Extract single Claude conversations with `--extract N`
- Export recent Claude chats with `--recent N`  
- Backup all Claude conversations with `--all`
- Custom output directory for Claude exports
- Zero dependencies - pure Python Claude extractor
- Cross-platform Claude Code export (Windows/Mac/Linux)

---

**Why This Tool Exists**: Claude Code stores all conversations locally but provides NO export functionality. Users were losing valuable AI programming sessions. This tool solves that problem.

**Keywords**: claude conversation extractor changelog, claude code export updates, extract claude logs version history, backup claude sessions releases, claude jsonl to markdown changelog