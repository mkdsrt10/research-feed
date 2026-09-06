#!/usr/bin/env python3
"""Minimal local API serving the research-feed SQLite data. Stdlib only."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "research.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"
PORT = 8787

sys.path.insert(0, str(ROOT / "extract"))
import weekly_summary  # noqa: E402
import entity_reply  # noqa: E402


# (table, column, sqlite type) -- columns added after these tables already existed
# in the wild get migrated in place here rather than via schema.sql (ALTER TABLE has
# no "IF NOT EXISTS", and a duplicate-column error would abort the whole executescript).
MIGRATED_COLUMNS = [
    ("todos", "created_by", "TEXT"),
    ("drafts", "created_by", "TEXT"),
    ("todo_comments", "created_by", "TEXT"),
    ("entities", "liked_at", "TEXT"),
    ("entities", "saved_at", "TEXT"),
]


def _ensure_migrated_columns(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATED_COLUMNS:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    _ensure_migrated_columns(conn)
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def deserialize_entity(row: dict) -> dict:
    row["tags"] = json.loads(row.get("tags") or "[]")
    row["extra"] = json.loads(row.get("extra") or "{}")
    return row


# Every todo read joins its linked entity (if any) so callers -- the UI and any
# agent -- can tell what a todo is *about* (e.g. a person, for networking) without
# a second round-trip.
TODO_SELECT = """
    SELECT t.*, e.type AS source_entity_type, e.title AS source_entity_title,
           e.extra AS source_entity_extra
    FROM todos t LEFT JOIN entities e ON e.id = t.source_entity_id
