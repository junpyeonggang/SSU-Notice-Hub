import re
from datetime import date, datetime, timedelta

_TIME = r"(?:(?P<gap>[^\d~]{0,8}?)(?P<h>\d{1,2})(?::(?P<mi>\d{2})|\s*시))?"   # 선택적 시각(18시 / 16:00 / 오후 3시)

# (1) '~' 뒤의 날짜:  ~10.8.목 17시 / ~2026.12.25.
_RANGE_END = re.compile(
    r"~\s*(?:(?P<y>20\d{2})\s*[./]\s*)?(?P<m>\d{1,2})\s*[./]\s*(?P<d>\d{1,2})" + _TIME
)
# (2) '~' 없이 '까지'로 끝나는 날짜:  2026. 11. 11. (수) 23:59 까지 / 10월 7일까지
_UNTIL = re.compile(
    r"(?:(?P<y>20\d{2})\s*[./년]\s*)?(?P<m>\d{1,2})\s*[./월]\s*(?P<d>\d{1,2})\s*일?\.?" + _TIME + r"[^\d~]{0,8}?까지"
)

# 본문 줄에서 '신청 마감'을 찾을 때: 이 단어가 있어야 하고 / 이 단어가 있으면 제외한다
# '기한/마감' 줄에 '~'나 '까지' 없이 날짜만 적힌 경우:  본교 지원기한: 2026. 10. 26. (월) 23:59
_SINGLE = re.compile(r"(?P<y>20\d{2})\s*[./]\s*(?P<m>\d{1,2})\s*[./]\s*(?P<d>\d{1,2})" + _TIME)
_TILDES = str.maketrans({"∼": "~", "～": "~", "〜": "~"})      # 모양이 다른 물결 문자를 '~'로 통일

_POS = ("지원", "신청", "접수", "제출", "응모", "모집", "마감", "기한", "등록")
_NEG = ("봉사시간", "봉사 시간", "운영 기간", "운영기간", "활동 기간", "활동기간", "임용 기간", "임용기간", "계약 기간", "계약기간",
        "근무 기간", "근무기간", "교육 기간", "교육기간", "파견 기간", "면접", "합격자", "발표")
_OPEN = ("채용 완료 시", "채용완료시", "선착순", "소진 시", "상시")


def _to_dt(g, published: date):
    m, d = int(g["m"]), int(g["d"])
    h = int(g["h"]) if g["h"] else 23
    if g["h"] and "오후" in (g["gap"] or "") and h < 12:
        h += 12
    mi = int(g["mi"]) if g["mi"] else (0 if g["h"] else 59)
    if not (1 <= m <= 12 and 1 <= d <= 31 and 0 <= h <= 23):
        return None
    try:
        dt = datetime(int(g["y"]) if g["y"] else published.year, m, d, h, mi)
    except ValueError:
        return None
    if not g["y"] and dt.date() < published - timedelta(days=30):   # 연말→연초 공지
        dt = dt.replace(year=dt.year + 1)
    return dt


_ACTION = ("신청", "접수", "모집", "지원", "제출", "선발", "응모", "참가", "참여", "등록", "추천")


def missing_kind(title: str, content_kind: str) -> str:
    """마감일을 못 찾았을 때 이유를 나눈다.
    - INFO_NO_DEADLINE : 제목에 신청/모집 같은 행동 단어가 없는 정보 공지 → 마감이 없는 게 정상
    - CHECK_ATTACHMENT : 신청 공지인데 내용이 첨부파일에 있음 → '첨부 확인 필요'
    - CHECK_BODY       : 신청 공지인데 본문에서 못 찾음 → AI 확인 대상"""
    if content_kind == "첨부만":                      # 내용이 첨부파일에만 있으면 정보 공지인지 알 수 없다
        return "CHECK_ATTACHMENT"
    if content_kind == "이미지":                      # 포스터/이미지에 내용이 있음 → 이미지 읽기(AI) 대상
        return "CHECK_IMAGE"
    if not any(a in title for a in _ACTION):
        return "INFO_NO_DEADLINE"
    return "CHECK_BODY"


def parse_deadline(title: str, published: date):
    """제목에서 마감 일시를 뽑는다. 없으면 (None, 'NOT_FOUND')."""
    hits = list(_RANGE_END.finditer(title))
    if not hits:
        return None, "NOT_FOUND"
    g = hits[-1]                       # 제목에 여러 개면 마지막 것
    dt = _to_dt(g, published)
    if dt is None:
        return None, "INVALID"
    return dt, "FOUND" if g["h"] else "FOUND_DATE_ONLY"


