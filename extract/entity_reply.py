#!/usr/bin/env python3
"""Generate a short, synchronous Hermes reply to a user comment on a feed entity."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from hermes_client import run_hermes

ROOT = Path(__file__).resolve().parent.parent

REPLY_PROMPT_TEMPLATE = """You are replying to a short comment the user left on a tracked research-feed \
card, as a knowledgeable research assistant. Keep it to 1-3 sentences -- specific and useful, not \
a generic acknowledgment. Ground your reply strictly in the card's own content below; if the comment \
asks something the card doesn't cover, say so plainly rather than inventing detail.

Card type: {type}
Title: {title}
Summary: {summary}
Tags: {tags}
Extra: {extra}

User's comment: {comment}

Reply as plain text, no markdown headers, no prefacing like "Reply:" -- just the reply itself.
"""


def generate_reply(entity: dict, comment_body: str) -> str | None:
    prompt = REPLY_PROMPT_TEMPLATE.format(
        type=entity.get("type", ""),
        title=entity.get("title", ""),
        summary=entity.get("summary") or "",
        tags=", ".join(entity.get("tags") or []),
        extra=json.dumps(entity.get("extra") or {}),
        comment=comment_body,
    )
    try:
        return run_hermes(prompt, cwd=ROOT, timeout=60)
    except Exception:  # noqa: BLE001
        return None
