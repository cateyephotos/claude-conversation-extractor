# Linear Project Brief — Claude Code Desktop Adaptation

Paste this into Linear to create the project and its issues. Fields follow
Linear's standard project/issue shape (Name, Description, Priority, Labels,
Cycle, Estimate). Generated 2026-04-10.

---

## Project

**Name:** Claude Code Desktop Adaptation
**Lead:** Dustin Kirby (@ZeroSumQuant)
**Status:** In Progress
**Target date:** TBD

**Summary:**
Adapt `claude-conversation-extractor` to the current Claude Code JSONL
schema (v2.1.x+) and make it a first-class citizen inside Claude Code
Desktop. Includes schema fixes (shipped in 1.2.0), new integrations
(skill wrapper, MCP server, post-session hook), and quality-of-life
improvements for power users who want their session history to become
queryable memory.

**Description (longer form):**
The tool was written against a pre-v2.0 Claude Code JSONL format where
tool calls and thinking blocks lived as top-level entries. Current Claude
Code Desktop embeds tool_use blocks inside `assistant.message.content[]`
and tool_result blocks inside `user.message.content[]`, plus emits a new
`thinking` block type for extended-thinking models. The 1.2.0 release
(this cycle) fixes the schema drift and adds session metadata to exports.
Subsequent cycles add agent-native integrations so past sessions can be
referenced from inside a running Claude Code session.

**Milestones:**
1. **1.2.0 — Schema fix (DONE in patch branch):** detailed mode captures
   tool_result + thinking + session metadata; tool_use paired with
   tool_result by id; noise filtered.
2. **1.2.1 — Windows polish + CLAUDE.md integration:** fix OneDrive path
   resolution, document schema assumptions, add CLAUDE.md file.
3. **1.3.0 — Sidechain separation + branching:** distinguish subagent
   sessions, reconstruct `parentUuid` trees for rewound conversations.
4. **1.4.0 — Agent integrations:** skill wrapper, MCP stdio server,
   post-session auto-archive hook, `--watch` mode.
5. **1.5.0 — Memory pipeline:** `/graphify` integration so past sessions
   feed a knowledge graph automatically.

**Labels to create:** `schema`, `windows`, `mcp`, `skill`, `hooks`,
`integration`, `qol`, `docs`, `tests`

---

## Issues

### CCE-1 — [DONE] Rewrite extraction for current JSONL schema
**Priority:** Urgent
**Labels:** schema
**Estimate:** 5
**Cycle:** 1.2.0

Current Claude Code Desktop (v2.1.x) stores `tool_use` blocks inside
`assistant.message.content[]` and `tool_result` blocks inside
`user.message.content[]`. The extractor's detailed mode silently dropped
all tool_results and all extended-thinking content because:

1. User-message content was parsed without `detailed=True`, so
   tool_result blocks inside user messages were never walked.
2. `_extract_text_content` had no handler for `type=="thinking"` blocks.
3. The top-level `type=="tool_use"` / `type=="tool_result"` /
   `type=="system"` branches at `src/extract_claude_logs.py:118-152` were
   dead code — they expected a pre-v2.0 format.

**Acceptance criteria:**
- [x] `extract_session(path, detailed=True)` returns tool_use, tool_result,
  and thinking blocks as first-class messages.
- [x] `extract_conversation` preserved as backward-compat wrapper.
- [x] All three writers (md/json/html) render the new block types.
- [x] Smoke test against a real `~/.claude/projects/*.jsonl` file
  confirms tool_use and tool_result counts match the raw JSONL.
- [x] Zero regressions vs `main` in existing test suite.

**Status at handoff:** Patch applied in working tree, 1.2.0 version
bumped, CHANGELOG updated. Not yet committed/tagged/published.

---

### CCE-2 — [DONE] Add session envelope metadata to exports
**Priority:** High
**Labels:** schema
**Estimate:** 3
**Cycle:** 1.2.0

