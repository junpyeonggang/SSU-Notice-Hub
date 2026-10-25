"""사용자 맞춤 판정. ※ 이 로직은 '폰 안'에서 돈다. 서버는 프로필을 모른다.
여기서는 Python 으로 규칙과 테스트를 확정하고, 앱에서는 같은 규칙을 Java 로 옮긴다.

3단계 판정
  MATCH   알려진 조건을 모두 만족하고, 모르는 조건이 없다
  CHECK   모르는 게 있다(내 프로필이 비어 있음 / 공지에 세부 조건이 있음 / 이미지·첨부에만 내용이 있음)
  NO      공지가 '명시적으로' 나를 제외한다 (다른 학과 대상, 대학원생 전용, 외국인 전용 ...)
  EXPIRED 마감이 지났다
원칙: 모르면 제외하지 않는다. 제외는 근거가 있을 때만."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import taxonomy as T


@dataclass
class Profile:
    dept: str | None = None                  # 정식 학과명 (taxonomy.COLLEGES 의 값)
    grade: int | None = None                 # 1~4
    term: int | None = None                  # 지금 몇 학기인지 1 또는 2 (학년과 합쳐 '몇 번째 학기'를 계산)
    status: str | None = None                # ENROLLED | LEAVE | RETURNING | GRADUATING | GRADUATE
    nationality: str | None = None           # DOMESTIC | FOREIGN
    level: str | None = None                 # UNDERGRAD | GRAD
    gpa: float | None = None
    interests: set = field(default_factory=set)      # 관심 주제 (비어 있으면 '전체')
    job_regions: list = field(default_factory=list)  # 채용/알바 선호 지역
    job_types: list = field(default_factory=list)    # 정규직/인턴/계약직 ...

    @property
    def college(self):
        return T.DEPT_TO_COLLEGE.get(self.dept) if self.dept else None


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def deadlines_of(n: dict):
    out = [_dt(n["deadline"]["at"])] if n["deadline"].get("at") else []
    out += [_dt(d["at"]) for d in n["deadline"].get("list", []) if d.get("at")]
    return sorted(set(x for x in out if x))


def next_deadline(n: dict, now: datetime):
    up = [d for d in deadlines_of(n) if d >= now]
    return up[0] if up else None


def judge(n: dict, p: Profile, now: datetime) -> dict:
    a, why_no, why_check, why_ok = n["audience"], [], [], []
    ds = deadlines_of(n)
    if n["deadline"]["kind"] == "FIXED" and ds and max(ds) < now:
        return {"verdict": "EXPIRED", "score": 0, "reasons": [f"마감 지남 ({max(ds):%m.%d})"], "id": n["id"]}

    # ---- 학과/단과대
    if a["scope"] in ("DEPT", "COLLEGE"):
        if p.dept is None:
            why_check.append("내 학과를 입력하면 정확해져요")
        elif p.dept in a["depts"] or (a["scope"] == "COLLEGE" and p.college in a["colleges"]):
            why_ok.append(("dept", f"{p.dept} 대상"))
        elif a.get("dept_confidence") == "medium":
            why_check.append("본문에 다른 학과 이름이 있어요(제목엔 없음)")
        else:
            why_no.append("대상 학과: " + ", ".join(a["colleges"] if a["scope"] == "COLLEGE" else a["depts"][:3]))
    # ---- 학년
    if a["grades"]:
        if p.grade is None:
            why_check.append("내 학년을 입력하면 정확해져요")
        elif p.grade in a["grades"]:
            why_ok.append(("grade", f"{p.grade}학년 대상"))
        else:
            why_no.append("대상 학년: " + ",".join(map(str, a["grades"])))
    # ---- 학기 (예: 2~7학기 → 1학년 1학기, 4학년 2학기는 제외)
    lo, hi = a.get("min_semester"), a.get("max_semester")
    if lo or hi:
        if p.grade is None or p.term is None:
            why_check.append("학년·학기를 입력하면 정확해져요")
        else:
            sem = (p.grade - 1) * 2 + p.term
            if (lo and sem < lo) or (hi and sem > hi):
                why_no.append(f"대상 학기: {lo or ''}~{hi or ''}학기")
    # ---- 학부/대학원
    if a["levels"] and len(a["levels"]) == 1 and p.level:
        if p.level not in a["levels"]:
            why_no.append("대학원 대상" if a["levels"] == ["GRAD"] else "학부생 대상")
    # ---- 국적
    if a["nationality"]:
        if p.nationality is None:
            why_check.append("내국인/외국인 정보가 필요해요")
        elif (a["nationality"] == "FOREIGN_ONLY") != (p.nationality == "FOREIGN"):
            why_no.append("외국인 유학생 대상" if a["nationality"] == "FOREIGN_ONLY" else "내국인 대상")
    # ---- 재학 상태
    if a["statuses"]:
        if p.status is None:
            why_check.append("재학 상태를 입력하면 정확해져요")
        elif p.status not in a["statuses"]:
            why_no.append("대상 상태 불일치")
    # ---- 성적
    if a["min_gpa"]:
        if p.gpa is None:
            why_check.append(f"평점 {a['min_gpa']} 이상 필요")
        elif p.gpa < a["min_gpa"]:
            why_no.append(f"평점 {a['min_gpa']} 이상 필요")
    # ---- 모르는 것들
    if a["confidence"] == "low":
        why_check.append("대상 조건을 아직 분석하지 못했어요")
    if a["other_conditions"]:
        why_check.append("세부 조건 확인: " + a["other_conditions"][0][:30] + (" 외" if len(a["other_conditions"]) > 1 else ""))
    if n.get("needs_review"):
        why_check.append("이미지에서 AI가 읽은 내용이라 원문 확인 필요")
    if n["content_kind"] in ("첨부만", "본문없음") and not a["other_conditions"]:
        why_check.append("내용이 첨부파일에 있어요")

    verdict = "NO" if why_no else ("CHECK" if why_check else "MATCH")
    reasons = why_no or why_check or [r for _, r in why_ok] or ["전체 대상"]

    # ---- 점수
    s = 0
    topic_hit = (not p.interests) or n["topic"] in p.interests
    s += 30 if (p.interests and topic_hit) else (10 if not p.interests else -20)
    kinds = {k for k, _ in why_ok}
    if "dept" in kinds:
        s += 30 if a["scope"] == "DEPT" else 20
    elif a["scope"] == "ALL":
        s += 5
    if "grade" in kinds:
        s += 10
    nd = next_deadline(n, now)
    if nd:
        left = (nd - now).total_seconds() / 86400
        s += 25 if left <= 1 else 20 if left <= 3 else 10 if left <= 7 else 0
    ex = n.get("extra") or {}
    if ex.get("region") and p.job_regions and ex["region"] not in p.job_regions:
        s -= 15
    if ex.get("employment_type") and p.job_types and ex["employment_type"] not in p.job_types:
        s -= 10
    if n.get("posted_at") and (now.date() - datetime.fromisoformat(n["posted_at"]).date()) <= timedelta(days=2):
        s += 5
    if n["topic"] in T.DEFAULT_OFF_TOPICS and n["topic"] not in p.interests:
        s = 0
    s = max(0, s) * (1.0 if verdict == "MATCH" else 0.5 if verdict == "CHECK" else 0)
    return {"id": n["id"], "verdict": verdict, "score": round(s), "reasons": reasons[:2], "topic_hit": topic_hit,
            "next_deadline": nd.isoformat(timespec="minutes") if nd else None}


def should_alert(res: dict, p: Profile) -> bool:
    """새 공지를 알림으로 띄울지. 관심 주제이고, 확실히 해당(또는 점수가 매우 높은 '확인 필요')일 때만."""
    if res["verdict"] in ("NO", "EXPIRED") or not res["topic_hit"]:
        return False
    return res["score"] >= 35 if res["verdict"] == "MATCH" else res["score"] >= 25


def reminders(n: dict, now: datetime, days=(7, 3, 1), hour=9):
    """마감 D-7/D-3/D-1 알림 시각. 이미 지난 시각은 뺀다. 마감이 여러 개면 가장 가까운 다음 마감 기준."""
    nd = next_deadline(n, now)
    if not nd:
        return []
    out = []
    for d in days:
        t = (nd - timedelta(days=d)).replace(hour=hour, minute=0)
        if t > now:
            out.append(t.isoformat(timespec="minutes"))
    return out


def build_feed(notices: list[dict], p: Profile, now: datetime) -> dict:
    res = [(judge(n, p, now), n) for n in notices]
    groups = {"MATCH": [], "CHECK": [], "NO": [], "EXPIRED": []}
    for r, n in res:
        groups[r["verdict"]].append((r, n))
    for k in groups:
        groups[k].sort(key=lambda x: (-x[0]["score"], x[0].get("next_deadline") or "9"))
    return groups
