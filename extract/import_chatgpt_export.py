#!/usr/bin/env python3
"""Import a ChatGPT conversation export (research-log-export/daily/*.md) into inbox/.

The export interleaves multiple messages per day, each under a heading like
"## <Conversation Title> - User" / "## <Conversation Title> - Assistant",
followed by Source/Message ID/Date basis metadata lines. This splits each day
into one file per Assistant message (user turns are dropped -- they're mostly
the user's own data/questions, not external signal), strips ChatGPT citation
tokens that don't resolve outside the original conversation, and writes
normalized files into inbox/ for extract.py to pick up.

Assistant messages only, because scope for this pass is external signal
(papers/people/repos/jobs) -- not the user's own experiment logs or coaching.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DAILY_DIR = ROOT / "research-log-export" / "daily"
INBOX = ROOT / "inbox"

MESSAGE_HEADING = re.compile(r"^## (.+?) [—-] (User|Assistant)\s*$")
METADATA_LINE = re.compile(r"^(Source|Message ID|Date basis):")
CITATION_TOKEN = re.compile(r"\b(file)?citeturn\S+")


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


def clean_body(lines: list[str]) -> str:
    kept = [line for line in lines if not METADATA_LINE.match(line)]
    text = "\n".join(kept).strip()
    text = CITATION_TOKEN.sub("", text)
    return text


def split_messages(text: str) -> list[tuple[str, str, str]]:
    """Returns list of (conversation_title, role, body) for each message block."""
    lines = text.splitlines()
    messages: list[tuple[str, str, list[str]]] = []
    current = None

    for line in lines:
        match = MESSAGE_HEADING.match(line)
        if match:
            if current:
                messages.append(current)
            current = (match.group(1), match.group(2), [])
        elif current:
            current[2].append(line)
    if current:
        messages.append(current)

    return [(title, role, clean_body(body)) for title, role, body in messages]


def import_file(day_path: Path) -> int:
    date = day_path.stem  # filename is YYYY-MM-DD.md
    text = day_path.read_text()
    messages = split_messages(text)

    written = 0
    for idx, (title, role, body) in enumerate(messages, start=1):
        if role != "Assistant" or not body:
            continue
        out_name = f"{date}__chatgpt__{idx:02d}__{slugify(title)}.md"
        out_path = INBOX / out_name
        out_path.write_text(f"# {title} ({date})\n\n{body}\n")
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(EXPORT_DAILY_DIR))
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    day_files = sorted(source_dir.glob("*.md"))
    if not day_files:
        print(f"No day files found in {source_dir}")
        return

    total = 0
    for day_path in day_files:
        count = import_file(day_path)
        total += count
        print(f"{day_path.name}: wrote {count} assistant message file(s)")

    print(f"Done. {total} message file(s) written to {INBOX}")


if __name__ == "__main__":
    main()
