#!/usr/bin/env python3
"""Create/list/revoke API keys for external agents (Hermes, etc.) to access research-feed.

Keys are never stored in plaintext -- only a sha256 hash. A newly created key is
printed once; if lost, revoke it and create a new one.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import secrets
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "research.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def cmd_create(args: argparse.Namespace) -> None:
    conn = get_conn()
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO api_keys (id, name, key_hash, scope, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_id, args.name, key_hash, args.scope, dt.datetime.now().astimezone().isoformat()),
    )
    conn.commit()
    print(f"Created key '{args.name}' (scope: {args.scope}, id: {key_id})")
    print("Copy this now -- it will not be shown again:\n")
    print(raw_key)
    print("\nUse it as a header: X-API-Key: " + raw_key)


def cmd_list(args: argparse.Namespace) -> None:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, scope, created_at, last_used_at, revoked_at FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    if not rows:
        print("No keys yet.")
        return
    for r in rows:
        status = "REVOKED" if r["revoked_at"] else "active"
        print(f"{r['id']}  {r['name']:<20} {r['scope']:<10} {status:<8} "
              f"created={r['created_at'][:19]}  last_used={(r['last_used_at'] or 'never')[:19]}")


def cmd_revoke(args: argparse.Namespace) -> None:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (dt.datetime.now().astimezone().isoformat(), args.id),
    )
    conn.commit()
    print(f"Revoked {args.id}" if cur.rowcount else f"No active key found with id {args.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a new key")
    p_create.add_argument("--name", required=True, help="human label, e.g. hermes-vm")
    p_create.add_argument("--scope", choices=["read", "readwrite"], required=True)
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="list all keys")
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", help="revoke a key by id")
    p_revoke.add_argument("--id", required=True)
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
