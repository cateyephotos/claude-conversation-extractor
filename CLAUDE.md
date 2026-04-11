# CLAUDE.md

This file is the repo-level context document for Claude Code sessions working
on `claude-conversation-extractor`. It exists so future sessions can make
informed edits instead of guessing at the JSONL schema, the
`extract_session` / `extract_conversation` split, or what `detailed` mode is
actually supposed to capture. Keep this file updated when any of those
contracts changes.

---

## What this tool does

Reads Claude Code's local session logs out of `~/.claude/projects/<encoded-cwd>/*.jsonl`
and renders them as clean Markdown, JSON, or HTML. Input is undocumented and
has shifted at least once (see *Schema history* below); output should stay
stable so downstream pipelines can consume it.

Primary CLI entry points (all thin wrappers in `src/extract_claude_logs.py`
and `src/search_cli.py`):

- `claude-extract` — interactive UI, default entry point
- `claude-logs` — alias
- `claude-start` — alias
- `claude-search` — search CLI

---

## JSONL schema (current, Claude Code v2.1.x+)

Each line in a session JSONL file is a JSON object. The envelope fields live
at the top level on user/assistant entries:

| Field          | Type    | Notes                                                                 |
|----------------|---------|-----------------------------------------------------------------------|
| `type`         | string  | `"user"`, `"assistant"`, `"queue-operation"`, `"last-prompt"`, `"attachment"` |
| `uuid`         | string  | Stable id for this entry                                              |
| `parentUuid`   | string  | Id of the previous entry in the same branch (null for the root)       |
| `isSidechain`  | bool    | True for subagent sessions (`**/subagents/agent-*.jsonl`)             |
| `cwd`          | string  | Absolute working directory at the time of the message                 |
| `gitBranch`    | string  | Git branch of that working directory, or empty                        |
| `version`      | string  | Claude Code version that emitted the entry                            |
| `entrypoint`   | string  | `"claude-desktop"`, `"cli"`, etc.                                     |
| `userType`     | string  | `"internal"`, `"external"`                                            |
| `timestamp`    | string  | ISO-8601                                                              |
| `message`      | object  | Anthropic-shape message: `{ role, content }` where `content` is a list of blocks |

### Content blocks (`message.content[]`)

Each block has a `type`. The ones we care about:

| Block type     | Where it appears   | What it carries                                                    |
|----------------|--------------------|--------------------------------------------------------------------|
| `text`         | user + assistant   | Plain text; the "visible" conversation                             |
| `thinking`     | assistant          | Extended-thinking content; **only included when `detailed=True`**  |
| `tool_use`     | assistant          | `{ id, name, input }` — tool call Claude made; **detailed only**   |
| `tool_result`  | user               | `{ tool_use_id, content, is_error? }` — result fed back; **detailed only** |

**The critical invariant the 1.2.0 fix enforces:** `tool_result` blocks live
inside **user** messages, `tool_use` and `thinking` blocks live inside
**assistant** messages. Pre-2.0 Claude Code stored them as top-level entries;
that is dead code now but the handling is preserved as a fallback for old
logs.

Example minimal entry (assistant with a tool_use and a text block):

```json
{
  "type": "assistant",
  "uuid": "abc",
  "parentUuid": "xyz",
  "isSidechain": false,
  "cwd": "/Users/x/proj",
  "gitBranch": "main",
  "version": "2.1.3",
  "entrypoint": "claude-desktop",
  "userType": "external",
  "timestamp": "2026-04-10T00:00:00Z",
  "message": {
    "role": "assistant",
    "content": [
      { "type": "thinking", "thinking": "..." },
      { "type": "tool_use", "id": "t1", "name": "Bash", "input": { "command": "ls" } },
      { "type": "text", "text": "Listing the directory." }
    ]
  }
}
```

### Top-level entry types that are telemetry, not conversation

These are skipped by default (see `_NOISE_TOP_LEVEL_TYPES` in
`src/extract_claude_logs.py`):

- `queue-operation`
- `last-prompt`
- `attachment`

If a new Claude Code version adds another telemetry type, add it to that set.

---

## How to validate against a new Claude Code version

When Claude Code ships a new version, do this before trusting the extractor
on it:

1. **Grab a real session file** from `~/.claude/projects/` that was produced
   by the new version. Confirm with `jq '.version' file.jsonl | sort -u`.
2. **Run the smoke test** — pull a recent session and compare counts against
   the raw JSONL:
   ```bash
   python -c "
   from extract_claude_logs import ClaudeConversationExtractor
   from pathlib import Path
   import sys
   e = ClaudeConversationExtractor()
   msgs, meta = e.extract_session(Path(sys.argv[1]), detailed=True)
   tu = sum(1 for m in msgs if m['role'] == 'tool_use')
   tr = sum(1 for m in msgs if m['role'] == 'tool_result')
   th = sum(1 for m in msgs if m['role'] == 'thinking')
   print(f'tool_use={tu} tool_result={tr} thinking={th}')
   " /path/to/session.jsonl
   ```
   Cross-check against `jq` counts on the raw file:
   ```bash
   jq '[.. | objects | select(.type=="tool_use")] | length' file.jsonl
   jq '[.. | objects | select(.type=="tool_result")] | length' file.jsonl
   jq '[.. | objects | select(.type=="thinking")] | length' file.jsonl
   ```
3. **Walk any unknown top-level types.** If `extract_session` reports
   `role: "unknown"` messages for a session, that means we hit a new
   top-level type. Decide whether to render it, drop it, or add a new
   handler. CCE-19 (schema drift detection) automates this check.
