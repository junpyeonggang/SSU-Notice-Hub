"""우리 DB(hyetaek)의 공지를 팀 공통 형식(notice.schema.json)으로 내보낸다.
실행(ssu-steps 폴더에서):  python export_common.py        → common_notices.json
입력: hyetaek.db (build_db 결과). 개인정보는 원래 DB에 없다."""
from __future__ import annotations
import hashlib, json, sys
from datetime import datetime

def _at(s):                       # 'YYYY-MM-DDTHH:MM' → 'YYYY-MM-DDTHH:MM:00+09:00'
    if not s: return None
    s = s if len(s) >= 16 else s[:10] + "T23:59"
    return s[:16] + ":00+09:00"

def _local(s):                    # 시간대 없는 저장 시각 → 이 컴퓨터의 시간대(+09:00 등)를 붙여 명시
    if not s: return None
    try:
        return datetime.fromisoformat(s).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return s

def _src_id(n):
    """짧고 안전한 번호. 한글·특수문자가 섞인 긴 주소(slug)는 해시로 줄인다."""
    ex = n.get("extra") or {}
    key = str(ex.get("path_seq") or n.get("source_key") or "")
    if not key or key.startswith("http"):
        key = n["url"]
    key = key.rstrip("/").split("/")[-1] if key.startswith("http") is False and "/" in key else key
    if not key.isascii() or len(key) > 40 or not key.replace("-", "").replace("_", "").isalnum():
        return hashlib.sha1(key.encode()).hexdigest()[:12]
    return key

def to_common(n: dict) -> dict:
    dl, aud = n["deadline"], n.get("audience") or {}
    dls = []
    for d in dl.get("list") or []:
        at = _at(d.get("at"))
        if at:
            lab = d.get("label")
            dls.append({"kind": "APPLICATION" if lab else "OTHER", "label": lab or "마감", "date": at[:10], "at": at,
                        "precision": "DAY" if at[11:16] == "23:59" else "MINUTE"})
    if not dls and dl.get("at"):
        at = _at(dl["at"])
        dls.append({"kind": "OTHER", "label": "마감", "date": at[:10], "at": at, "precision": "DAY" if at[11:16] == "23:59" else "MINUTE"})
    ex = dict(n.get("extra") or {})
    for e in ex.pop("events", None) or []:                      # 행사일(훈련·설명회 등). 마감이 아니므로 deadline_at 에는 들어가지 않는다
        at = _at(e.get("at"))
        if at:
            dls.append({"kind": "EVENT", "label": e.get("label") or "행사", "date": at[:10], "at": at, "precision": "DAY" if at[11:16] in ("00:00", "23:59") else "MINUTE"})   # 시간 없이 날짜만 있으면 AI가 00:00으로 준다 → 날짜만 의미
    elig = {k: aud[k] for k in ("scope", "colleges", "depts", "grades", "min_semester", "max_semester", "levels", "statuses", "gender", "nationality", "min_gpa", "other_conditions", "confidence") if k in aud}
    sid = _src_id(n)
    return {
        "id": f"{n['source']}:{sid}", "source": n["source"], "source_id": sid, "url": n["url"], "title": n["title"],
        "topic": n["topic"], "posted_at": n.get("posted_at"), "updated_at": _local(n.get("updated_at")),
        "deadline_status": dl["kind"], "deadline_at": _at(dl.get("at")), "deadlines": dls,
        "eligibility": elig, "summary": n.get("summary"), "body": n.get("body_text"), "needs_review": bool(n.get("needs_review")),
        "content_kind": n.get("content_kind") or "TEXT",
        "attachments": [{"name": a.get("name"), "url": a["url"]} if isinstance(a, dict) else {"name": None, "url": a} for a in n.get("attachments") or []],
        "extra": {**ex, "source_key": n.get("source_key")},
    }

def main(db="hyetaek.db", out="common_notices.json"):
    from hyetaek import store
    con = store.connect(db)
    items = store.feed_since(con, 0, 100000)["items"]
    body = dict(con.execute("SELECT id, body_text FROM notices").fetchall())      # feed 응답은 본문을 빼므로 DB에서 직접 읽는다
    for n in items:
        n["body_text"] = body.get(n["id"])
    data = [to_common(n) for n in items]
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(data)}건 → {out}")

if __name__ == "__main__":
    main(*sys.argv[1:])