Current JSONL entries carry `cwd`, `gitBranch`, `version`, `entrypoint`,
and `userType` on every user/assistant entry. Surface these in exports
so downstream tools can filter sessions by working directory, Claude
Code version, or entrypoint (`claude-desktop` vs CLI).

**Acceptance criteria:**
- [x] `extract_session` returns a `(messages, metadata)` tuple.
- [x] Markdown export: YAML frontmatter + human-readable header block.
- [x] HTML export: dedicated metadata panel styled to match the header.
- [x] JSON export: top-level `metadata` object.
- [x] Lightweight `extract_session_metadata()` helper for callers that
  already have messages from elsewhere.

---

### CCE-3 — [DONE] Pair tool_use with tool_result by tool_use_id
**Priority:** High
**Labels:** schema
**Estimate:** 2
**Cycle:** 1.2.0

In the raw JSONL, tool_use and its matching tool_result can be separated
by other blocks (thinking, text). Rendering them inline as a pair makes
detailed exports actually readable.

**Acceptance criteria:**
- [x] Markdown and HTML writers build a `tool_use_id → tool_result` map
  on entry and render the result inline after each tool_use.
- [x] Orphaned tool_results (no matching tool_use in the session) still
  render as standalone blocks.
- [x] Error results (`is_error: true`) render with a distinct label.

---

### CCE-4 — [DONE] Truncate oversized tool payloads
**Priority:** Medium
**Labels:** schema, qol
**Estimate:** 1
**Cycle:** 1.2.0

Read/Write/Edit tool calls with large file contents produced multi-MB
detailed exports. Cap `tool_use` input and `tool_result` content at
2000 chars with a `[truncated N chars]` marker. The full payload is
still available in the original JSONL for anyone who needs it.

---

### CCE-5 — Fix default Windows output directory for OneDrive users
**Priority:** Medium
**Labels:** windows, qol
**Estimate:** 2
**Cycle:** 1.2.1

On Windows 11 with OneDrive-redirected Desktop, the default output
candidate `~/Desktop/Claude logs` (src/extract_claude_logs.py:30)
resolves into OneDrive's synced folder, which can trigger upload of
potentially sensitive conversation history.

**Acceptance criteria:**
- [ ] On `sys.platform == "win32"`, prefer `Documents/Claude logs` ahead
  of `Desktop/Claude logs`.
- [ ] Detect OneDrive redirection by checking if `~/Desktop` resolves
  under an `OneDrive*` path and skip it if so.
- [ ] Emit a one-line notice when falling back because of OneDrive.
- [ ] Add a test that mocks the redirected path.

---

### CCE-6 — Fix pre-existing test_init_fallback_all_dirs_fail
**Priority:** Low
**Labels:** tests
**Estimate:** 1
**Cycle:** 1.2.1

`tests/test_error_handling.py::test_init_fallback_all_dirs_fail` has
been failing on `main` independently of the 1.2.0 patch. The test
patches `pathlib.Path.mkdir` to always raise but the `__init__`
fallback at src/extract_claude_logs.py calls `mkdir(exist_ok=True)`
without a try/except, so the constructor raises. Either wrap the
fallback in try/except or update the test.

---

### CCE-7 — Fix additional pre-existing test failures
**Priority:** Low
**Labels:** tests
**Estimate:** 5
**Cycle:** 1.2.1

29 tests fail on `main` before the 1.2.0 patch is applied. Triage and
fix in a dedicated cycle so the suite is usable as a regression gate
for future work. Covers `test_extract_claude_logs_aligned`,
`test_extract_comprehensive`, `test_search`, `test_search_conversations_aligned`,
and several realtime_search files.

---

### CCE-8 — Separate sidechain / subagent sessions
**Priority:** Medium
**Labels:** schema, qol
**Estimate:** 3
**Cycle:** 1.3.0

`find_sessions()` uses `rglob("*.jsonl")` which picks up subagent files
under `**/subagents/agent-*.jsonl` alongside primary session files.
These should be labeled separately or excluded by default with an opt-in
flag. Also honor the `isSidechain: true` field in the JSONL envelope.

