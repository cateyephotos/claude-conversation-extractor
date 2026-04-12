# Session Handoff — CCE Branch Landing Campaign

## Context

We're landing 14 feature branches from the Claude Code Desktop
Adaptation project (LINEAR_PROJECT.md) onto the `dev` branch, with
code review before each merge. The repo is
`cateyephotos/claude-conversation-extractor`, cloned at
`C:\Users\Mind0\Downloads\git\claude-conversation-extractor`.

Linear project: "Claude Code Desktop Adaptation" in the SupplementDB
team. All 20 CCE issues (SUPP-179 through SUPP-198) are created with
milestones, labels, estimates, and descriptions matching
`docs/development/LINEAR_PROJECT.md`.

## Branches landed on `dev` (6/14 done)

These have been code-reviewed, merged with `--no-ff`, pushed to
`origin/dev`, and marked **Done** in Linear:

| Branch | Issue | Merge commit |
|--------|-------|-------------|
| `feature/cce-18-claude-md` | SUPP-196 | `cabd866` |
| `feature/cce-5-windows-onedrive-output-dir` | SUPP-183 | `fc4e224` |
| `feature/cce-6-fix-init-fallback` | SUPP-184 | `b85f540` |
| `feature/cce-10-decode-project-names` | SUPP-188 | `5fe8d43` |
| `feature/cce-12-date-filters` | SUPP-190 | `c4fe790` |
| `feature/cce-16-install-hook` | SUPP-194 | `935a5ba` |

## Branches remaining (8, in recommended landing order)

Each is a local branch off `main` with a single commit. Review with
`/code-review:code-review`, then merge into `dev` with `--no-ff`,
push, and mark the Linear issue Done.

| # | Branch | Issue | Est. pts | Notes |
|---|--------|-------|----------|-------|
| 1 | `feature/cce-19-schema-drift-detection` | SUPP-197 | 3 | `--check-schema` flag + per-version auto cache |
| 2 | `feature/cce-13-watch-mode` | SUPP-191 | 3 | `--watch` mode for auto-export |
| 3 | `feature/cce-8-sidechains-separation` | SUPP-186 | 3 | `find_sessions_separated` + `--include-sidechains` |
| 4 | `feature/cce-9-parent-uuid-branching` | SUPP-187 | 5 | parentUuid DAG + `--show-branches` / `--newest-branch` |
| 5 | `feature/cce-14-skill-wrapper` | SUPP-192 | 5 | `/extract-session` Claude Code skill + `--install-skill` |
| 6 | `feature/cce-15-mcp-server` | SUPP-193 | 8 | stdio MCP server (zero-dep JSON-RPC 2.0) |
| 7 | `feature/cce-17-graphify-pipeline` | SUPP-195 | 5 | `--graphify` pipeline + manifest |
| 8 | `feature/cce-7-fix-pre-existing-tests` | SUPP-185 | 5 | Test suite triage (74->0 failures via xfail + fixes) |

**Land CCE-7 last** — its `conftest.py` xfail list needs to reconcile
against whatever else already shipped.

## Landing workflow per branch

```bash
# 1. Checkout the feature branch
git checkout feature/cce-N-slug

# 2. Run its tests
python -m pytest tests/test_NEW_FILE.py -v

# 3. Review (invoke /code-review:code-review)

# 4. If review passes, merge into dev
git checkout dev
git merge --no-ff feature/cce-N-slug -m "Merge ..."

# 5. Verify post-merge
python -m pytest tests/test_NEW_FILE.py -v

# 6. Push
git push origin dev

# 7. Update Linear
# Mark SUPP-NNN as Done, post a review summary comment
```

## Merge conflict expectations

- **CCE-8 and CCE-12** both add kwargs to `find_sessions` — textual
  conflict likely but both are additive (different param names).
- **CCE-9** refactored `extract_session` into a two-pass walker —
  largest conflict surface in the project.
- **CCE-15** adds `mcp_server` to `pyproject.toml` `py-modules` —
  ensure it lands.
- **CCE-7** touches `conftest.py` and several test files — land last.

## Key decisions made in the previous session

1. All branches are independent off `main` (not stacked).
2. `dev` branch was created from `main` for this landing campaign.
3. Code reviews flagged and fixed: stale line-number citation in
   CLAUDE.md (CCE-18), `sort_keys=True` key-reordering in
   `install_hook` (CCE-16), generic test fixture names replacing
   `thomasc8` (CCE-10).
4. Hook schema for CCE-16 was verified against the live Claude Code
   `update-config` skill's JSON schema — format is correct.
5. `.gitignore` line 74 has `test_*.py` — new test files need
   `git add -f`. Worth a cleanup PR later.

## How to resume

Start a new Claude Code session in the repo directory and say:

> Read .claude/handoff.md and continue landing the remaining 8
> feature branches onto dev, with code review before each merge.
> Start with CCE-19.