def find_deadlines(body: str, published: date, max_lines: int = 400):
    """
    본문 전체에서 '신청 마감'을 찾는다. (dt, status, 후보목록) 반환.
    - 신청/접수/제출/마감 같은 단어가 있는 줄만 보고, 운영기간/임용기간/면접 같은 줄은 제외한다.
    - 후보가 여러 개면 게시일 이후 중 가장 이른 날짜를 쓰고 BODY_MULTIPLE로 표시한다 (사람/AI가 최종 확인).
    - '채용 완료 시까지' 같은 상시 모집이면 OPEN_ENDED.
    """
    cands, open_ended = {}, False
    lines = [ln.translate(_TILDES) for ln in body.splitlines()[:max_lines]]
    for i, ln in enumerate(lines):
        if not any(k in ln for k in _POS) or any(n in ln for n in _NEG):
            continue
        if any(o in ln for o in _OPEN):
            open_ended = True
        text = ln
        if (not re.search(r"\d{1,2}\s*[./월]\s*\d{1,2}", ln) and i + 1 < len(lines)
                and any(h in ln for h in ("기간", "일정", "기한", "마감"))):
            text = ln + " " + lines[i + 1]          # '5. 접수기간 및 방법' 다음 줄에 날짜가 있는 경우
        pats = [_RANGE_END, _UNTIL] + ([_SINGLE] if ("기한" in text or "마감" in text) else [])
        for pat in pats:
            for g in pat.finditer(text):
                dt = _to_dt(g, published)
                if dt and dt.date() >= published:
                    cands.setdefault(dt, (bool(g["h"]), ln.strip()[:80]))
    if not cands:
        return None, ("OPEN_ENDED" if open_ended else "NOT_FOUND"), []
    timed_days = {dt.date() for dt, (t, _) in cands.items() if t}
    ordered = sorted(dt for dt, (t, _) in cands.items() if t or dt.date() not in timed_days)
    has_time = cands[ordered[0]][0]
    status = "BODY_MULTIPLE" if len(ordered) > 1 else ("BODY_FOUND" if has_time else "BODY_FOUND_DATE_ONLY")
    return ordered[0], status, [d.isoformat(timespec="minutes") for d in ordered]


if __name__ == "__main__":
    cases = [
     ("2026년도 하반기 (재)춘천인재육성장학재단 봄내장학생 선발 안내(9.28.월~10.7수 18시)", date(2026,9,18), "2026-10-07 18:00"),
     ("2026 대한산업보건협회 산재 노동자 자녀 성장지원사업 안내(~10.31.토)", date(2026,9,18), "2026-10-31 23:59"),
     ("서초구_2026년 하반기 문주장학재단 주관 AI · ICT 인재 장학생 모집 안내(9.21.월~10.8.목)", date(2026,9,17), "2026-10-08 23:59"),
     ("★ 2026학년도 2학기 하나금융나눔재단 하나장학생 추천자 선발 공고(~9.23수 15시)", date(2026,9,16), "2026-09-23 15:00"),
     ("2026년도 (재)포항시장학회 장학생 선발 안내(~9.22.화 18시)", date(2026,9,16), "2026-09-22 18:00"),
     ("2026년 (재)고속도로장학재단 고속도로 장학생 선발 안내(~10.11.일)", date(2026,9,15), "2026-10-11 23:59"),
     ("제36기 미래에셋 해외교환 장학생 선발 안내(2027년 봄학기 파견 대비) (9.30~10.6.화 15시)", date(2026,9,2), "2026-10-06 15:00"),
     ("2026년도 재단법인 수림재단 동교인재상 선발 안내(~10.16.금)", date(2026,9,2), "2026-10-16 23:59"),
     ("2026학년도 해외선교봉사 (IMPACT 41기) 모집 (지원: ~10.28.(수) 16:00)", date(2026,9,23), "2026-10-28 16:00"),
     ("2026년 하반기 (재)대전청년내일재단 인재육성(성취) 장학생 선발 안내(~9.23.수 17시)", date(2026,9,9), "2026-09-23 17:00"),
     ("2026년도 하반기 (재)인천인재평생교육진흥원 장학생 선발 안내(9.10.목~10.8.목)", date(2026,9,7), "2026-10-08 23:59"),
     ("[숭실대학교 앵커사업단] 2026년 숭실 특허 경진대회 개최(~10/18일까지 마감)", date(2026,9,21), "2026-10-18 23:59"),
     ("2026학년도 2학기 고졸 후학습자 장학사업(희망사다리 Ⅱ유형) 신규장학생 신청기간 연장 안내", date(2026,9,17), None),
     ("★2026학년도 2학기 국가장학금Ⅰ유형 사후지급 일정 안내", date(2026,9,7), None),
     ("2026-2학기 3~4학년 대상 특강 안내", date(2026,9,7), None),
     ("2026년 겨울 인턴 모집(~1.5.월)", date(2026,12,20), "2027-01-05 23:59"),
    ]
    ok = 0
    for t, pub, want in cases:
        dt, st = parse_deadline(t, pub)
        got = dt.strftime("%Y-%m-%d %H:%M") if dt else None
        flag = "OK  " if got == want else "FAIL"
        ok += got == want
        print(f"{flag} {st:16} got={got}  want={want}  | {t[:40]}")
    print(f"\n{ok}/{len(cases)} passed")
