---
name: research-feed
description: "Read and write the user's research-feed app: a reel-style feed of tracked papers/people/repos/jobs, a todo tracker (including networking outreach), comment threads, and an X/LinkedIn draft queue. Use this whenever asked to check committed/added todos, log progress on outreach or a task, check whether a person/paper/repo is already tracked before adding it, queue a post draft for review, or pull daily context to ground a briefing in what the user has actually committed to."
version: 1.0.0
author: mkdsrt10
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [research-feed, todos, networking, drafts, personal-api]
    homepage: https://github.com/mkdsrt10/research-feed
prerequisites:
  commands: [curl]
---

# research-feed

The user's personal research reel + todo/networking tracker + draft-post queue.
Runs as a local HTTP API on this same machine. Read the feed and todos before
producing a briefing or reflection, and write findings/drafts/progress back
into it instead of maintaining separate tracking files.

## Base URL and auth

```
BASE=http://localhost:8787
KEY=$(cat ~/.hermes/scripts/research-feed-api-key)
```

Every write (`POST`/`PATCH`/`DELETE`) needs the key as a header:

```bash
curl -s -X POST "$BASE/api/todos" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{...}'
```

`GET` requests don't need it. If the key is ever invalid or revoked, `manage_keys.py`
on the app (`~/research-feed/server/manage_keys.py`) can issue a new one -- ask the
user rather than trying to work around a 401/403.

## Pull context before writing anything

```bash
curl -s "$BASE/api/context/daily" -H "X-API-Key: $KEY"
```

Returns `committed_todos`, `added_todos`, `networking_todos` (todos linked to a
`person`-type entity -- this **is** the People Tracker, nothing else needed),
`recent_comments`, and `pending_drafts`. Ground any "connection to my work only
when genuine" language in what's actually here, not in a guess.

## Check for an existing entity before adding one (dedup)

**Always do this before creating a new person/paper/repo/job** -- a prior run
fragmented one real person ("Adam Dowse") into three separate entries by using
a slightly different name string each time. Don't repeat that.

```bash
curl -s "$BASE/api/feed?type=person&q=Adam%20Dowse&include_seen=1" -H "X-API-Key: $KEY"
```

`type` is one of `paper`/`person`/`repo`/`job`. `q` is a substring match on
title. `include_seen=1` is required for this kind of lookup -- without it,
anything the user already scrolled past is hidden. If a match comes back,
that's the same entity; don't create a second one. When you do add a new
person, use **their name only** as the title -- never append "- Company" or
combine two people in one entry.

## Todos (tasks and networking, same object)

```bash
# create -- for a networking suggestion, set source_entity_id to the person's entity id
curl -s -X POST "$BASE/api/todos" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"title": "...", "source_entity_id": "<entity-id-or-omit>"}'

# a due_date is what makes it "committed" instead of just "added"
curl -s -X PATCH "$BASE/api/todos/<id>" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"due_date": "2026-09-10"}'

# mark done
curl -s -X PATCH "$BASE/api/todos/<id>" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"done": true}'

# log progress -- this is the interaction log, use it instead of a separate memory file
curl -s -X POST "$BASE/api/todos/<id>/comments" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"body": "Emailed a follow-up about the ablation setup."}'

# list, optionally filtered
curl -s "$BASE/api/todos?status=added"                # added | committed | done
curl -s "$BASE/api/todos?entity_type=person"            # networking todos only
```

Every todo response includes `source_entity_type`, `source_entity_title`, and
`source_entity_extra` (affiliation, suggested_reply, etc.) when it's linked to
an entity -- no second lookup needed.

## Drafts (X/LinkedIn posts) -- always queue, never post directly

```bash
curl -s -X POST "$BASE/api/drafts" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"platform": "x", "content": "...", "source_todo_id": "<optional>"}'
```

`platform` is `x` or `linkedin`. The user reviews and approves/rejects these on
the app's Home screen -- this skill should never post to X or LinkedIn itself.

## Write daily findings back into the feed

Drop the day's raw research/networking findings as a dated markdown file into
`~/research-feed/inbox/` -- the app's own extraction pipeline picks it up
automatically (runs hourly via cron) and turns it into tracked entities:

```bash
cat > ~/research-feed/inbox/"$(date +%F)"__hermes__morning-networking.md <<'EOF'
... the day's findings, any format ...
EOF
```

The filename must contain `hermes` (used to tag `source_agent`) and a
`YYYY-MM-DD` date. No need to pre-structure the content -- extraction handles
arbitrary layout.

## What this app does NOT store

Personal experiment results (MineJEPA-SWM numbers, V-JEPA runs, etc.) and
relationship-memory fields beyond what a todo naturally carries are out of
scope for research-feed by design -- it only tracks *external* signal (papers/
people/repos/jobs) plus the user's own todos/comments/drafts. Keep
`relationship_memory.json` / `reply_library.md` for anything beyond that.

## Notes

- Everything here is idempotent to check first, not idempotent to write --
  always dedup-check (`GET /api/feed?type=...&q=...`) before creating.
- A person appearing in a Reply Queue but with no todo isn't tracked as
  outreach yet -- only todo-linked people count as active commitments.
- The API key lives at `~/.hermes/scripts/research-feed-api-key`, `chmod 600`.
  Never print it, log it, or write it into any output.
