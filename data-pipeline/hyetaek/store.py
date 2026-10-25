"""서버 DB 저장/조회. (SQLite)  upsert 는 '본문이 바뀌었을 때만' version 을 올린다."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def connect(path: str = "hyetaek.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    return con


def _next_version(con) -> int:
    return (con.execute("SELECT COALESCE(MAX(version),0) FROM notices").fetchone()[0]) + 1


def upsert(con, n: dict) -> str:
    """반환: 'new' | 'updated' | 'same'"""
    now = datetime.now().isoformat(timespec="seconds")
    row = con.execute("SELECT content_hash, deadline_at, dup_of, audience_json, extra_json, summary, topic, needs_review, deadline_kind FROM notices WHERE id=?", (n["id"],)).fetchone()
    dl = n["deadline"]
    changed = row is None or row["content_hash"] != n["content_hash"] or row["deadline_at"] != dl["at"] or row["dup_of"] != n.get("dup_of")
    if row is not None and not changed:      # 분류 규칙·AI 결과가 바뀐 경우도 갱신
        changed = (row["audience_json"] != json.dumps(n["audience"], ensure_ascii=False) or row["summary"] != n.get("summary")
                   or row["extra_json"] != json.dumps(n["extra"], ensure_ascii=False) or row["topic"] != n["topic"] or row["needs_review"] != int(n["needs_review"]) or row["deadline_kind"] != dl["kind"])
    if row is not None and not changed:
        con.execute("UPDATE notices SET is_active=1 WHERE id=?", (n["id"],))
        return "same"
    vals = (n["source"], n["source_key"], n["url"], n["title"], n["source_category"], n["topic"], n["posted_at"], dl["at"], dl["kind"],
            n.get("summary"), n["body_text"], n["content_kind"], int(n["needs_review"]), json.dumps(n["audience"], ensure_ascii=False),
            json.dumps(n["extra"], ensure_ascii=False), n["content_hash"], n.get("dup_of"))
    ver = _next_version(con)
    if row is None:
        con.execute("""INSERT INTO notices (id,version,source,source_key,url,title,source_category,topic,posted_at,deadline_at,deadline_kind,
                       summary,body_text,content_kind,needs_review,audience_json,extra_json,content_hash,dup_of,first_seen_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (n["id"], ver, *vals, now, now))
    else:
        con.execute("""UPDATE notices SET version=?,source=?,source_key=?,url=?,title=?,source_category=?,topic=?,posted_at=?,deadline_at=?,
                       deadline_kind=?,summary=?,body_text=?,content_kind=?,needs_review=?,audience_json=?,extra_json=?,content_hash=?,
                       dup_of=?,is_active=1,updated_at=? WHERE id=?""", (ver, *vals, now, n["id"]))
    for t in ("notice_deadlines", "notice_categories", "notice_files"):
        con.execute(f"DELETE FROM {t} WHERE notice_id=?", (n["id"],))
    for d in dl["list"]:
        if d.get("at"):
            con.execute("INSERT INTO notice_deadlines VALUES (?,?,?)", (n["id"], d.get("label"), d["at"]))
    for c in n["categories"]:
        if c:
            con.execute("INSERT OR IGNORE INTO notice_categories VALUES (?,?)", (n["id"], c))
    for a in n["attachments"]:
        con.execute("INSERT INTO notice_files VALUES (?,?,?,?)", (n["id"], "attachment", a.get("name"), a["url"]))
    for u in n["images"]:
        con.execute("INSERT INTO notice_files VALUES (?,?,?,?)", (n["id"], "image", None, u))
    return "new" if row is None else "updated"


def feed_since(con, version: int = 0, limit: int = 200) -> dict:
    """앱이 받는 응답. 중복(dup_of)은 제외하고, 마감/마감목록/파일을 함께 붙인다."""
    rows = con.execute("SELECT * FROM notices WHERE version>? AND dup_of IS NULL AND is_active=1 ORDER BY version LIMIT ?", (version, limit)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["audience"] = json.loads(d.pop("audience_json"))
        d["extra"] = json.loads(d.pop("extra_json") or "{}")
        lst = [dict(x) for x in con.execute("SELECT label,at FROM notice_deadlines WHERE notice_id=? ORDER BY at", (r["id"],))]
        d["deadline"] = {"at": d.pop("deadline_at"), "kind": d.pop("deadline_kind"), "list": lst}   # 앱이 받는 모양 = normalize 의 Notice 와 동일
        d["needs_review"] = bool(d["needs_review"])
        d["categories"] = [x[0] for x in con.execute("SELECT category FROM notice_categories WHERE notice_id=?", (r["id"],))]
        d["attachments"] = [dict(x) for x in con.execute("SELECT name,url FROM notice_files WHERE notice_id=? AND kind='attachment'", (r["id"],))]
        d["images"] = [x[0] for x in con.execute("SELECT url FROM notice_files WHERE notice_id=? AND kind='image'", (r["id"],))]
        d.pop("body_text", None)                          # 목록 응답에는 본문을 싣지 않는다 (상세에서 받는다)
        items.append(d)
    return {"items": items, "next_version": rows[-1]["version"] if rows else version}