**Acceptance criteria:**
- [ ] New method `find_sessions_separated()` returning
  `(primary, sidechains)`.
- [ ] CLI flag `--include-sidechains` (default off).
- [ ] Interactive UI shows a "Sidechains (N)" submenu.
- [ ] Exported metadata carries `is_sidechain` (already done in 1.2.0).

---

### CCE-9 — Reconstruct conversation branching from parentUuid chains
**Priority:** Medium
**Labels:** schema
**Estimate:** 5
**Cycle:** 1.3.0

Claude Code rewinds create a tree of messages, not a flat list. Each
entry has a `parentUuid` linking it to the previous message. When a
user rewinds and sends a new message, a branch forks. Current exports
linearize the JSONL and can produce confusing interleaved output.

**Acceptance criteria:**
- [ ] Build the parentUuid DAG during extraction.
- [ ] Default export walks the newest leaf back to root (what the user
  actually saw).
- [ ] `--show-branches` flag exports all branches with headers.
- [ ] Detect rewinds and emit a `↶ branch` marker in default exports.

---

### CCE-10 — Decode project folder names for display
**Priority:** Low
**Labels:** qol
**Estimate:** 1
**Cycle:** 1.3.0

Project folders in `~/.claude/projects/` are encoded like `Z--git` or
`C--Users-thomasc8-Downloads`. The tool shows the raw encoded string in
session listings. Helper `_decode_project_name()` already exists (added
in 1.2.0) — wire it into `list_recent_sessions` and the interactive UI.

---

### CCE-11 — Raise filename UUID truncation from 8 to 12 chars
**Priority:** Low
**Labels:** qol
**Estimate:** 1
**Cycle:** 1.2.0

**Status:** Done in the 1.2.0 patch. Created as a tracking issue so the
change is discoverable in search.

---

### CCE-12 — Add `--after` / `--before` date filters
**Priority:** Medium
**Labels:** qol
**Estimate:** 2
**Cycle:** 1.3.0

Already on the upstream roadmap in README. Filter sessions by
modification time or by `first_timestamp` / `last_timestamp` from the
envelope metadata.

---

### CCE-13 — Add `--watch` mode for auto-export
**Priority:** Medium
**Labels:** qol
**Estimate:** 3
**Cycle:** 1.4.0

Tail new JSONL writes in `~/.claude/projects/` and auto-export new
sessions to the configured output directory. Fires once per closed
session (detect via `last-prompt` or stream idle timeout).

---

### CCE-14 — Package as a Claude Code skill (`/extract-session`)
**Priority:** High
**Labels:** skill, integration
**Estimate:** 5
**Cycle:** 1.4.0

Wrap the extractor as a skill under `~/.claude/skills/extract-session/`
following the graphify skill pattern. Skill behavior:

- Default output path to `./conversations/` in the current cwd.
- Default format Markdown, always `--detailed`.
- Expose `/extract-session list`, `/extract-session recent N`,
  `/extract-session export <id>`, `/extract-session search "<query>"`.
- Support piping the exported Markdown into `/graphify` so past sessions
  become part of the knowledge graph.

**Acceptance criteria:**
- [ ] Skill lives in `integrations/claude-code-skill/SKILL.md` in the
  repo and gets installed by a `claude-extract install-skill` command.
- [ ] Skill invocation works from any Claude Code session without extra
  configuration.
- [ ] README updated with skill usage examples.

---

### CCE-15 — Build stdio MCP server (`claude_conversation_extractor.mcp`)
**Priority:** High
**Labels:** mcp, integration
**Estimate:** 8
**Cycle:** 1.4.0

Expose the extractor as a stdio MCP server that any MCP-capable agent
(Claude Desktop, Claude Code, other orchestrators) can query for past
session content mid-conversation. This is the single biggest unlock —
"reference a past session by name" becomes trivial.

