#!/usr/bin/env python3
"""Minimal local API serving the research-feed SQLite data. Stdlib only."""
from __future__ import annotations

import datetime as dt
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


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
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

    # ---- GET ----

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api/feed":
            limit = int(params.get("limit", ["50"])[0])
            offset = int(params.get("offset", ["0"])[0])
            rows = query(
                "SELECT * FROM entities ORDER BY novelty_score DESC, last_seen_date DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            self._send_json([deserialize_entity(r) for r in rows])
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
            order = {
                "added": "added_at DESC",
                "committed": "due_date ASC",
                "done": "done_at DESC",
            }.get(status, "added_at DESC")
            if status in ("added", "committed", "done"):
                rows = query(f"SELECT * FROM todos WHERE status = ? ORDER BY {order}", (status,))
            else:
                rows = query(f"SELECT * FROM todos ORDER BY {order}")
            self._send_json(rows)
            return

        if parsed.path.startswith("/api/todos/") and not parsed.path.endswith("/comments"):
            todo_id = parsed.path.rsplit("/", 1)[-1]
            rows = query("SELECT * FROM todos WHERE id = ?", (todo_id,))
            if not rows:
                self._send_json({"error": "not found"}, status=404)
                return
            todo = rows[0]
            todo["comments"] = query(
                "SELECT * FROM todo_comments WHERE todo_id = ? ORDER BY created_at ASC", (todo_id,)
            )
            self._send_json(todo)
            return

        if parsed.path == "/api/weekly-summary":
            rows = query("SELECT * FROM weekly_summaries ORDER BY generated_at DESC")
            self._send_json(rows)
            return

        if parsed.path == "/" or parsed.path.startswith("/app"):
            self._serve_static(parsed.path)
            return

        self._send_json({"error": "not found"}, status=404)

    # ---- POST ----

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path == "/api/todos":
            body = self._read_json_body()
            title = (body.get("title") or "").strip()
            if not title:
                self._send_json({"error": "title required"}, status=400)
                return
            todo_id = str(uuid.uuid4())
            now = dt.datetime.now().astimezone().isoformat()
            execute(
                """INSERT INTO todos (id, title, notes, source_entity_id, status, added_at)
                   VALUES (?, ?, ?, ?, 'added', ?)""",
                (todo_id, title, body.get("notes"), body.get("source_entity_id"), now),
            )
            rows = query("SELECT * FROM todos WHERE id = ?", (todo_id,))
            self._send_json(rows[0], status=201)
            return

        if parsed.path.startswith("/api/todos/") and parsed.path.endswith("/comments"):
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
                "INSERT INTO todo_comments (id, todo_id, body, created_at) VALUES (?, ?, ?, ?)",
                (comment_id, todo_id, text, now),
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

        rows = query("SELECT * FROM todos WHERE id = ?", (todo_id,))
        self._send_json(rows[0])

    # ---- DELETE ----

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
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