4. **Run the adjacent test files** (`test_error_handling`,
   `test_extractor`, `test_extract_claude_logs_aligned`) before and after
   any schema-adjacent change. Failures should not increase.

---

## `extract_session` vs `extract_conversation`

There are two public extraction entry points and they are **not**
interchangeable:

- **`extract_session(jsonl_path, detailed=False) -> (messages, metadata)`** —
  canonical, returns both the message list and the session envelope
  metadata (cwd, gitBranch, version, entrypoint, userType, first/last
  timestamps, `is_sidechain`). Added in 1.2.0. Use this in new code.
- **`extract_conversation(jsonl_path, detailed=False) -> messages`** —
  backward-compat wrapper that drops the metadata. Kept because several
  tests and the older interactive UI path still call it. Do not delete it
  without updating all callers.

There is also a lightweight helper:

- **`extract_session_metadata(jsonl_path) -> metadata`** — reads just the
  envelope fields, used when a caller already has the message list from
  somewhere else (e.g. a mocked extractor in tests).

---

## Why `detailed` mode exists

Default extraction is the "clean transcript" view: only user and assistant
text blocks. This is what most users want when they export a conversation to
share or archive, and it matches the behavior of every pre-1.2.0 release.

`detailed=True` opts into the full agent trace: `thinking` blocks, paired
`tool_use` / `tool_result` blocks, and anything else that lives in
`message.content[]` that isn't plain text. The three writers
(`save_as_markdown`, `save_as_json`, `save_as_html`) all render the new
block types, and `tool_use` / `tool_result` are paired by `tool_use_id` so
the result renders inline after its call.

Detailed mode also truncates large `tool_use` inputs and `tool_result`
content at `_TOOL_PAYLOAD_MAX_CHARS` (2000 chars) with a
`[truncated N chars]` marker — Read/Write/Edit tool calls can otherwise
dump multi-megabyte file contents into the export.

---

## Repository layout

```text
claude-conversation-extractor/
├── CLAUDE.md                         # <- this file; repo-level Claude context
├── README.md                         # User-facing documentation
├── CHANGELOG.md                      # Release notes
├── LICENSE
├── pyproject.toml                    # Package metadata; src layout
├── setup.py                          # Backwards-compat shim
├── assets/                           # Demo GIFs and screenshots
├── config/                           # Packaging config
├── docs/
│   └── development/
│       ├── CLAUDE.md                 # Legacy project context (pre-1.2.0)
│       ├── CONTRIBUTING.md
│       └── LINEAR_PROJECT.md         # Linear project brief for the adaptation work
├── requirements/                     # Dev/optional requirements
├── scripts/                          # Dev scripts
├── src/
│   ├── extract_claude_logs.py        # Main extractor + CLI entry point
│   ├── interactive_ui.py             # Menu-driven UI
│   ├── realtime_search.py            # Incremental search UI
│   ├── search_cli.py                 # `claude-search` CLI entry point
│   └── search_conversations.py       # Search backend
└── tests/
    ├── conftest.py                   # Adds src/ to sys.path
    ├── fixtures/
    ├── test_error_handling.py
    ├── test_extract_claude_logs_aligned.py
    ├── test_extract_comprehensive.py
    ├── test_extractor.py
    ├── test_interactive_ui.py
    ├── test_onedrive_default_output.py   # CCE-5 (1.2.1)
    ├── test_realtime_search_*.py
    ├── test_search.py
    ├── test_search_conversations_aligned.py
    └── test_search_integration.py
```

---

## Development workflow

1. Branch from `main` for every issue. Name branches `feature/cce-N-short-slug`
   where `N` is the Linear issue number from `docs/development/LINEAR_PROJECT.md`.
2. Write the failing test first (TDD). For the schema-adjacent code, use real
   JSONL fixtures in `tests/fixtures/`, not hand-rolled dicts.
3. Run `python -m flake8 src/ tests/ --max-line-length=100`. The existing
   baseline has some pre-existing warnings (~57 at the time of writing);
   don't add new ones.
4. Run the adjacent test files before committing:
   ```bash
   python -m pytest tests/test_error_handling.py tests/test_extractor.py \
                    tests/test_extract_claude_logs_aligned.py --tb=no -q
   ```
   The full suite has known pre-existing failures (tracked by CCE-7); the
   number of failures should not increase from your change.
5. Conventional-Commits style commit messages. Include the Linear issue id
   in the subject, e.g. `fix(windows): ... (CCE-5 / SUPP-183)`.
6. Do **not** push feature branches to `dev` or `main` until the human
   collaborator confirms the feature is finished.

---

## Schema history

- **pre-2.0**: `tool_use` and `tool_result` were emitted as top-level
  entries. The extractor handled them as such. Any remaining
  top-level `type==` branches in `_extract_text_content` /
  `extract_session` are compat shims for old logs; do not rely on
  them for new sessions.
- **2.1.x (current)**: `tool_use` and `thinking` live inside
  `assistant.message.content[]`; `tool_result` lives inside
  `user.message.content[]`. 1.2.0 ships the fix for this.
- **future**: treat `role: "unknown"` messages and unrecognized top-level
  types as schema drift signals. Add handlers, don't paper over them.

---

## Useful references

- `docs/development/LINEAR_PROJECT.md` — the 5-cycle Linear brief driving
  the current adaptation effort.
- `docs/development/CONTRIBUTING.md` — contributor-facing conventions.
- `CHANGELOG.md` — human-readable release history.
- Linear project: *Claude Code Desktop Adaptation* (SupplementDB team)
