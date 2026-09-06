# Research Feed

Turns daily AI-research digests (from your research agents) into a swipeable,
reel-style feed you can install on your phone as a PWA — one card per item,
tap to expand, tap out to the raw source. Plus a daily log view.

## How it works

1. Drop each day's raw markdown digest into `inbox/` (e.g.
   `2026-09-04_hermes-briefing.md`, `2026-09-04_chatgpt-log.md`). The source
   agent is inferred from the filename (`chatgpt` / `hermes`); the date is
   inferred from a `YYYY-MM-DD` in the filename, falling back to today.
2. `extract/extract.py` reads unprocessed inbox files, asks the local
   `hermes` CLI to normalize each day's markdown (whatever section layout it
   happens to use) into a fixed entity schema, dedups against existing rows,
   and writes to `data/research.db` (SQLite).
3. `extract/cron_runner.py` is the scheduled entrypoint (same silent-wrapper
   contract as voicecoach-desktop's cron runner: quiet on success, non-zero
   exit on failure so Hermes cron alerts).
4. `server/server.py` serves a small JSON API plus the `web/` PWA over HTTP.

## Run it

```bash
# one-off extraction of whatever's in inbox/
python3 extract/extract.py --once

# serve the API + PWA
python3 server/server.py
# then open http://localhost:8787/app
```

No dependencies beyond the Python standard library and the `hermes` CLI
already installed at `~/.local/bin/hermes`.

## Data model

- `entities` — one row per distinct paper/person/repo/job/insight/track-update/
  action-item, with a `novelty_score` used to rank the feed.
- `mentions` — every time an entity is referenced (possibly the same entity
  shows up in multiple sections/documents on the same day); these collapse
  into one `entities` row instead of duplicating.

## Agent access

Any agent (Hermes, or something else entirely) can read and write to research-feed
over the same JSON API the PWA uses — feed, todos, comments, drafts, and a bundled
`GET /api/context/daily` for personalized context. Your own browser use stays
key-free; an agent authenticates via an `X-API-Key` header.

```bash
# create a key (printed once -- copy it, it can't be shown again)
python3 server/manage_keys.py create --name hermes-vm --scope readwrite   # or --scope read
python3 server/manage_keys.py list
python3 server/manage_keys.py revoke --id <id>
```

- `read` keys can only `GET`; `readwrite` keys can also `POST`/`PATCH`/`DELETE`.
- A request with no key at all is treated as trusted/anonymous (this is what the PWA
  does) and always allowed — the key is for granting and later revoking *other*
  agents' access, not for locking out your own client.
- Writes made with a key are attributed: `todos`, `todo_comments`, and `drafts` rows
  get a `created_by` set to the key's name, so you can tell what an agent added versus
  what you added yourself.

## Known follow-up

The server binds to `0.0.0.0` so it's reachable on your LAN, but for real
phone access outside your home network you'll want this behind Tailscale (or
similar) or deployed to a small always-on host. Not set up yet.
