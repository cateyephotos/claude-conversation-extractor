#!/usr/bin/env python3
"""
Extract clean conversation logs from Claude Code's internal JSONL files

This tool parses the undocumented JSONL format used by Claude Code to store
conversations locally in ~/.claude/projects/ and exports them as clean,
readable markdown files.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Top-level entry types that are JSONL telemetry, not conversation content.
# These are skipped during extraction regardless of --detailed.
_NOISE_TOP_LEVEL_TYPES = {
    "queue-operation",
    "last-prompt",
    "attachment",
}

# Max serialized size (chars) for tool_use input and tool_result content in
# detailed mode. Read/Write/Edit tool calls can dump entire files; this keeps
# exports bounded.
_TOOL_PAYLOAD_MAX_CHARS = 2000


def _truncate_payload(payload: str, limit: int = _TOOL_PAYLOAD_MAX_CHARS) -> str:
    """Truncate a large tool payload with a clear marker."""
    if len(payload) <= limit:
        return payload
    return payload[:limit] + f"\n... [truncated {len(payload) - limit} chars]"


def _decode_project_name(encoded: str) -> str:
    """Decode Claude Code's CWD-as-folder encoding.

    Claude Code stores conversations under ~/.claude/projects/<encoded-cwd>/
    where slashes and colons are replaced with hyphens. E.g.:
        C--Users-thomasc8-Downloads -> C:/Users/thomasc8/Downloads
        Z--git -> Z:/git
    Returns the original path as a display string; falls back to the raw
    encoded name if decoding produces something implausible.
    """
    if not encoded:
        return encoded
    # Windows drive: single letter followed by "--"
    if len(encoded) >= 3 and encoded[0].isalpha() and encoded[1:3] == "--":
        return encoded[0] + ":/" + encoded[3:].replace("-", "/")
    # POSIX absolute path: leading "-" then segments
    if encoded.startswith("-"):
        return "/" + encoded.lstrip("-").replace("-", "/")
    return encoded.replace("-", "/")


class ClaudeConversationExtractor:
    """Extract and convert Claude Code conversations from JSONL to markdown."""

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize the extractor with Claude's directory and output location."""
        self.claude_dir = Path.home() / ".claude" / "projects"

        if output_dir:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Try multiple possible output directories
            possible_dirs = [
                Path.home() / "Desktop" / "Claude logs",
                Path.home() / "Documents" / "Claude logs",
                Path.home() / "Claude logs",
                Path.cwd() / "claude-logs",
            ]

            # Use the first directory we can create
            for dir_path in possible_dirs:
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    # Test if we can write to it
                    test_file = dir_path / ".test"
                    test_file.touch()
                    test_file.unlink()
                    self.output_dir = dir_path
                    break
                except Exception:
                    continue
            else:
                # Fallback to current directory
                self.output_dir = Path.cwd() / "claude-logs"
                self.output_dir.mkdir(exist_ok=True)

        print(f"📁 Saving logs to: {self.output_dir}")

    def find_sessions(self, project_path: Optional[str] = None) -> List[Path]:
        """Find all JSONL session files, sorted by most recent first."""
        if project_path:
            search_dir = self.claude_dir / project_path
        else:
            search_dir = self.claude_dir

        sessions = []
        if search_dir.exists():
            for jsonl_file in search_dir.rglob("*.jsonl"):
                sessions.append(jsonl_file)
        return sorted(sessions, key=lambda x: x.stat().st_mtime, reverse=True)

    def extract_conversation(self, jsonl_path: Path, detailed: bool = False) -> List[Dict[str, str]]:
        """Extract conversation messages from a JSONL file.

        Backward-compatible wrapper around :meth:`extract_session` that
        returns only the messages list.

        Args:
            jsonl_path: Path to the JSONL file
            detailed: If True, include thinking blocks, tool_use blocks, and
                tool_result blocks alongside the normal user/assistant text.
        """
        messages, _metadata = self.extract_session(jsonl_path, detailed=detailed)
        return messages

    def extract_session_metadata(self, jsonl_path: Path) -> Dict[str, str]:
        """Read only the session envelope metadata from a JSONL file.

        Faster than :meth:`extract_session` when the caller already has
        the message list from another source (e.g. a mocked
        :meth:`extract_conversation`). Walks the file until all known
        metadata fields are populated, then stops. Returns an empty
        metadata dict if the file cannot be read.
        """
        metadata: Dict[str, str] = {
            "session_id": jsonl_path.stem if hasattr(jsonl_path, "stem") else "",
            "cwd": "",
            "git_branch": "",
            "version": "",
            "entrypoint": "",
            "user_type": "",
            "first_timestamp": "",
            "last_timestamp": "",
            "is_sidechain": False,
        }
        field_map = (
            ("cwd", "cwd"),
            ("gitBranch", "git_branch"),
            ("version", "version"),
            ("entrypoint", "entrypoint"),
            ("userType", "user_type"),
        )
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except Exception:
                        continue
                    for src, dst in field_map:
                        if not metadata[dst] and entry.get(src):
                            metadata[dst] = entry[src]
                    if entry.get("isSidechain"):
                        metadata["is_sidechain"] = True
                    ts = entry.get("timestamp", "")
                    if ts:
                        if not metadata["first_timestamp"]:
                            metadata["first_timestamp"] = ts
                        metadata["last_timestamp"] = ts
                    # Stop early once all envelope fields are filled.
                    if all(metadata[dst] for _, dst in field_map):
                        break
        except Exception:
            pass
        return metadata

    def extract_session(
        self, jsonl_path: Path, detailed: bool = False
    ) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
        """Parse a Claude Code JSONL session file.

        Walks the session once and returns a flat list of conversation
        messages plus a metadata dict extracted from session envelope fields.

        The current Claude Code JSONL format (verified against v2.1.x) stores
        tool_use blocks inside ``assistant.message.content[]`` and tool_result
        blocks inside ``user.message.content[]``. Extended thinking content
        appears as ``type: "thinking"`` blocks inside assistant content
        arrays. This walker handles all three plus plain text.

        Args:
            jsonl_path: Path to the JSONL file.
            detailed: If True, thinking/tool_use/tool_result blocks are
                emitted as their own messages. If False, only user/assistant
                text blocks are returned.

        Returns:
            Tuple of (messages, metadata). ``messages`` is a list of dicts
            with at minimum ``role``, ``content``, and ``timestamp``; tool
            messages also carry ``tool_use_id`` and ``tool_name``/``is_error``.
        """
        messages: List[Dict[str, str]] = []
        metadata: Dict[str, str] = {
            "session_id": jsonl_path.stem,
            "cwd": "",
            "git_branch": "",
            "version": "",
            "entrypoint": "",
            "user_type": "",
            "first_timestamp": "",
            "last_timestamp": "",
            "is_sidechain": False,
        }

        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    except Exception:
                        continue

                    # Skip pure telemetry entries.
                    entry_type = entry.get("type", "")
                    if entry_type in _NOISE_TOP_LEVEL_TYPES:
                        continue

                    # Capture envelope metadata from any entry that carries it.
                    # These fields appear on every user/assistant entry in
                    # modern JSONL; take the first non-empty value we see.
                    for field_src, field_dst in (
                        ("cwd", "cwd"),
                        ("gitBranch", "git_branch"),
                        ("version", "version"),
                        ("entrypoint", "entrypoint"),
                        ("userType", "user_type"),
                    ):
                        if not metadata[field_dst] and entry.get(field_src):
                            metadata[field_dst] = entry[field_src]
                    if entry.get("isSidechain"):
                        metadata["is_sidechain"] = True
                    ts = entry.get("timestamp", "")
                    if ts:
                        if not metadata["first_timestamp"]:
                            metadata["first_timestamp"] = ts
                        metadata["last_timestamp"] = ts

                    # System entries in current schema have shape
                    # {"type":"system","subtype":...,"level":...,"content":...}.
                    # They are mostly hook telemetry; expose only in detailed
                    # mode so default exports stay clean.
                    if entry_type == "system":
                        if not detailed:
                            continue
                        sys_content = entry.get("content") or entry.get("message") or ""
                        if not sys_content:
                            continue
                        messages.append(
                            {
                                "role": "system",
                                "content": str(sys_content),
                                "timestamp": ts,
                                "subtype": entry.get("subtype", ""),
                                "level": entry.get("level", ""),
                            }
                        )
                        continue

                    if entry_type not in ("user", "assistant"):
                        continue

                    msg = entry.get("message")
                    if not isinstance(msg, dict):
                        continue
                    role = msg.get("role") or entry_type
                    content = msg.get("content", "")

                    # Expand content blocks into structured messages.
                    for block in self._iter_content_blocks(content, role, detailed=detailed):
                        block.setdefault("timestamp", ts)
                        messages.append(block)

        except Exception as e:
            print(f"❌ Error reading file {jsonl_path}: {e}")

        return messages, metadata

    def _iter_content_blocks(
        self, content, default_role: str, detailed: bool = False
    ):
        """Yield one or more message dicts from a content payload.

        Claude Code content can be:

        * A plain string (legacy / simple prompts) → one message.
        * A list of block dicts with ``type`` in {text, thinking, tool_use,
          tool_result}. Each block becomes its own message.

        In non-detailed mode only ``text`` blocks are emitted, preserving
        the clean-export contract of earlier versions.
        """
        if isinstance(content, str):
            if content.strip():
                yield {"role": default_role, "content": content}
            return

        if not isinstance(content, list):
            text = str(content)
            if text.strip():
                yield {"role": default_role, "content": text}
            return

        for item in content:
            if not isinstance(item, dict):
                continue
            block_type = item.get("type", "")

            if block_type == "text":
                text = item.get("text", "")
                if text.strip():
                    yield {"role": default_role, "content": text}
                continue

            if not detailed:
                continue

            if block_type == "thinking":
                thinking = item.get("thinking") or item.get("text") or ""
                if thinking.strip():
                    yield {"role": "thinking", "content": thinking}
                continue

            if block_type == "tool_use":
                tool_name = item.get("name", "unknown")
                tool_input = item.get("input", {})
                try:
                    payload = json.dumps(tool_input, indent=2, ensure_ascii=False)
                except (TypeError, ValueError):
                    payload = str(tool_input)
                yield {
                    "role": "tool_use",
                    "content": f"Tool: {tool_name}\nInput: {_truncate_payload(payload)}",
                    "tool_name": tool_name,
                    "tool_use_id": item.get("id", ""),
                }
                continue

            if block_type == "tool_result":
                # tool_result blocks live inside user messages in the
                # current schema. The result payload itself may be a
                # string or another list of text blocks.
                raw = item.get("content", "")
                if isinstance(raw, list):
                    parts = []
                    for sub in raw:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            parts.append(sub.get("text", ""))
                        elif isinstance(sub, str):
                            parts.append(sub)
                    result_text = "\n".join(p for p in parts if p)
                elif isinstance(raw, str):
                    result_text = raw
                else:
                    result_text = str(raw)
                yield {
                    "role": "tool_result",
                    "content": _truncate_payload(result_text),
                    "tool_use_id": item.get("tool_use_id", ""),
                    "is_error": bool(item.get("is_error", False)),
                }
                continue

            # Unknown block type — preserve raw in detailed mode so nothing
            # is silently dropped as the schema evolves.
            yield {
                "role": "unknown",
                "content": f"[{block_type}] " + json.dumps(item, ensure_ascii=False)[:500],
            }

    def _extract_text_content(self, content, detailed: bool = False) -> str:
        """Legacy text extractor retained for any external callers.

        New code should prefer :meth:`extract_session`. This method now
        delegates to :meth:`_iter_content_blocks` so callers still see
        thinking/tool blocks when ``detailed=True``.
        """
        parts = []
        for block in self._iter_content_blocks(content, "user", detailed=detailed):
            parts.append(block["content"])
        return "\n".join(parts)

    def display_conversation(self, jsonl_path: Path, detailed: bool = False) -> None:
        """Display a conversation in the terminal with pagination.
        
        Args:
            jsonl_path: Path to the JSONL file
            detailed: If True, include tool use and system messages
        """
        try:
            # Extract conversation
            messages = self.extract_conversation(jsonl_path, detailed=detailed)
            
            if not messages:
                print("❌ No messages found in conversation")
                return
            
            # Get session info
            session_id = jsonl_path.stem
            
            # Clear screen and show header
            print("\033[2J\033[H", end="")  # Clear screen
            print("=" * 60)
            print(f"📄 Viewing: {jsonl_path.parent.name}")
            print(f"Session: {session_id[:8]}...")
            
            # Get timestamp from first message
            first_timestamp = messages[0].get("timestamp", "")
            if first_timestamp:
                try:
                    dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                    print(f"Date: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                except Exception:
                    pass
            
            print("=" * 60)
            print("↑↓ to scroll • Q to quit • Enter to continue\n")
            
            # Display messages with pagination
            lines_shown = 8  # Header lines
            lines_per_page = 30
            
            for i, msg in enumerate(messages):
                role = msg["role"]
                content = msg["content"]
                
                # Format role display
                if role == "user" or role == "human":
                    print(f"\n{'─' * 40}")
                    print(f"👤 HUMAN:")
                    print(f"{'─' * 40}")
                elif role == "assistant":
                    print(f"\n{'─' * 40}")
                    print(f"🤖 CLAUDE:")
                    print(f"{'─' * 40}")
                elif role == "thinking":
                    print(f"\n💭 THINKING:")
                elif role == "tool_use":
                    tool_name = msg.get("tool_name", "")
                    label = f"🔧 TOOL USE: {tool_name}" if tool_name else "🔧 TOOL USE:"
                    print(f"\n{label}")
                elif role == "tool_result":
                    marker = "❌ TOOL ERROR:" if msg.get("is_error") else "📤 TOOL RESULT:"
                    print(f"\n{marker}")
                elif role == "system":
                    subtype = msg.get("subtype", "")
                    label = f"ℹ️ SYSTEM ({subtype}):" if subtype else "ℹ️ SYSTEM:"
                    print(f"\n{label}")
                else:
                    print(f"\n{role.upper()}:")
                
                # Display content (limit very long messages)
                lines = content.split('\n')
                max_lines_per_msg = 50
                
                for line_idx, line in enumerate(lines[:max_lines_per_msg]):
                    # Wrap very long lines
                    if len(line) > 100:
                        line = line[:97] + "..."
                    print(line)
                    lines_shown += 1
                    
                    # Check if we need to paginate
                    if lines_shown >= lines_per_page:
                        response = input("\n[Enter] Continue • [Q] Quit: ").strip().upper()
                        if response == "Q":
                            print("\n👋 Stopped viewing")
                            return
                        # Clear screen for next page
                        print("\033[2J\033[H", end="")
                        lines_shown = 0
                
                if len(lines) > max_lines_per_msg:
                    print(f"... [{len(lines) - max_lines_per_msg} more lines truncated]")
                    lines_shown += 1
            
            print("\n" + "=" * 60)
            print("📄 End of conversation")
            print("=" * 60)
            input("\nPress Enter to continue...")
            
        except Exception as e:
            print(f"❌ Error displaying conversation: {e}")
            input("\nPress Enter to continue...")

    def save_as_markdown(
        self,
        conversation: List[Dict[str, str]],
        session_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Save conversation as clean markdown file.

        Args:
            conversation: Flat message list from :meth:`extract_session`.
            session_id: Session identifier (used for the output filename).
            metadata: Optional session envelope metadata (cwd, git_branch,
                version, entrypoint). When supplied it is rendered as a
                YAML frontmatter block at the top of the file.
        """
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                # Parse ISO timestamp
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                date_str = datetime.now().strftime("%Y-%m-%d")
                time_str = ""
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = ""

        filename = f"claude-conversation-{date_str}-{session_id[:12]}.md"
        output_path = self.output_dir / filename

        # Pair tool_use blocks with their matching tool_result so the
        # Markdown renders a call followed by its result, even when other
        # text blocks appear between them in the raw JSONL.
        result_by_id = {
            m.get("tool_use_id"): m
            for m in conversation
            if m.get("role") == "tool_result" and m.get("tool_use_id")
        }
        rendered_result_ids = set()

        with open(output_path, "w", encoding="utf-8") as f:
            # YAML frontmatter for tooling that consumes exported files.
            if metadata:
                f.write("---\n")
                f.write(f"session_id: {session_id}\n")
                f.write(f"date: {date_str}")
                if time_str:
                    f.write(f" {time_str}")
                f.write("\n")
                if metadata.get("cwd"):
                    f.write(f"cwd: {metadata['cwd']}\n")
                if metadata.get("git_branch"):
                    f.write(f"git_branch: {metadata['git_branch']}\n")
                if metadata.get("version"):
                    f.write(f"claude_version: {metadata['version']}\n")
                if metadata.get("entrypoint"):
                    f.write(f"entrypoint: {metadata['entrypoint']}\n")
                if metadata.get("is_sidechain"):
                    f.write("is_sidechain: true\n")
                f.write(f"message_count: {len(conversation)}\n")
                f.write("---\n\n")

            f.write("# Claude Conversation Log\n\n")
            f.write(f"Session ID: {session_id}\n")
            f.write(f"Date: {date_str}")
            if time_str:
                f.write(f" {time_str}")
            f.write("\n")
            if metadata:
                if metadata.get("cwd"):
                    f.write(f"Working directory: `{metadata['cwd']}`\n")
                if metadata.get("git_branch"):
                    f.write(f"Git branch: `{metadata['git_branch']}`\n")
                if metadata.get("version"):
                    f.write(f"Claude Code version: {metadata['version']}\n")
                if metadata.get("entrypoint"):
                    f.write(f"Entrypoint: `{metadata['entrypoint']}`\n")
            f.write("\n---\n\n")

            for msg in conversation:
                role = msg["role"]
                content = msg["content"]

                # tool_results are rendered inline after their matching
                # tool_use; skip them when iterating linearly.
                if role == "tool_result" and msg.get("tool_use_id") in rendered_result_ids:
                    continue

                if role == "user":
                    f.write("## 👤 User\n\n")
                    f.write(f"{content}\n\n")
                elif role == "assistant":
                    f.write("## 🤖 Claude\n\n")
                    f.write(f"{content}\n\n")
                elif role == "thinking":
                    f.write("<details><summary>💭 Thinking</summary>\n\n")
                    f.write(f"{content}\n\n")
                    f.write("</details>\n\n")
                elif role == "tool_use":
                    tool_name = msg.get("tool_name", "tool")
                    f.write(f"### 🔧 Tool Use: `{tool_name}`\n\n")
                    f.write("```\n")
                    f.write(content)
                    f.write("\n```\n\n")
                    # Inline the paired result, if any.
                    tid = msg.get("tool_use_id")
                    if tid and tid in result_by_id:
                        result = result_by_id[tid]
                        rendered_result_ids.add(tid)
                        marker = "❌ Tool Error" if result.get("is_error") else "📤 Tool Result"
                        f.write(f"**{marker}**\n\n")
                        f.write("```\n")
                        f.write(result["content"])
                        f.write("\n```\n\n")
                elif role == "tool_result":
                    # Orphaned tool_result (no matching tool_use in session).
                    marker = "❌ Tool Error" if msg.get("is_error") else "📤 Tool Result"
                    f.write(f"### {marker}\n\n")
                    f.write("```\n")
                    f.write(content)
                    f.write("\n```\n\n")
                elif role == "system":
                    subtype = msg.get("subtype", "")
                    label = f"ℹ️ System ({subtype})" if subtype else "ℹ️ System"
                    f.write(f"### {label}\n\n")
                    f.write(f"{content}\n\n")
                else:
                    f.write(f"## {role}\n\n")
                    f.write(f"{content}\n\n")
                f.write("---\n\n")

        return output_path
    
    def save_as_json(
        self,
        conversation: List[Dict[str, str]],
        session_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Save conversation as JSON file.

        The top-level object includes a ``metadata`` block when available so
        downstream consumers can filter or group sessions by cwd, git
        branch, Claude Code version, or entrypoint without re-parsing the
        original JSONL.
        """
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        filename = f"claude-conversation-{date_str}-{session_id[:12]}.json"
        output_path = self.output_dir / filename

        output = {
            "session_id": session_id,
            "date": date_str,
            "message_count": len(conversation),
            "metadata": metadata or {},
            "messages": conversation,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output_path
    
    def save_as_html(
        self,
        conversation: List[Dict[str, str]],
        session_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Save conversation as HTML file with syntax highlighting.

        Adds a metadata panel and renders ``thinking`` blocks inside
        collapsed ``<details>`` elements. Tool use/result pairs are
        grouped visually.
        """
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                date_str = datetime.now().strftime("%Y-%m-%d")
                time_str = ""
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = ""

        filename = f"claude-conversation-{date_str}-{session_id[:12]}.html"
        output_path = self.output_dir / filename

        # HTML template with modern styling
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Conversation - {session_id[:8]}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            margin: 0 0 10px 0;
        }}
        .metadata {{
            color: #666;
            font-size: 0.9em;
        }}
        .message {{
            background: white;
            padding: 15px 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .user {{
            border-left: 4px solid #3498db;
        }}
        .assistant {{
            border-left: 4px solid #2ecc71;
        }}
        .tool_use {{
            border-left: 4px solid #f39c12;
            background: #fffbf0;
        }}
        .tool_result {{
            border-left: 4px solid #e74c3c;
            background: #fff5f5;
        }}
        .thinking {{
            border-left: 4px solid #9b59b6;
            background: #faf5ff;
            font-style: italic;
            color: #555;
        }}
        .thinking details summary {{
            cursor: pointer;
            font-weight: bold;
            color: #9b59b6;
        }}
        .system {{
            border-left: 4px solid #95a5a6;
            background: #f8f9fa;
        }}
        .metadata-panel {{
            background: #eef2f7;
            padding: 10px 15px;
            border-radius: 6px;
            margin-top: 10px;
            font-size: 0.85em;
            font-family: 'Courier New', monospace;
        }}
        .metadata-panel dt {{
            font-weight: bold;
            display: inline-block;
            width: 140px;
        }}
        .metadata-panel dd {{
            display: inline;
            margin: 0;
        }}
        .metadata-panel dl {{
            margin: 0;
        }}
        .role {{
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }}
        .content {{
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        pre {{
            background: #f4f4f4;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Claude Conversation Log</h1>
        <div class="metadata">
            <p>Session ID: {session_id}</p>
            <p>Date: {date_str} {time_str}</p>
            <p>Messages: {len(conversation)}</p>
        </div>
"""

        def esc(s: str) -> str:
            return (
                s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

            if metadata:
                f.write('        <div class="metadata-panel"><dl>\n')
                for key, label in (
                    ("cwd", "Working directory"),
                    ("git_branch", "Git branch"),
                    ("version", "Claude Code version"),
                    ("entrypoint", "Entrypoint"),
                    ("user_type", "User type"),
                ):
                    val = metadata.get(key)
                    if val:
                        f.write(
                            f'            <dt>{label}:</dt><dd>{esc(str(val))}</dd><br>\n'
                        )
                if metadata.get("is_sidechain"):
                    f.write('            <dt>Sidechain:</dt><dd>true</dd><br>\n')
                f.write("        </dl></div>\n")

            f.write("    </div>\n")

            # Build tool_use_id -> tool_result map for inline pairing.
            result_by_id = {
                m.get("tool_use_id"): m
                for m in conversation
                if m.get("role") == "tool_result" and m.get("tool_use_id")
            }
            rendered_result_ids = set()

            for msg in conversation:
                role = msg["role"]
                content = esc(msg["content"])

                if role == "tool_result" and msg.get("tool_use_id") in rendered_result_ids:
                    continue

                role_display = {
                    "user": "👤 User",
                    "assistant": "🤖 Claude",
                    "thinking": "💭 Thinking",
                    "tool_use": f"🔧 Tool Use: {esc(msg.get('tool_name', ''))}",
                    "tool_result": "❌ Tool Error" if msg.get("is_error") else "📤 Tool Result",
                    "system": f"ℹ️ System{' (' + esc(msg.get('subtype', '')) + ')' if msg.get('subtype') else ''}",
                }.get(role, role)

                f.write(f'    <div class="message {role}">\n')
                f.write(f'        <div class="role">{role_display}</div>\n')
                if role == "thinking":
                    f.write(
                        f'        <details><summary>Show reasoning</summary>'
                        f'<div class="content">{content}</div></details>\n'
                    )
                else:
                    f.write(f'        <div class="content">{content}</div>\n')
                f.write("    </div>\n")

                # Inline the paired tool_result.
                if role == "tool_use":
                    tid = msg.get("tool_use_id")
                    if tid and tid in result_by_id:
                        result = result_by_id[tid]
                        rendered_result_ids.add(tid)
                        result_role = "tool_result"
                        result_label = (
                            "❌ Tool Error" if result.get("is_error") else "📤 Tool Result"
                        )
                        f.write(f'    <div class="message {result_role}">\n')
                        f.write(f'        <div class="role">{result_label}</div>\n')
                        f.write(
                            f'        <div class="content">{esc(result["content"])}</div>\n'
                        )
                        f.write("    </div>\n")

            f.write("\n</body>\n</html>")

        return output_path

    def save_conversation(
        self,
        conversation: List[Dict[str, str]],
        session_id: str,
        format: str = "markdown",
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[Path]:
        """Save conversation in the specified format.

        Args:
            conversation: The conversation data
            session_id: Session identifier
            format: Output format ('markdown', 'json', 'html')
            metadata: Optional session envelope metadata threaded through
                to the underlying writer.
        """
        if format == "markdown":
            return self.save_as_markdown(conversation, session_id, metadata=metadata)
        elif format == "json":
            return self.save_as_json(conversation, session_id, metadata=metadata)
        elif format == "html":
            return self.save_as_html(conversation, session_id, metadata=metadata)
        else:
            print(f"❌ Unsupported format: {format}")
            return None

    def get_conversation_preview(self, session_path: Path) -> Tuple[str, int]:
        """Get a preview of the conversation's first real user message and message count."""
        try:
            first_user_msg = ""
            msg_count = 0
            
            with open(session_path, 'r', encoding='utf-8') as f:
                for line in f:
                    msg_count += 1
                    if not first_user_msg:
                        try:
                            data = json.loads(line)
                            # Check for user message
                            if data.get("type") == "user" and "message" in data:
                                msg = data["message"]
                                if msg.get("role") == "user":
                                    content = msg.get("content", "")
                                    
                                    # Handle list content (common format in Claude JSONL)
                                    if isinstance(content, list):
                                        for item in content:
                                            if isinstance(item, dict) and item.get("type") == "text":
                                                text = item.get("text", "").strip()
                                                
                                                # Skip tool results
                                                if text.startswith("tool_use_id"):
                                                    continue
                                                
                                                # Skip interruption messages
                                                if "[Request interrupted" in text:
                                                    continue
                                                
                                                # Skip Claude's session continuation messages
                                                if "session is being continued" in text.lower():
                                                    continue
                                                
                                                # Remove XML-like tags (command messages, etc)
                                                import re
                                                text = re.sub(r'<[^>]+>', '', text).strip()
                                                
                                                # Skip command outputs  
                                                if "is running" in text and "…" in text:
                                                    continue
                                                
                                                # Handle image references - extract text after them
                                                if text.startswith("[Image #"):
                                                    parts = text.split("]", 1)
                                                    if len(parts) > 1:
                                                        text = parts[1].strip()
                                                
                                                # If we have real user text, use it
                                                if text and len(text) > 3:  # Lower threshold to catch "hello"
                                                    first_user_msg = text[:100].replace('\n', ' ')
                                                    break
                                    
                                    # Handle string content (less common but possible)
                                    elif isinstance(content, str):
                                        import re
                                        content = content.strip()
                                        
                                        # Remove XML-like tags
                                        content = re.sub(r'<[^>]+>', '', content).strip()
                                        
                                        # Skip command outputs
                                        if "is running" in content and "…" in content:
                                            continue
                                        
                                        # Skip Claude's session continuation messages
                                        if "session is being continued" in content.lower():
                                            continue
                                        
                                        # Skip tool results and interruptions
                                        if not content.startswith("tool_use_id") and "[Request interrupted" not in content:
                                            if content and len(content) > 3:  # Lower threshold to catch short messages
                                                first_user_msg = content[:100].replace('\n', ' ')
                        except json.JSONDecodeError:
                            continue
                            
            return first_user_msg or "No preview available", msg_count
        except Exception as e:
            return f"Error: {str(e)[:30]}", 0

    def list_recent_sessions(self, limit: int = None) -> List[Path]:
        """List recent sessions with details."""
        sessions = self.find_sessions()

        if not sessions:
            print("❌ No Claude sessions found in ~/.claude/projects/")
            print("💡 Make sure you've used Claude Code and have conversations saved.")
            return []

        print(f"\n📚 Found {len(sessions)} Claude sessions:\n")
        print("=" * 80)

        # Show all sessions if no limit specified
        sessions_to_show = sessions[:limit] if limit else sessions
        for i, session in enumerate(sessions_to_show, 1):
            # Clean up project name (remove hyphens, make readable)
            project = session.parent.name.replace('-', ' ').strip()
            if project.startswith("Users"):
                project = "~/" + "/".join(project.split()[2:]) if len(project.split()) > 2 else "Home"
            
            session_id = session.stem
            modified = datetime.fromtimestamp(session.stat().st_mtime)

            # Get file size
            size = session.stat().st_size
            size_kb = size / 1024
            
            # Get preview and message count
            preview, msg_count = self.get_conversation_preview(session)

            # Print formatted info
            print(f"\n{i}. 📁 {project}")
            print(f"   📄 Session: {session_id[:8]}...")
            print(f"   📅 Modified: {modified.strftime('%Y-%m-%d %H:%M')}")
            print(f"   💬 Messages: {msg_count}")
            print(f"   💾 Size: {size_kb:.1f} KB")
            print(f"   📝 Preview: \"{preview}...\"")

        print("\n" + "=" * 80)
        return sessions[:limit]

    def extract_multiple(
        self, sessions: List[Path], indices: List[int], 
        format: str = "markdown", detailed: bool = False
    ) -> Tuple[int, int]:
        """Extract multiple sessions by index.
        
        Args:
            sessions: List of session paths
            indices: Indices to extract
            format: Output format ('markdown', 'json', 'html')
            detailed: If True, include tool use and system messages
        """
        success = 0
        total = len(indices)

        for idx in indices:
            if 0 <= idx < len(sessions):
                session_path = sessions[idx]
                # Call extract_conversation so subclasses / tests that
                # override it still see the call. Metadata is fetched
                # separately via the lightweight envelope reader.
                conversation = self.extract_conversation(
                    session_path, detailed=detailed
                )
                if conversation:
                    metadata = self.extract_session_metadata(session_path)
                    output_path = self.save_conversation(
                        conversation,
                        session_path.stem,
                        format=format,
                        metadata=metadata,
                    )
                    success += 1
                    msg_count = len(conversation)
                    print(
                        f"✅ {success}/{total}: {output_path.name} "
                        f"({msg_count} messages)"
                    )
                else:
                    print(f"⏭️  Skipped session {idx + 1} (no conversation)")
            else:
                print(f"❌ Invalid session number: {idx + 1}")

        return success, total


# ---------------------------------------------------------------------------
# Post-session auto-archive hook installer (CCE-16)
# ---------------------------------------------------------------------------

# Exact command we want to land in the user's ``settings.json`` Stop hook.
# Using ``--recent 1 --detailed`` matches the recipe documented in the
# README: archive the most recent session with full tool trace after
# every Claude Code session exit.
_HOOK_COMMAND = "claude-extract --recent 1 --detailed"


def _hook_already_installed(settings: dict) -> bool:
    """True if a Stop hook entry invoking claude-extract already exists."""
    stop_hooks = (
        settings.get("hooks", {}).get("Stop", [])
        if isinstance(settings.get("hooks", {}), dict)
        else []
    )
    for group in stop_hooks or []:
        inner = group.get("hooks", []) if isinstance(group, dict) else []
        for entry in inner:
            if not isinstance(entry, dict):
                continue
            cmd = entry.get("command", "")
            if entry.get("type") == "command" and "claude-extract" in cmd:
                return True
    return False


def install_hook(settings_path: Optional[Path] = None) -> bool:
    """Install a Claude Code Stop hook that auto-archives every session.

    Writes (or merges into) ``settings_path`` the hook block::

        {"hooks": {"Stop": [{"hooks": [{"type": "command",
                                        "command": "claude-extract --recent 1 --detailed"}]}]}}

    Behavior:
    - If the hook is already present, returns False without prompting.
    - Otherwise prompts the user with a y/N confirmation. Declining is a
      no-op and returns False.
    - On accept, merges the hook into the existing file (preserving
      unrelated keys and hook events) and returns True.

    Args:
        settings_path: Override for ``~/.claude/settings.json``. Used by
            tests; production callers should leave this at the default.
    """
    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"

    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (OSError, json.JSONDecodeError):
            existing = {}

    if _hook_already_installed(existing):
        print(
            f"ℹ️  Stop hook already installed in {settings_path}. "
            f"Nothing to do."
        )
        return False

    print(
        f"About to install this Stop hook into {settings_path}:\n\n"
        f"  {_HOOK_COMMAND}\n\n"
        f"This runs after every Claude Code session exit and archives "
        f"the latest session to your configured output folder."
    )
    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print("Aborted. settings.json was not modified.")
        return False

    hooks_block = existing.setdefault("hooks", {})
    if not isinstance(hooks_block, dict):
        hooks_block = {}
        existing["hooks"] = hooks_block
    stop_block = hooks_block.setdefault("Stop", [])
    if not isinstance(stop_block, list):
        stop_block = []
        hooks_block["Stop"] = stop_block
    stop_block.append(
        {
            "hooks": [
                {"type": "command", "command": _HOOK_COMMAND},
            ]
        }
    )

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✅ Installed Stop hook into {settings_path}.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Extract Claude Code conversations to clean markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                    # List all available sessions
  %(prog)s --extract 1               # Extract the most recent session
  %(prog)s --extract 1,3,5           # Extract specific sessions
  %(prog)s --recent 5                # Extract 5 most recent sessions
  %(prog)s --all                     # Extract all sessions
  %(prog)s --output ~/my-logs        # Specify output directory
  %(prog)s --search "python error"   # Search conversations
  %(prog)s --search-regex "import.*" # Search with regex
  %(prog)s --format json --all       # Export all as JSON
  %(prog)s --format html --extract 1 # Export session 1 as HTML
  %(prog)s --detailed --extract 1    # Include tool use & system messages
        """,
    )
    parser.add_argument("--list", action="store_true", help="List recent sessions")
    parser.add_argument(
        "--extract",
        type=str,
        help="Extract specific session(s) by number (comma-separated)",
    )
    parser.add_argument(
        "--all", "--logs", action="store_true", help="Extract all sessions"
    )
    parser.add_argument(
        "--recent", type=int, help="Extract N most recent sessions", default=0
    )
    parser.add_argument(
        "--output", type=str, help="Output directory for markdown files"
    )
    parser.add_argument(
        "--limit", type=int, help="Limit for --list command (default: show all)", default=None
    )
    parser.add_argument(
        "--install-hook",
        action="store_true",
        help=(
            "Install a Claude Code Stop hook into ~/.claude/settings.json "
            "that runs 'claude-extract --recent 1 --detailed' after every "
            "session exit, archiving each session outside ~/.claude/projects/"
        ),
    )
    parser.add_argument(
        "--interactive",
        "-i",
        "--start",
        "-s",
        action="store_true",
        help="Launch interactive UI for easy extraction",
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Export mode: 'logs' for interactive UI",
    )

    # Search arguments
    parser.add_argument(
        "--search", type=str, help="Search conversations for text (smart search)"
    )
    parser.add_argument(
        "--search-regex", type=str, help="Search conversations using regex pattern"
    )
    parser.add_argument(
        "--search-date-from", type=str, help="Filter search from date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--search-date-to", type=str, help="Filter search to date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--search-speaker",
        choices=["human", "assistant", "both"],
        default="both",
        help="Filter search by speaker",
    )
    parser.add_argument(
        "--case-sensitive", action="store_true", help="Make search case-sensitive"
    )
    
    # Export format arguments
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "html"],
        default="markdown",
        help="Output format for exported conversations (default: markdown)"
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Include tool use, MCP responses, and system messages in export"
    )

    args = parser.parse_args()

    # Handle --install-hook before anything else so the command stays
    # usable even if the user has no sessions yet. Short-circuits the
    # rest of main() on completion.
    if args.install_hook:
        install_hook()
        return

    # Handle interactive mode
    if args.interactive or (args.export and args.export.lower() == "logs"):
        from interactive_ui import main as interactive_main

        interactive_main()
        return

    # Initialize extractor with optional output directory
    extractor = ClaudeConversationExtractor(args.output)

    # Handle search mode
    if args.search or args.search_regex:
        from datetime import datetime

        from search_conversations import ConversationSearcher

        searcher = ConversationSearcher()

        # Determine search mode and query
        if args.search_regex:
            query = args.search_regex
            mode = "regex"
        else:
            query = args.search
            mode = "smart"

        # Parse date filters
        date_from = None
        date_to = None
        if args.search_date_from:
            try:
                date_from = datetime.strptime(args.search_date_from, "%Y-%m-%d")
            except ValueError:
                print(f"❌ Invalid date format: {args.search_date_from}")
                return

        if args.search_date_to:
            try:
                date_to = datetime.strptime(args.search_date_to, "%Y-%m-%d")
            except ValueError:
                print(f"❌ Invalid date format: {args.search_date_to}")
                return

        # Speaker filter
        speaker_filter = None if args.search_speaker == "both" else args.search_speaker

        # Perform search
        print(f"🔍 Searching for: {query}")
        results = searcher.search(
            query=query,
            mode=mode,
            date_from=date_from,
            date_to=date_to,
            speaker_filter=speaker_filter,
            case_sensitive=args.case_sensitive,
            max_results=30,
        )

        if not results:
            print("❌ No matches found.")
            return

        print(f"\n✅ Found {len(results)} matches across conversations:")

        # Group and display results
        results_by_file = {}
        for result in results:
            if result.file_path not in results_by_file:
                results_by_file[result.file_path] = []
            results_by_file[result.file_path].append(result)

        # Store file paths for potential viewing
        file_paths_list = []
        for file_path, file_results in results_by_file.items():
            file_paths_list.append(file_path)
            print(f"\n{len(file_paths_list)}. 📄 {file_path.parent.name} ({len(file_results)} matches)")
            # Show first match preview
            first = file_results[0]
            print(f"   {first.speaker}: {first.matched_content[:100]}...")

        # Offer to view conversations
        if file_paths_list:
            print("\n" + "=" * 60)
            try:
                view_choice = input("\nView a conversation? Enter number (1-{}) or press Enter to skip: ".format(
                    len(file_paths_list))).strip()
                
                if view_choice.isdigit():
                    view_num = int(view_choice)
                    if 1 <= view_num <= len(file_paths_list):
                        selected_path = file_paths_list[view_num - 1]
                        extractor.display_conversation(selected_path, detailed=args.detailed)

                        # Offer to extract after viewing
                        extract_choice = input("\n📤 Extract this conversation? (y/N): ").strip().lower()
                        if extract_choice == 'y':
                            conversation, metadata = extractor.extract_session(
                                selected_path, detailed=args.detailed
                            )
                            if conversation:
                                session_id = selected_path.stem
                                output = extractor.save_conversation(
                                    conversation,
                                    session_id,
                                    format=args.format,
                                    metadata=metadata,
                                )
                                print(f"✅ Saved: {output.name}")
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Cancelled")
        
        return

    # Default action is to list sessions
    if args.list or (
        not args.extract
        and not args.all
        and not args.recent
        and not args.search
        and not args.search_regex
    ):
        sessions = extractor.list_recent_sessions(args.limit)

        if sessions and not args.list:
            print("\nTo extract conversations:")
            print("  claude-extract --extract <number>      # Extract specific session")
            print("  claude-extract --recent 5              # Extract 5 most recent")
            print("  claude-extract --all                   # Extract all sessions")

    elif args.extract:
        sessions = extractor.find_sessions()

        # Parse comma-separated indices
        indices = []
        for num in args.extract.split(","):
            try:
                idx = int(num.strip()) - 1  # Convert to 0-based index
                indices.append(idx)
            except ValueError:
                print(f"❌ Invalid session number: {num}")
                continue

        if indices:
            print(f"\n📤 Extracting {len(indices)} session(s) as {args.format.upper()}...")
            if args.detailed:
                print("📋 Including detailed tool use and system messages")
            success, total = extractor.extract_multiple(
                sessions, indices, format=args.format, detailed=args.detailed
            )
            print(f"\n✅ Successfully extracted {success}/{total} sessions")

    elif args.recent:
        sessions = extractor.find_sessions()
        limit = min(args.recent, len(sessions))
        print(f"\n📤 Extracting {limit} most recent sessions as {args.format.upper()}...")
        if args.detailed:
            print("📋 Including detailed tool use and system messages")

        indices = list(range(limit))
        success, total = extractor.extract_multiple(
            sessions, indices, format=args.format, detailed=args.detailed
        )
        print(f"\n✅ Successfully extracted {success}/{total} sessions")

    elif args.all:
        sessions = extractor.find_sessions()
        print(f"\n📤 Extracting all {len(sessions)} sessions as {args.format.upper()}...")
        if args.detailed:
            print("📋 Including detailed tool use and system messages")

        indices = list(range(len(sessions)))
        success, total = extractor.extract_multiple(
            sessions, indices, format=args.format, detailed=args.detailed
        )
        print(f"\n✅ Successfully extracted {success}/{total} sessions")


def launch_interactive():
    """Launch the interactive UI directly, or handle search if specified."""
    import sys
    
    # If no arguments provided, launch interactive UI
    if len(sys.argv) == 1:
        try:
            from .interactive_ui import main as interactive_main
        except ImportError:
            from interactive_ui import main as interactive_main
        interactive_main()
    # Check if 'search' was passed as an argument
    elif len(sys.argv) > 1 and sys.argv[1] == 'search':
        # Launch real-time search with viewing capability
        try:
            from .realtime_search import RealTimeSearch, create_smart_searcher
            from .search_conversations import ConversationSearcher
        except ImportError:
            from realtime_search import RealTimeSearch, create_smart_searcher
            from search_conversations import ConversationSearcher
        
        # Initialize components
        extractor = ClaudeConversationExtractor()
        searcher = ConversationSearcher()
        smart_searcher = create_smart_searcher(searcher)
        
        # Run search
        rts = RealTimeSearch(smart_searcher, extractor)
        selected_file = rts.run()
        
        if selected_file:
            # View the selected conversation
            extractor.display_conversation(selected_file)

            # Offer to extract
            try:
                extract_choice = input("\n📤 Extract this conversation? (y/N): ").strip().lower()
                if extract_choice == 'y':
                    conversation, metadata = extractor.extract_session(selected_file)
                    if conversation:
                        session_id = selected_file.stem
                        output = extractor.save_as_markdown(
                            conversation, session_id, metadata=metadata
                        )
                        print(f"✅ Saved: {output.name}")
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Cancelled")
    else:
        # If other arguments are provided, run the normal CLI
        main()


if __name__ == "__main__":
    main()