**Tools to expose:**
- `list_sessions(project=None, limit=20, include_sidechains=False)`
- `get_session(session_id, detailed=False)` → messages + metadata
- `search_sessions(query, mode="smart", max_results=20, date_from=None, date_to=None)`
- `export_session(session_id, format="markdown", detailed=True)` →
  returns the exported content inline plus a path
- `session_stats()` → counts, date range, total tool_use calls, etc.

**Acceptance criteria:**
- [ ] New module `src/mcp_server.py` implementing the MCP protocol over
  stdio (use the official Python MCP SDK).
- [ ] `claude-extract mcp` entry point starts the server.
- [ ] README section showing how to add it to
  `~/.claude.json` / Claude Desktop `claude_desktop_config.json`.
- [ ] Integration test that spawns the server, sends a
  `tools/list` and a `tools/call` for `list_sessions`, and validates
  the response schema.

---

### CCE-16 — Post-session Claude Code hook for auto-archiving
**Priority:** Medium
**Labels:** hooks, integration
**Estimate:** 2
**Cycle:** 1.4.0

Add a one-line `settings.json` hook recipe to the README that invokes
`claude-extract --recent 1 --detailed` after every Claude Code session
exit, archiving each session to a permanent folder outside
`~/.claude/projects/` (which Claude Code may prune).

Ship a `claude-extract install-hook` command that writes the hook into
the user's `settings.json` with a confirmation prompt.

---

### CCE-17 — Graphify pipeline integration
**Priority:** Medium
**Labels:** integration
**Estimate:** 5
**Cycle:** 1.5.0

End-to-end: exported sessions → `/graphify` → searchable knowledge graph
of the user's Claude Code history, clustered by topic and cross-linked
to their actual code. Builds on CCE-14 (skill) and CCE-15 (MCP).

---

### CCE-18 — Add CLAUDE.md to the repo
**Priority:** Low
**Labels:** docs
**Estimate:** 1
**Cycle:** 1.2.1

Repo-level `CLAUDE.md` documenting:
- The current JSONL schema assumptions (with a link to an example file).
- How to validate against a new Claude Code version.
- The extract_session / extract_conversation split.
- Why detailed mode exists and what it captures.

Helps future Claude Code sessions working on this repo make informed
edits instead of guessing.

---

### CCE-19 — Schema drift detection
**Priority:** Low
**Labels:** schema, tests
**Estimate:** 3
**Cycle:** 1.3.0

The 1.2.0 fix happened because schema drift went undetected for months.
Add a self-check that scans a handful of recent sessions on startup and
warns if unexpected top-level types or content block types appear.
`role: "unknown"` messages (already captured in 1.2.0) are the hook for
this.

**Acceptance criteria:**
- [ ] New `--check-schema` flag that scans N recent sessions and reports
  any unknown types with counts and sample files.
- [ ] Runs automatically on first use per Claude Code version and
  caches the result under `~/.claude/.cce_schema_checked`.

---

### CCE-20 — Bound session_id[:12] filename collisions
**Priority:** Low
**Labels:** qol, schema
**Estimate:** 1
**Cycle:** 1.2.0

**Status:** Bumped to 12 chars in the 1.2.0 patch. Tracking issue only.

---

## Summary

- **Shipped in 1.2.0 (working tree, uncommitted):** CCE-1, CCE-2, CCE-3,
  CCE-4, CCE-11, CCE-20 (6 issues)
- **1.2.1 cycle:** CCE-5, CCE-6, CCE-7, CCE-18 (4 issues, windows/tests/docs)
- **1.3.0 cycle:** CCE-8, CCE-9, CCE-10, CCE-12, CCE-19 (5 issues, schema/qol)
- **1.4.0 cycle:** CCE-13, CCE-14, CCE-15, CCE-16 (4 issues, agent integration)
- **1.5.0 cycle:** CCE-17 (1 issue, graphify pipeline)

Total: 20 issues across 5 cycles. The 1.4.0 cycle is the highest-impact
work for turning this from an archiver into queryable agent memory.
