"""수집 결과(SSU:catch / JOB.ssu) + AI 결과(step4) → 공통 Notice(dict).
이 dict 한 모양이 서버 DB(notices 표)와 앱 API가 쓰는 모양이다. (SSU-PATH도 같은 모양으로 넣는다)"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from . import taxonomy as T

_NAMES = sorted(set(T.DEPT_TO_COLLEGE) | set(T.COLLEGES) | set(T.DEPT_ALIASES), key=len, reverse=True)
_NAME_RE = re.compile("(?:" + "|".join(re.escape(n) for n in _NAMES) + ")(?!원)")   # '경영대학원' ≠ 경영대학
_GRADE_RE = re.compile(r"([1-4])\s*학년")
_SEM_RANGE = re.compile(r"(\d{1,2})\s*학기\s*[~\-～]\s*(\d{1,2})\s*학기|(\d{1,2})\s*[~\-～]\s*(\d{1,2})\s*학기")
_SEM_UP = re.compile(r"(\d{1,2})\s*학기\s*이상")
_SEM_DOWN = re.compile(r"(\d{1,2})\s*학기\s*이하")


def semester_range(text: str):
    """'2~7학기' → (2, 7), '5학기 이상' → (5, None), '3학기 이하' → (None, 3). 제외·초과 같은 말이 있으면 뜻이 뒤집힐 수 있어 None."""
    if re.search(r"제외|불가|초과|미만", text):
        return None
    m = _SEM_RANGE.search(text)
    if m:
        a, b = [int(x) for x in m.groups() if x]
        return (a, b) if 1 <= a <= b <= 12 else None
    m = _SEM_UP.search(text)
    if m:
        return int(m.group(1)), None
    m = _SEM_DOWN.search(text)
    if m:
        return None, int(m.group(1))
    return None


def semester_grades(lo, hi):
    """학기 범위 → 학년(n학기 = ceil(n/2)학년). 예: 2~7학기 → 1~4학년, 5학기 이상 → 3~4학년."""
    lo, hi = lo or 1, min(hi or 8, 8)
    return set(range((lo + 1) // 2, (hi + 1) // 2 + 1))


_GPA_RE = re.compile(r"(?:GPA|평점|학점|평균)\D{0,6}([0-4](?:\.\d{1,2})?)\s*(?:/\s*4\.\d)?\s*이상")
_STATUS_WORDS = [("재학생", "ENROLLED"), ("재학", "ENROLLED"), ("복학 예정", "RETURNING"), ("복학예정", "RETURNING"),
                 ("휴학생", "LEAVE"), ("졸업예정", "GRADUATING"), ("졸업 예정", "GRADUATING"), ("졸업생", "GRADUATE"), ("졸업자", "GRADUATE")]


def norm_title(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t).lower()


def make_id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16]


def content_hash(title: str, body: str) -> str:
    return hashlib.sha1((norm_title(title) + "|" + norm_title(body)[:3000]).encode()).hexdigest()[:16]


def find_names(text: str):
    out = []
    for m in _NAME_RE.finditer(text):
        n = T.DEPT_ALIASES.get(m.group(0), m.group(0))
        if n not in out:
            out.append(n)
    return out


def tag_departments(title: str, body: str) -> dict:
    """제목에 학과/단과대가 있으면 high, 본문 앞부분에만 있으면 medium, 없으면 ALL."""
    names, conf = find_names(title), "high"
    if not names:
        names, conf = find_names(body[:400]), "medium"
    if not names or len(names) > 6:                      # 너무 많이 나열 = 사실상 전체
        return {"scope": "ALL", "colleges": [], "depts": [], "dept_confidence": "none"}
    colleges = [n for n in names if n in T.COLLEGES]
    direct = [n for n in names if n not in T.COLLEGES]
    depts = list(direct)
    for c in colleges:
        if any(T.DEPT_TO_COLLEGE.get(d) == c for d in direct):
            continue                                      # 'IT대학 전자정보공학부' 처럼 학과가 특정되면 단과대 전체로 펼치지 않는다
        depts += [d for d in T.COLLEGES[c] if d not in depts]
    for d in direct:
        c = T.DEPT_TO_COLLEGE.get(d)
        if c and c not in colleges:
            colleges.append(c)
    return {"scope": "DEPT" if direct else "COLLEGE", "colleges": colleges, "depts": depts, "dept_confidence": conf}


def empty_audience() -> dict:
    return {"scope": "ALL", "colleges": [], "depts": [], "dept_confidence": "none", "grades": [], "levels": [],
            "nationality": None, "statuses": [], "min_gpa": None, "other_conditions": [], "confidence": "low"}


def apply_conditions(aud: dict, conds: list[dict]) -> None:
    """AI가 뽑은 조건(type/value/evidence)을 구조 필드로 옮긴다. 옮길 수 없으면 other_conditions 로 둔다(= '확인 필요')."""
    gpas = set()
    for c in conds or []:
        t, v, ev = c.get("type", "other"), c.get("value", ""), c.get("evidence", "")
        text = f"{v} {ev}"
        placed = False
        if t == "grade":
            gs = {int(g) for g in _GRADE_RE.findall(text)}
            if gs and "이상" in text:
                gs = set(range(min(gs), 5))
            if gs:
                aud["grades"] = sorted(set(aud["grades"]) | gs)
                placed = True
        elif t == "department":
            names = find_names(text)
            if names:
                aud["depts"] = sorted(set(aud["depts"]) | set(names))
                aud["scope"] = "DEPT" if aud["scope"] == "ALL" else aud["scope"]
                placed = True
        elif t == "nationality":
            if "대한민국 국적" in text or "내국인" in text:
                aud["nationality"] = "DOMESTIC_ONLY"
                placed = True
            elif re.search(r"외국인\s*(유학생|구직자|학생)", text) and "제출" not in text:
                aud["nationality"] = "FOREIGN_ONLY"
                placed = True
        elif t == "status":
            st = [code for w, code in _STATUS_WORDS if w in text]
            if st:
                aud["statuses"] = sorted(set(aud["statuses"]) | set(st))
                placed = True
        elif t == "gpa":
            m = _GPA_RE.search(text)
            if m:
                gpas.add(float(m.group(1)))
                placed = True
        if not placed and t in ("grade", "other"):
            sr = semester_range(text)
            if sr:                                         # 학기 조건: 학기 범위를 그대로 저장 + 학년으로도 바꿔 둔다
                aud["min_semester"], aud["max_semester"] = sr
                gs = semester_grades(*sr)
                if gs != {1, 2, 3, 4}:
                    aud["grades"] = sorted(set(aud["grades"]) | gs)
                placed = True
        if not placed:
            aud["other_conditions"].append(v)
    if len(gpas) == 1:
        aud["min_gpa"] = gpas.pop()
    elif len(gpas) > 1:                                   # 프로그램마다 GPA가 다르면 하나로 못 정한다 → 확인 필요
        aud["other_conditions"].append(f"프로그램별 GPA 기준 상이({', '.join(str(g) for g in sorted(gpas))})")


def tag_basic(aud: dict, title: str, body: str, source_category: str | None) -> None:
    text = title + "\n" + body[:400]
    gs = sorted({int(g) for g in _GRADE_RE.findall(text)})
    if gs and not aud["grades"]:
        aud["grades"] = gs
    lv = set(aud["levels"])
    if "대학원" in title:
        lv.add("GRAD")
    if "학부생" in text or "재학생" in text or gs:
        lv.add("UNDERGRAD")
    aud["levels"] = sorted(lv)
    if source_category == "외국인유학생" and aud["nationality"] is None and "내국인" not in text:
        aud["nationality"] = "FOREIGN_ONLY"             # 사이트가 외국인 유학생 전용 게시판 (신뢰도는 medium)


def topic_of(source_category: str | None, title: str) -> str:
    topic = T.SOURCE_CATEGORY_TO_TOPIC.get(source_category or "", "기타")
    if (source_category in T.NARROWABLE) or topic == "기타":
        for tp, kws in T.KEYWORD_TOPIC:
            if any(k in title for k in kws):
                return tp
    return topic


def _iso(x):
    if not x:
        return None
    s = str(x).replace(" ", "T")
    return s[:16] if len(s) >= 16 else s[:10] + "T23:59"


def deadline_block(final, status, deadlines):
    kind = "FIXED" if final else {"OPEN_ENDED": "OPEN", "INFO_NO_DEADLINE": "NONE"}.get(status, "UNKNOWN")
    return {"at": _iso(final), "kind": kind, "list": [{"label": d.get("label"), "at": _iso(d.get("datetime") or d.get("at"))} for d in deadlines or []]}


SHORT_BODY = 300


def attachment_dependent(row: dict) -> bool:
    """본문이 짧고 첨부가 있으면 실제 지원 조건은 첨부(PDF 등)에 있을 가능성이 높다."""
    return bool(row.get("attachments")) and len((row.get("body") or "").strip()) < SHORT_BODY


def ai_extras(ai: dict, aud: dict) -> dict:
    """AI가 뽑은 행사 일정(마감 아님)과 성별 제한을 옮긴다. 있을 때만 넣는다(없으면 기존 모양 그대로)."""
    if ai.get("gender") in ("MALE_ONLY", "FEMALE_ONLY"):
        aud["gender"] = ai["gender"]
    ev = [{"label": e.get("label"), "at": _iso(e.get("datetime"))} for e in ai.get("events") or [] if e.get("datetime")]
    return {"events": ev} if ev else {}


def from_catch(row: dict, ai: dict | None) -> dict:
    ai = ai or {}
    body, title = row.get("body", ""), row["title"]
    aud = empty_audience()
    aud.update(tag_departments(title, body))
    apply_conditions(aud, ai.get("conditions"))
    cat = row.get("category")
    tag_basic(aud, title, body, cat)
    aud["confidence"] = "high" if (aud["scope"] != "ALL" or aud["grades"] or aud["nationality"]) else ("medium" if ai else "low")
    if attachment_dependent(row) and aud["confidence"] != "high":
        aud["confidence"] = "low"
    final = ai.get("final_deadline") or row.get("deadline")
    extra = ai_extras(ai, aud)
    return {
        "id": make_id("ssu_catch", row.get("slug") or row["url"]), "source": "ssu_catch", "source_key": row.get("slug") or row["url"],
        "url": row["url"], "title": title, "source_category": cat, "categories": row.get("categories") or [cat],
        "topic": topic_of(cat, title), "posted_at": (row.get("date") or "")[:10] or None,
        "deadline": deadline_block(final, row.get("deadline_status"), ai.get("deadlines")),
        "summary": ai.get("summary"), "body_text": body, "content_kind": row.get("content_kind", "TEXT"),
        "needs_review": bool(ai.get("needs_review")), "audience": aud,
        "attachments": row.get("attachments", []), "images": row.get("images", []),
        "content_hash": content_hash(title, body), "extra": extra,
    }


def from_job(row: dict, ai: dict | None) -> dict:
    ai = ai or {}
    body, title = row.get("body", ""), row["title"]
    aud = empty_audience()
    structured = bool((row.get("eligibility") or {}).get("parsed"))       # 진로취업프로그램: 사이트가 구조화한 대상 조건이 있으면 그것만 믿는다
    if not structured:
        apply_conditions(aud, ai.get("conditions"))
    tag_basic(aud, title, body, row.get("list"))
    aud["confidence"] = "medium" if ai else "low"
    if attachment_dependent(row):
        aud["confidence"] = "low"
    el = row.get("eligibility")
    if el and el.get("parsed"):                       # 진로취업프로그램: 사이트가 학적/학년/학위를 구조화해 둠 → AI 없이 높은 신뢰도
        aud["grades"] = sorted(set(aud["grades"]) | set(el["grades"]))
        aud["statuses"] = sorted(set(aud["statuses"]) | set(el["statuses"]))
        aud["levels"] = sorted(set(aud["levels"]) | set(el["levels"]))
        aud["other_conditions"] += el["other"]
        aud["confidence"] = "high"
    if row.get("deadline_source") == "program_field":      # 목록에 구조화된 신청기간이 있으면 AI보다 우선
        final = row.get("deadline") or ai.get("final_deadline")
    else:
        final = ai.get("final_deadline") or row.get("deadline")
    key = (row.get("fields") or {}).get("path_seq") or row["url"]
    extra = ai_extras(ai, aud)
    return {
        "id": make_id("job_ssu", row["url"]), "source": "job_ssu", "source_key": row["url"],
        "url": row["url"], "title": title, "source_category": row.get("list"), "categories": [row.get("list")],
        "topic": topic_of(row.get("list"), title), "posted_at": (row.get("posted") or "")[:10] or None,
        "deadline": deadline_block(final, None if final else "UNKNOWN", ai.get("deadlines") or row.get("deadlines")),
        "summary": ai.get("summary") or row.get("summary"), "body_text": body, "content_kind": row.get("content_kind", "TEXT"),
        "needs_review": bool(ai.get("needs_review")) and not structured, "audience": aud,
        "attachments": row.get("attachments", []), "images": row.get("images", []),
        "content_hash": content_hash(title, body),
        "extra": {"company": row.get("company"), "employment_type": row.get("employment_type"), "region": row.get("region"),
                  "job_category": row.get("job_category"), "path_seq": (row.get("fields") or {}).get("path_seq"),
                  "apply_url": row.get("apply_url"), "sessions": row.get("sessions"), "program": row.get("program"),
                  "summary_from_image": bool(structured and ai.get("needs_review")),
                  "deadline_source": row.get("deadline_source"), **extra},
    }


def dedupe(notices: list[dict]) -> list[dict]:
    """같은 글이 둘 이상이면 하나만 남기고 나머지는 dup_of 로 표시한다. (삭제하지 않는다)
    기준: ① 같은 출처에서 제목+게시일이 같음(다른 카테고리에 중복 게시) ② 본문 해시가 같음(다른 번호로 재등록)"""
    seen_title, seen_hash = {}, {}
    for n in notices:
        n.setdefault("dup_of", None)
        k1 = (n["source"], norm_title(n["title"]), n["posted_at"])
        k2 = n["content_hash"] if len(n["body_text"]) > 150 else None
        first = seen_title.get(k1) or (seen_hash.get(k2) if k2 else None)
        if first and first["id"] != n["id"]:
            n["dup_of"] = first["id"]
            first["categories"] = sorted(set(first["categories"]) | set(n["categories"]), key=str)
        else:
            seen_title[k1] = n
            if k2:
                seen_hash[k2] = n
    return notices
