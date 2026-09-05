#!/usr/bin/env python3
"""Generate an on-demand weekly summary of todo activity via Hermes."""
from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from pathlib import Path

from hermes_client import run_hermes

ROOT = Path(__file__).resolve().parent.parent

SUMMARY_PROMPT_TEMPLATE = """You are writing a short, honest weekly review of a personal todo list, for \
someone who has a habit of taking on too much and not following through. Be direct, not falsely \
encouraging -- the point is to surface the pattern, not to make them feel good.

Period: {period_start} to {period_end}

Added this week (no due date yet):
{added}

Committed this week (given a due date):
{committed}

Done this week:
{done}

Still sitting untouched, added more than 7 days ago and never committed (a due date was never set):
{stale}

Overdue (committed with a due date that has already passed, not done):
{overdue}

Write a short markdown summary (headings + a few bullets each, no more than ~200 words total) covering: \
what actually got done, what's piling up unclaimed, and what's overdue. End with one blunt, concrete \
suggestion for what to do about the pile-up.
"""


def _fmt(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "(none)"
    return "\n".join(f"- {row['title']}" for row in rows)


def generate(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    today = dt.date.today()
    period_start = (today - dt.timedelta(days=7)).isoformat()
    period_end = today.isoformat()

    added = conn.execute(
        "SELECT title FROM todos WHERE added_at >= ? AND status = 'added'", (period_start,)
    ).fetchall()
    committed = conn.execute(
        "SELECT title FROM todos WHERE committed_at >= ?", (period_start,)
    ).fetchall()
    done = conn.execute(
        "SELECT title FROM todos WHERE done_at >= ?", (period_start,)
    ).fetchall()
    stale = conn.execute(
        "SELECT title FROM todos WHERE status = 'added' AND added_at < ?",
        ((today - dt.timedelta(days=7)).isoformat(),),
    ).fetchall()
    overdue = conn.execute(
        "SELECT title FROM todos WHERE status = 'committed' AND due_date < ? AND done_at IS NULL",
        (period_end,),
    ).fetchall()

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        period_start=period_start, period_end=period_end,
        added=_fmt(added), committed=_fmt(committed), done=_fmt(done),
        stale=_fmt(stale), overdue=_fmt(overdue),
    )
    summary_text = run_hermes(prompt, cwd=ROOT)

    row = {
        "id": str(uuid.uuid4()),
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "period_start": period_start,
        "period_end": period_end,
        "summary": summary_text,
    }
    conn.execute(
        "INSERT INTO weekly_summaries (id, generated_at, period_start, period_end, summary) "
        "VALUES (?, ?, ?, ?, ?)",
        (row["id"], row["generated_at"], row["period_start"], row["period_end"], row["summary"]),
    )
    conn.commit()
    return row