"""


def deserialize_todo(row: dict) -> dict:
    if row.get("source_entity_extra"):
        row["source_entity_extra"] = json.loads(row["source_entity_extra"])
    return row


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def _authenticate(self, write: bool = False):
        """Optional API-key auth for agent access. No key -> anonymous/trusted (the PWA
        itself never sends one). A key, if present, must be valid; returns the key row
        (for created_by attribution), None if anonymous, or False if it already sent an
        error response and the caller should abort."""
        raw = self.headers.get("X-API-Key")
        if not raw:
            return None
        key_hash = hashlib.sha256(raw.encode()).hexdigest()
        rows = query("SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL", (key_hash,))
        if not rows:
            self._send_json({"error": "invalid or revoked API key"}, status=401)
            return False
        key = rows[0]
        if write and key["scope"] != "readwrite":
            self._send_json({"error": "this key is read-only"}, status=403)
            return False
        execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (dt.datetime.now().astimezone().isoformat(), key["id"]))
        return key

    # ---- GET ----

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/feed":
            limit = int(params.get("limit", ["50"])[0])
            offset = int(params.get("offset", ["0"])[0])
            include_seen = params.get("include_seen", ["0"])[0] == "1"
            entity_type = params.get("type", [None])[0]
            title_query = params.get("q", [None])[0]
            # No explicit type -> the main reel, scoped to papers (+ pending drafts, merged below).
            # An explicit ?type= (e.g. Hermes's dedup checks) bypasses this scoping entirely.
            scoped_to_papers = entity_type is None

            clauses = [] if include_seen else ["id NOT IN (SELECT entity_id FROM entity_views)"]
            sql_params: list = []
            if entity_type:
                clauses.append("type = ?")
                sql_params.append(entity_type)
            elif scoped_to_papers:
                clauses.append("type = 'paper'")
            if title_query:
                clauses.append("title LIKE ?")
                sql_params.append(f"%{title_query}%")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

            rows = query(
                f"SELECT * FROM entities {where} ORDER BY novelty_score DESC, last_seen_date DESC",
                tuple(sql_params),
            )
            items = [deserialize_entity(r) for r in rows]

            if scoped_to_papers and not title_query:
                draft_rows = query(
                    "SELECT * FROM drafts WHERE status = 'pending' ORDER BY created_at DESC"
                )
                for d in draft_rows:
                    items.append({
                        "id": d["id"],
                        "type": "draft",
                        "title": f"{d['platform']} post",
                        "one_liner": d["content"][:120],
                        "summary": d["content"],
                        "raw_url": None,
                        "tags": [],
                        "extra": {"platform": d["platform"]},
                        "novelty_score": 1.0,
                        "first_seen_date": d["created_at"][:10],
                        "last_seen_date": d["created_at"][:10],
                    })
                items.sort(key=lambda e: (e["novelty_score"], e["last_seen_date"]), reverse=True)

            self._send_json(items[offset:offset + limit])
            return

        if parsed.path.startswith("/api/entity/"):
            entity_id = parsed.path.rsplit("/", 1)[-1]
            rows = query("SELECT * FROM entities WHERE id = ?", (entity_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            entity = deserialize_entity(rows[0])
            entity["mentions"] = query(
                "SELECT date, source_agent, source_section, context_snippet FROM mentions "
                "WHERE entity_id = ? ORDER BY date DESC",
                (entity_id,),
            )
            entity["comments"] = query(
                "SELECT * FROM entity_comments WHERE entity_id = ? ORDER BY created_at ASC",
                (entity_id,),
            )
            self._send_json(entity)
            return

        if parsed.path.startswith("/api/log/"):
            date = parsed.path.rsplit("/", 1)[-1]
            rows = query(
                """SELECT DISTINCT e.* FROM entities e
                   JOIN mentions m ON m.entity_id = e.id
                   WHERE m.date = ?
                   ORDER BY e.novelty_score DESC""",
                (date,),
            )
            self._send_json([deserialize_entity(r) for r in rows])
            return

        if parsed.path == "/api/todos":
            status = params.get("status", [None])[0]
            entity_type = params.get("entity_type", [None])[0]
            order = {
                "added": "t.added_at DESC",
                "committed": "t.due_date ASC",
                "done": "t.done_at DESC",
            }.get(status, "t.added_at DESC")
            clauses, sql_params = [], []
            if status in ("added", "committed", "done"):
                clauses.append("t.status = ?")
                sql_params.append(status)
            if entity_type:
                clauses.append("e.type = ?")
                sql_params.append(entity_type)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = query(f"{TODO_SELECT} {where} ORDER BY {order}", tuple(sql_params))
            self._send_json([deserialize_todo(r) for r in rows])
            return

        if parsed.path.startswith("/api/todos/") and not parsed.path.endswith("/comments"):
            todo_id = parsed.path.rsplit("/", 1)[-1]
            rows = query(f"{TODO_SELECT} WHERE t.id = ?", (todo_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            todo = deserialize_todo(rows[0])
            todo["comments"] = query(
                "SELECT * FROM todo_comments WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
            )
            self._send_json(todo)
            return

        if parsed.path == "/api/weekly-summary":
            rows = query("SELECT * FROM weekly_summaries ORDER BY generated_at DESC")
            self._send_json(rows)
            return

        if parsed.path == "/api/saved":
            rows = query("SELECT * FROM entities WHERE saved_at IS NOT NULL ORDER BY saved_at DESC")
            self._send_json([deserialize_entity(r) for r in rows])
            return

        if parsed.path == "/api/drafts":
            status = params.get("status", [None])[0]
            if status:
                rows = query("SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                rows = query("SELECT * FROM drafts ORDER BY created_at DESC")
            self._send_json(rows)
            return

        if parsed.path == "/api/context/daily":
            committed = [deserialize_todo(r) for r in query(
                f"{TODO_SELECT} WHERE t.status = 'committed' ORDER BY t.due_date ASC"
            )]
            added = [deserialize_todo(r) for r in query(
                f"{TODO_SELECT} WHERE t.status = 'added' ORDER BY t.added_at DESC"
            )]
            self._send_json({
                "committed_todos": committed,
                "added_todos": added,
                "networking_todos": [
                    t for t in committed + added if t.get("source_entity_type") == "person"
                ],
                "recent_comments": query(
                    """SELECT tc.body, tc.created_at, t.title AS todo_title
                       FROM todo_comments tc JOIN todos t ON t.id = tc.todo_id
                       ORDER BY tc.created_at DESC LIMIT 10"""
                ),
                "pending_drafts": query(
                    "SELECT id, platform, content FROM drafts WHERE status = 'pending' ORDER BY created_at DESC"
                ),
            })
            return

        if parsed.path == "/" or parsed.path.startswith("/app"):
            self._serve_static(parsed.path)
            return

        self._send_json({"error": "not found"}, status=404)

    # ---- POST ----

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path.startswith("/api/entity/") and parsed.path.endswith("/view"):
            entity_id = parsed.path.split("/")[3]
            body = self._read_json_body()
            duration_ms = int(body.get("duration_ms") or 0)
            context = body.get("context") or "card"
            if duration_ms < 1000:
                self._send_json({"skipped": True})
                return
            execute(
                "INSERT INTO entity_views (id, entity_id, viewed_at, duration_ms, context) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), entity_id, dt.datetime.now().astimezone().isoformat(),
                 duration_ms, context),
            )
            self._send_json({"ok": True}, status=201)
            return

        if parsed.path.startswith("/api/entity/") and parsed.path.endswith("/interact"):
            entity_id = parsed.path.split("/")[3]
            body = self._read_json_body()
            action = (body.get("action") or "").strip()
            if not action:
                self._send_json({"error": "action required"}, status=400)
                return
            execute(
                "INSERT INTO entity_interactions (id, entity_id, action, created_at) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), entity_id, action, dt.datetime.now().astimezone().isoformat()),
            )
            self._send_json({"ok": True}, status=201)
            return

        if parsed.path.startswith("/api/entity/") and parsed.path.endswith("/comments"):
            entity_id = parsed.path.split("/")[3]
            rows = query("SELECT * FROM entities WHERE id = ?", (entity_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            entity = deserialize_entity(rows[0])
            body = self._read_json_body()
            text = (body.get("body") or "").strip()
            if not text:
                self._send_json({"error": "body required"}, status=400)
                return

            now = dt.datetime.now().astimezone().isoformat()
            comment_id = str(uuid.uuid4())
            execute(
                "INSERT INTO entity_comments (id, entity_id, body, author, created_at) "
                "VALUES (?, ?, ?, 'user', ?)",
                (comment_id, entity_id, text, now),
            )
            comment = query("SELECT * FROM entity_comments WHERE id = ?", (comment_id,))[0]

            reply_text = entity_reply.generate_reply(entity, text)
            reply = None
            if reply_text:
                reply_id = str(uuid.uuid4())
                reply_now = dt.datetime.now().astimezone().isoformat()
                execute(
                    "INSERT INTO entity_comments (id, entity_id, body, author, created_at) "
                    "VALUES (?, ?, ?, 'hermes', ?)",
                    (reply_id, entity_id, reply_text, reply_now),
                )
                reply = query("SELECT * FROM entity_comments WHERE id = ?", (reply_id,))[0]

            self._send_json({"comment": comment, "reply": reply}, status=201)
            return

        if parsed.path.startswith("/api/entity/") and parsed.path.endswith("/like"):
            entity_id = parsed.path.split("/")[3]
            rows = query("SELECT liked_at FROM entities WHERE id = ?", (entity_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            new_value = None if rows[0]["liked_at"] else dt.datetime.now().astimezone().isoformat()
            execute("UPDATE entities SET liked_at = ? WHERE id = ?", (new_value, entity_id))
            self._send_json({"liked_at": new_value})
            return

        if parsed.path.startswith("/api/entity/") and parsed.path.endswith("/save"):
            entity_id = parsed.path.split("/")[3]
            rows = query("SELECT saved_at FROM entities WHERE id = ?", (entity_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            new_value = None if rows[0]["saved_at"] else dt.datetime.now().astimezone().isoformat()
            execute("UPDATE entities SET saved_at = ? WHERE id = ?", (new_value, entity_id))
            self._send_json({"saved_at": new_value})
            return

        if parsed.path == "/api/drafts":
            key = self._authenticate(write=True)
            if key is False:
                return
            body = self._read_json_body()
            platform = (body.get("platform") or "").strip()
            content = (body.get("content") or "").strip()
            if platform not in ("x", "linkedin") or not content:
                self._send_json({"error": "platform ('x'|'linkedin') and content required"}, status=400)
                return
            draft_id = str(uuid.uuid4())
            execute(
                """INSERT INTO drafts (id, platform, content, status, source_entity_id, source_todo_id,
                                       created_at, created_by)
                   VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)""",
                (draft_id, platform, content, body.get("source_entity_id"), body.get("source_todo_id"),
                 dt.datetime.now().astimezone().isoformat(), key["name"] if key else None),
            )
            rows = query("SELECT * FROM drafts WHERE id = ?", (draft_id,))
            self._send_json(rows[0], status=201)
            return

        if parsed.path == "/api/todos":
            key = self._authenticate(write=True)
            if key is False:
                return
            body = self._read_json_body()
            title = (body.get("title") or "").strip()
            if not title:
                self._send_json({"error": "title required"}, status=400)
                return
            todo_id = str(uuid.uuid4())
            now = dt.datetime.now().astimezone().isoformat()
            execute(
                """INSERT INTO todos (id, title, notes, source_entity_id, status, added_at, created_by)
                   VALUES (?, ?, ?, ?, 'added', ?, ?)""",
                (todo_id, title, body.get("notes"), body.get("source_entity_id"), now,
                 key["name"] if key else None),
            )
            rows = query(f"{TODO_SELECT} WHERE t.id = ?", (todo_id,))
            self._send_json(deserialize_todo(rows[0]), status=201)
            return

        if parsed.path.startswith("/api/todos/") and parsed.path.endswith("/comments"):
            key = self._authenticate(write=True)
            if key is False:
                return
            todo_id = parsed.path.split("/")[3]
            if not query("SELECT id FROM todos WHERE id = ?", (todo_id,)):
                self._send_json({"error": "not found"}, status=404)
                return
            body = self._read_json_body()
            text = (body.get("body") or "").strip()
            if not text:
                self._send_json({"error": "body required"}, status=400)
                return
            comment_id = str(uuid.uuid4())
            now = dt.datetime.now().astimezone().isoformat()
            execute(
                "INSERT INTO todo_comments (id, todo_id, body, created_at, created_by) VALUES (?, ?, ?, ?, ?)",
                (comment_id, todo_id, text, now, key["name"] if key else None),
            )
            rows = query("SELECT * FROM todo_comments WHERE id = ?", (comment_id,))
            self._send_json(rows[0], status=201)
            return

        if parsed.path == "/api/weekly-summary":
            conn = get_conn()
            try:
                row = weekly_summary.generate(conn)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)
                return
            finally:
                conn.close()
            self._send_json(row, status=201)
            return

        self._send_json({"error": "not found"}, status=404)

    # ---- PATCH ----

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        key = self._authenticate(write=True)
        if key is False:
            return

        if parsed.path.startswith("/api/drafts/"):
            draft_id = parsed.path.rsplit("/", 1)[-1]
            if not query("SELECT id FROM drafts WHERE id = ?", (draft_id,)):
                self._send_json({"error": "not found"}, status=404)
                return
            body = self._read_json_body()
            status = body.get("status")
            if status not in ("pending", "approved", "rejected", "posted"):
                self._send_json({"error": "invalid status"}, status=400)
                return
            execute(
                "UPDATE drafts SET status = ?, reviewed_at = ? WHERE id = ?",
                (status, dt.datetime.now().astimezone().isoformat(), draft_id),
            )
            rows = query("SELECT * FROM drafts WHERE id = ?", (draft_id,))
            self._send_json(rows[0])
            return

        if not parsed.path.startswith("/api/todos/"):
            self._send_json({"error": "not found"}, status=404)
            return

        todo_id = parsed.path.rsplit("/", 1)[-1]
        existing = query("SELECT * FROM todos WHERE id = ?", (todo_id,))
        if not existing:
            self._send_json({"error": "not found"}, status=404)
            return

        body = self._read_json_body()
        now = dt.datetime.now().astimezone().isoformat()
        fields, values = [], []

        if "title" in body:
            fields.append("title = ?")
            values.append(body["title"])
        if "notes" in body:
            fields.append("notes = ?")
            values.append(body["notes"])
        if "due_date" in body:
            fields.append("due_date = ?")
            values.append(body["due_date"])
            if body["due_date"]:
                fields.append("committed_at = ?")
                values.append(now)
                if existing[0]["status"] != "done":
                    fields.append("status = 'committed'")
            elif existing[0]["status"] != "done":
                fields.append("status = 'added'")
                fields.append("committed_at = NULL")
        if "done" in body:
            if body["done"]:
                fields.append("done_at = ?")
                values.append(now)
                fields.append("status = 'done'")
            else:
                fields.append("done_at = NULL")
                fields.append("status = ?")
                values.append("committed" if existing[0]["due_date"] else "added")

        if fields:
            values.append(todo_id)
            execute(f"UPDATE todos SET {', '.join(fields)} WHERE id = ?", tuple(values))

        rows = query(f"{TODO_SELECT} WHERE t.id = ?", (todo_id,))
        self._send_json(deserialize_todo(rows[0]))

    # ---- DELETE ----

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        key = self._authenticate(write=True)
        if key is False:
            return
        if not parsed.path.startswith("/api/todos/"):
            self._send_json({"error": "not found"}, status=404)
            return
        todo_id = parsed.path.rsplit("/", 1)[-1]
        execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        self._send_json({"ok": True})

    # ---- static ----

    def _serve_static(self, path: str) -> None:
        web_dir = ROOT / "web"
        rel = "index.html" if path in ("/", "/app") else path.split("/app/", 1)[-1]
        file_path = (web_dir / rel).resolve()
        if web_dir not in file_path.parents and file_path != web_dir:
            self._send_json({"error": "forbidden"}, status=403)
            return
        if not file_path.exists():
            self._send_json({"error": "not found"}, status=404)
            return
        content_type = {
            ".html": "text/html", ".js": "application/javascript",
            ".css": "text/css", ".json": "application/json",
        }.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"research-feed API + web serving on http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
