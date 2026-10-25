"""JOB.ssu 진로취업프로그램(카드형 목록) 수집.
- 카드 하나 = 프로그램 하나. 프로그램에 '회차'가 여럿이면 회차마다 신청기간/운영기간/정원이 있다.
- 신청기간·운영기간·정원·신청대상이 목록에 구조화돼 있으므로 마감은 AI 없이 읽는다(deadline_source = program_field).
- 상세 페이지(본문/이미지)는 기존 job_collect.parse_detail 을 그대로 쓴다.
실행: python program_collect.py --pages 2 --detail 5
결과: program_notices.json  /  raw_program_detail_첫번째.html (구조 확인용)"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from urllib.parse import urlencode

from bs4 import BeautifulSoup

import job_collect as J

LIST_NAME = "진로취업프로그램"
PATH = "/service/careerProgram/careerProgramList.do"
DT = re.compile(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?")


def _dt(m):
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    hh, mm = (int(m[4]), int(m[5])) if m[4] else (0, 0)
    return y, mo, d, hh, mm


def parse_period(text: str):
    """'2026.10.07 14:00~2026.11.03 14:00' → (시작ISO, 끝ISO). 끝 시각이 00:00이면 그날 23:59."""
    ms = list(DT.finditer(text or ""))
    if not ms:
        return None, None
    s = _dt(ms[0])
    e = _dt(ms[-1])
    if (e[3], e[4]) == (0, 0):
        e = (*e[:3], 23, 59)
    f = lambda t: f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}"      # noqa: E731
    return f(s), f(e)


def _dl(el):
    """<dl><dt>이름</dt><dd>값</dd></dl> 들을 {이름: 값} 으로"""
    out = {}
    for dl in el.select("dl"):
        dt, dd = dl.find("dt"), dl.find("dd")
        if dt and dd:
            out[dt.get_text(" ", strip=True)] = dd.get_text(" ", strip=True)
    return out


def _int(s):
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


def parse_list(html: str):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for box in soup.select("div.cont_box"):
        li = box.parent
        a = box.select_one("a.detailBtn[data-params]")
        tit = box.select_one("span.tit")
        if not a or not tit:
            continue
        try:
            params = json.loads(a["data-params"])
        except ValueError:
            continue
        params.pop("paginationInfo.currentPageNo", None)
        info = _dl(box.select_one(".info_wrap") or box)
        label = box.select_one(".label_box")
        majors = [x.get_text(strip=True) for x in box.select("ul.major_type li")]
        etc = li.select_one(".etc_cont")
        sessions = []
        for cc in (etc.select(".class_cont") if etc else []):
            d = _dl(cc)
            s, e = parse_period(d.get("신청기간", ""))
            rs, re_ = parse_period(d.get("운영기간", "") or d.get("교육기간", ""))
            t = cc.select_one(".tit")
            sessions.append({"label": re.sub(r"^(신청|종료|마감|대기)\s+", "", re.sub(r"\s+", " ", t.get_text(" ", strip=True))).strip() if t else "",
                             "apply_start": s, "apply_end": e, "run_start": rs, "run_end": re_,
                             "applied": _int(d.get("신청자")), "capacity": _int(d.get("모집정원")), "place": d.get("교육장소")})
        if not sessions:                                    # 회차가 없는 프로그램: 카드 자체가 하나의 회차
            s, e = parse_period(info.get("신청기간", ""))
            rs, re_ = parse_period(info.get("교육기간", "") or info.get("운영기간", ""))
            ed = _dl(etc) if etc else {}
            sessions.append({"label": "", "apply_start": s, "apply_end": e, "run_start": rs, "run_end": re_,
                             "applied": _int(ed.get("신청자")), "capacity": _int(ed.get("모집정원")), "place": ed.get("교육장소")})
        rows.append({
            "list": LIST_NAME, "title": tit.get_text(" ", strip=True), "summary": (box.select_one("p.desc") or tit).get_text(" ", strip=True),
            "team": majors[0] if majors else None, "program_type": majors[1] if len(majors) > 1 else None,
            "status_label": label.get_text(" ", strip=True) if label else "",
            "target": info.get("신청대상"), "status_of_applicant": info.get("신청신분"),
            "competencies": [x.get_text(strip=True) for x in box.select(".cabil .on")],
            "mileage": _int(_dl(etc).get("마일리지")) if etc else None,
            "sessions": sessions, "params": params,
            "detail_url": J.BASE + PATH.replace("List.do", "Info.do"),
        })
    return rows


def parse_program_detail(html: str) -> dict:
    """상세 표(table.t_view)의 항목을 {이름: 값} 으로. '학생 신청대상 상세정보'(학적/구분/학년/학위)도 따로 뽑는다."""
    soup = BeautifulSoup(html, "lxml")
    fields, elig = {}, {}
    tb = soup.select_one("table.t_view")
    for tr in (tb.select("tr") if tb else []):
        th, td = tr.find("th"), tr.find("td")
        if not th or not td:
            continue
        key = th.get_text(" ", strip=True)
        if key == "학생 신청대상 상세정보":
            for dl in td.select("dl"):
                dt, dd = dl.find("dt"), dl.find("dd")
                if dt and dd:
                    elig[dt.get_text(strip=True).rstrip(":")] = re.sub(r"\s+", " ", dd.get_text(" ", strip=True))
        else:
            fields[key] = re.sub(r"\s+", " ", td.get_text(" ", strip=True))
    seq = soup.select_one("#sddpbSeq")
    has_main_img = bool(tb and any(th.get_text(strip=True) == "프로그램 주요내용" and th.find_next("td").find("img") for th in tb.select("th")))
    return {"fields": fields, "eligibility_raw": elig, "seq": seq.get("value") if seq else None,
            "sessions": parse_sessions_detail(html), "main_is_image": has_main_img and not fields.get("프로그램 주요내용")}


def parse_sessions_detail(html: str):
    """상세 페이지의 '분반정보' 표 → 회차 목록 (분반명, 신청기간, 운영기간, 정원, 대기정원, 신청인원, 대기신청인원, 신청 버튼 유무)"""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tb in soup.select("table.t_list"):
        heads = [th.get_text(" ", strip=True) for th in tb.select("thead th")]
        if "분반명" not in heads:
            continue
        for tr in tb.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) != len(heads):
                continue
            d = {h: td.get_text(" ", strip=True) for h, td in zip(heads, tds)}
            s_, e_ = parse_period(d.get("신청기간", ""))
            rs, re_ = parse_period(d.get("운영기간", ""))
            out.append({"label": d.get("분반명", ""), "apply_start": s_, "apply_end": e_, "run_start": rs, "run_end": re_,
                        "capacity": _int(d.get("모집정원")), "waitlist": _int(d.get("대기정원")),
                        "applied": _int(d.get("신청인원")), "waiting": _int(d.get("대기신청인원")),
                        "can_apply": bool(tr.select_one("a.ssupathBtn")), "place": None})
    return out


_STATUS = {"재학": "ENROLLED", "휴학": "LEAVE", "복학": "RETURNING", "졸업": "GRADUATE", "졸업예정": "GRADUATING", "수료": "GRADUATE"}
_LEVEL = {"학사": "UNDERGRAD", "학부": "UNDERGRAD", "석사": "GRAD", "박사": "GRAD", "석박": "GRAD", "대학원": "GRAD"}


def eligibility_of(elig: dict) -> dict:
    """'학적/구분/학년/학위' → 앱 공통 조건. 값이 '전체'이면 제한 없음. 해석하지 못한 값은 other 로 남겨 '확인 필요'가 되게 한다."""
    out = {"grades": [], "statuses": [], "levels": [], "other": [], "parsed": bool(elig)}
    for k, v in (elig or {}).items():
        v = (v or "").strip()
        if not v or v in ("전체", "-", "무관"):
            continue
        if k == "학년":
            gs = sorted({int(g) for g in re.findall(r"([1-6])\s*학년?", v)})
            if gs:
                out["grades"] = gs
                continue
        elif k == "학적":
            st = sorted({c for w, c in _STATUS.items() if w in v})
            if st:
                out["statuses"] = st
                continue
        elif k == "학위":
            lv = sorted({c for w, c in _LEVEL.items() if w in v})
            if lv:
                out["levels"] = lv
                continue
        out["other"].append(f"{k}: {v}")
    return out


def pick_deadline(sessions, now: datetime):
    """대표 마감 = 아직 안 지난 신청 마감 중 가장 이른 것. 모두 지났으면 가장 늦은 것. 회차별 마감은 목록으로도 돌려준다."""
    ends = sorted({s["apply_end"] for s in sessions if s["apply_end"]})
    if not ends:
        return None, []
    up = [e for e in ends if datetime.fromisoformat(e) >= now]
    lst = [{"label": s["label"] or "신청", "datetime": s["apply_end"]} for s in sessions if s["apply_end"]] if len(ends) > 1 else []
    return (up[0] if up else ends[-1]), lst


APPLY = "https://path.ssu.ac.kr/comm/login/user/login.do?rtnUrl=/ptfol/imng/icmpNsbjtPgm/findIcmpNsbjtPgmInfo.do?encSddpbSeq="


def to_notice(row, det, now=None, pdet=None):
    now = now or datetime.now()
    sessions = row["sessions"]
    if pdet and pdet.get("sessions"):                      # 상세의 분반 표가 더 정확하다. 장소는 목록 카드에만 있으므로 이름으로 맞춰 채운다.
        place = {x["label"]: x.get("place") for x in row["sessions"]}
        sessions = [{**x, "place": place.get(x["label"]) or (row["sessions"][0].get("place") if len(row["sessions"]) == 1 else None)} for x in pdet["sessions"]]
    row = {**row, "sessions": sessions}
    deadline, dls = pick_deadline(sessions, now)
    head = [f"{row['title']}", row["summary"]]
    for s in row["sessions"]:
        head.append(f"[{s['label'] or '신청'}] 신청 {s['apply_start'] or '-'} ~ {s['apply_end'] or '-'} / 운영 {s['run_start'] or '-'} ~ {s['run_end'] or '-'}"
                    f" / 정원 {s['capacity'] if s['capacity'] is not None else '-'} / 장소 {s['place'] or '-'}")
    extra_lines = []
    for k in ("프로그램 분류", "운영방식", "프로그램 목표", "선정방법", "지급 마일리지", "핵심역량 비중도"):
        v = (pdet or {}).get("fields", {}).get(k)
        if v:
            extra_lines.append(f"{k}: {v}")
    elig = (pdet or {}).get("eligibility_raw") or {}
    if elig:
        extra_lines.append("신청대상 상세: " + ", ".join(f"{k} {v}" for k, v in elig.items()))
    body = "\n".join(extra_lines)
    if det and len(det["body"]) > 120:               # 상세 본문이 따로 있으면 덧붙인다(제목만 있는 경우는 제외)
        body += "\n" + det["body"]
    return {
        "source": "job.ssu", "list": LIST_NAME, "title": row["title"], "summary": row["summary"], "company": row["team"], "employment_type": row["program_type"],
        "region": None, "job_category": ", ".join(row["competencies"]) or None, "posted": None,
        "deadline": deadline, "deadline_source": "program_field", "deadline_raw": "; ".join(f"{s['apply_start']}~{s['apply_end']}" for s in row["sessions"]),
        "deadlines": dls,
        "url": row["detail_url"] + "?" + urlencode(row["params"]),
        "body": ("\n".join(head) + "\n\n" + body).strip(),
        "fields": {"신청대상": row["target"], "신청신분": row["status_of_applicant"], "상태": row["status_label"], "마일리지": row["mileage"]},
        "sessions": row["sessions"],
        "apply_url": APPLY + row["params"]["encSddpbSeq"] if row["params"].get("encSddpbSeq") else None,
        "eligibility": eligibility_of(pdet["eligibility_raw"]) if pdet else None,
        "program_fields": pdet["fields"] if pdet else {},
        "attachments": det["attachments"] if det else [], "images": det["images"] if det else [],
        "content_kind": "이미지" if (pdet and pdet.get("main_is_image") and det and det["images"]) else "TEXT",
        "program": {k: (pdet or {}).get("fields", {}).get(k) for k in
                    ("프로그램 유형", "운영년도/학기", "프로그램 분류", "프로그램 형식", "운영방식", "신청방법", "선정방법", "정원/대기자", "이수 인증서", "지급 마일리지", "핵심역량 비중도")} if pdet else {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--detail", type=int, default=5, help="상세를 가져올 프로그램 수 (0이면 목록 정보만)")
    a = ap.parse_args()
    rows = []
    for p in range(1, a.pages + 1):
        rows += parse_list(J.get(J.BASE + PATH, {"currentPageNo": p}))
    print(f"=== {LIST_NAME}: 목록 {len(rows)}개")
    out, saved = [], False
    for i, r in enumerate(rows):
        det = pdet = None
        if i < a.detail:
            try:
                html = J.get(r["detail_url"], r["params"])
                if not saved:
                    open("raw_program_detail_first.html", "w", encoding="utf-8").write(html)
                    saved = True
                det = J.parse_detail(html, r["title"])
                pdet = parse_program_detail(html)
            except Exception as e:                      # noqa: BLE001
                print("  상세 실패:", r["title"][:30], e)
        n = to_notice(r, det, pdet=pdet)
        out.append(n)
        print(f"  {n['deadline'] or '-':<17} 회차 {len(r['sessions']):>2} 상태 {r['status_label'] or '-':<4} 본문 {len(n['body']):>5}자 이미지 {len(n['images'])} | {n['title'][:34]}")
    json.dump(out, open("program_notices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: program_notices.json ({len(out)}개)")


if __name__ == "__main__":
    main()
