"""JOB.ssu 2단계: 목록 → 상세를 가져와 공통 모양(job_notices.json)으로 저장한다.
실행:  python job_collect.py            (목록마다 1페이지, 상세 5개씩)
       python job_collect.py --pages 2 --detail 10
상세 주소 규칙(확인됨): 목록의 제목 링크 data-params(JSON) → ...List.do 를 ...Info.do 로 바꾸고 같은 값을 GET으로 보낸다.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from deadline import find_deadlines, parse_deadline

BASE = "https://job.ssu.ac.kr"
UA = {"User-Agent": "SSU-Hyetaek-Student-Project (mobile programming class)"}
LISTS = {
    "기업채용공고": "/service/careerEmpl/opportunityList.do",
    "아르바이트": "/service/careerEmpl/partTimeList.do",
    "공모전/기타": "/service/careerEmpl/etcList.do",
}
DATE = re.compile(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?")


def get(url, params=None):
    time.sleep(1)                                   # 서버 부담을 줄이기 위해 1초 간격
    r = requests.get(url, params=params, headers=UA, timeout=20)
    r.raise_for_status()
    return r.text


def to_iso(text: str, last: bool = True):
    """'2026.10.13~ 2026.10.30' / '2026.10.30 00:00' → 마지막 날짜의 ISO. 시각이 00:00이면 그날 23:59로 본다."""
    ms = list(DATE.finditer(text or ""))
    if not ms:
        return None
    m = ms[-1] if last else ms[0]
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    hh, mm = (int(m[4]), int(m[5])) if m[4] else (23, 59)
    if (hh, mm) == (0, 0):
        hh, mm = 23, 59
    return f"{y:04d}-{mo:02d}-{d:02d}T{hh:02d}:{mm:02d}"


def parse_list(html: str, list_name: str, list_path: str):
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.t_list") or soup.find("table")
    if not table:
        return []
    heads = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        a = tr.select_one("a.detailBtn")
        if not a or not tds:
            continue
        cells = {heads[i] if i < len(heads) else f"c{i}": td.get_text(" ", strip=True) for i, td in enumerate(tds)}
        try:
            params = json.loads(a.get("data-params", "{}"))
        except ValueError:
            params = {}
        params.pop("paginationInfo.currentPageNo", None)
        rows.append({"list": list_name, "title": a.get_text(" ", strip=True), "cells": cells, "params": params,
                     "detail_url": BASE + list_path.replace("List.do", "Info.do"), "is_pinned": "공지" in tds[0].get_text()})
    return rows


from bs4 import NavigableString

_BLOCKS = ("p", "li", "tr", "div", "ol", "ul", "h1", "h2", "h3", "h4", "table", "section")


def block_text(node) -> str:
    """<strong>처럼 글자 단위로 쪼개진 태그는 붙이고, 문단/줄/표 행은 줄바꿈으로 나눈다."""
    for br in node.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for t in node.find_all(_BLOCKS):
        t.append(NavigableString("\n"))
    for t in node.find_all(["td", "th"]):
        t.append(NavigableString(" | "))
    text = node.get_text("").replace("\xa0", " ").replace("\u200b", "")
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip(" |").strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines)


_JUNK_LINES = {"공모전/기타", "채용정보", "아르바이트", "기업채용공고", "고용24", "공지사항 조회 테이블 입니다.", "목록", "첨부파일"}
_PERIOD = re.compile(r"^(20\d{2}\.\d{1,2}\.\d{1,2})\s*~\s*(20\d{2}\.\d{1,2}\.\d{1,2})$")


def _clean_lines(text: str):
    out = []
    for ln in text.splitlines():
        ln = ln.replace("\u200b", "").strip()
        if ln:
            out.append(ln)
    return out


def parse_detail(html: str, title: str = ""):
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(".contents-wrap") or soup.body or soup
    for t in root(["script", "style", "nav", "form", "noscript"]):
        t.decompose()
    for sel in (".sub_title_wrap", ".guide_wrap", ".page-nav", ".btn_wrap", ".breadcrumb"):
        for t in root.select(sel):
            t.decompose()
    files, seen_names = [], set()
    for a in root.select("a[href]"):
        if re.search(r"download|fileDown|cmnFile", a["href"], re.I):
            name = a.get_text(" ", strip=True)
            if name and name not in seen_names:                 # 같은 파일이 주소 2개로 걸려 있어 이름으로 합친다
                seen_names.add(name)
                files.append({"name": name, "url": BASE + a["href"] if a["href"].startswith("/") else a["href"]})
    for a in root.select("a[href]"):                            # 파일 링크와 '목록' 버튼은 본문에서 뺀다
        if a.get_text(" ", strip=True) in seen_names or "listBtn" in (a.get("class") or []):
            a.decompose()
    imgs = []
    for i in root.select("img[src]"):
        src = i["src"]
        if any(w in src.lower() for w in ("thumbnail", "icon", "gstatic", "blank", "/common/images/")):
            continue
        u = BASE + src if src.startswith("/") else src
        if u not in imgs:
            imgs.append(u)
    fields, content = {}, None
    rec = root.select_one(".rec_cont")                          # 기업채용공고의 '공고내용' 영역
    if rec is not None:
        content = block_text(rec)
        rec.decompose()
    seq = root.select_one("#sjrSeq")
    if seq is not None and seq.get("value"):
        fields["path_seq"] = seq["value"]                       # SSU-PATH '지원하기' 링크에 쓰이는 번호(3번 사이트와 연결 고리)
    tables = root.select("table.t_view") or [t for t in root.select("table") if not t.find_parent("table")]
    for table in tables:
        head = [th.get_text(" ", strip=True) for th in table.select("thead th")]
        if head:                                                # 공모전/기타: 머리글 줄(thead) 아래 값 줄(tbody)이 따로 있는 표
            first = table.select_one("tbody tr")
            cells = [td.get_text(" ", strip=True) for td in first.find_all("td")] if first else []
            for h, v in zip(head, cells):
                fields.setdefault(h, v)
            for v in cells:
                if _PERIOD.match(v):
                    fields.setdefault("게시기간", v)
                elif re.match(r"^20\d{2}\.\d{2}\.\d{2}(\s+\d{2}:\d{2})?$", v):
                    fields.setdefault("등록일", v)
            for h, v in zip(head, cells):
                if any(w in h for w in ("작성", "등록자", "담당")) and v:
                    fields.setdefault("작성자", v)
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue
            for th, td in zip(tr.find_all("th", recursive=False), tr.find_all("td", recursive=False)):
                k = th.get_text(" ", strip=True)
                if k and k not in fields:
                    fields[k] = block_text(td) if k == "내용" else td.get_text(" ", strip=True)
        if table.find("th"):
            table.decompose()                                   # 정보 표는 이미 읽었으니 본문 계산에서 뺀다
    lines = _clean_lines(block_text(root))
    if "목록" in lines:
        lines = lines[:len(lines) - 1 - lines[::-1].index("목록")]
    if title:                                                   # 공모전/기타: 제목 줄 아래에 '게시기간 / 작성자 / 등록일시'가 온다
        t = title.replace(" ", "")
        idx = next((i for i, ln in enumerate(lines) if ln.replace(" ", "") == t), None)
        if idx is not None:
            head, lines = lines[:idx], lines[idx + 1:]
            for _ in range(3):                                  # 게시기간 → 작성자 → 등록일시 (최대 3줄만 떼어낸다)
                if not lines:
                    break
                m = _PERIOD.match(lines[0])
                if m:
                    fields.setdefault("게시기간", f"{m[1]} ~ {m[2]}")
                elif re.match(r"^20\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}$", lines[0]):
                    fields.setdefault("등록일", lines[0])
                elif "작성자" not in fields and len(lines[0]) <= 12 and not re.search(r"[:■]", lines[0]):
                    fields["작성자"] = lines[0]
                else:
                    break
                lines = lines[1:]
    lines = [ln for ln in lines if ln not in _JUNK_LINES and ln not in seen_names]
    rest = "\n".join(lines)
    body = content or fields.get("내용") or rest
    return {"fields": fields, "body": body, "attachments": files, "images": imgs}


def best_deadline(title, posted_iso, body, fields, row_cells, list_name):
    """마감일 하나를 정한다. (iso, 출처)
    - 기업채용공고/아르바이트: '모집기간' 칸의 끝 날짜(사이트가 칸으로 주는 값)
    - 공모전/기타: 게시기간은 '게시 기간'일 뿐이라(LG CNS: 게시 10.21, 실제 10.12) 제목 → 본문 규칙을 먼저, 없으면 게시기간"""
    from datetime import date

    field_text = fields.get("모집기간") or row_cells.get("마감일시") or row_cells.get("기간") or ""
    board_text = fields.get("게시기간") or ""
    if list_name != "공모전/기타":
        return to_iso(field_text), "field"
    pub = date.fromisoformat(posted_iso[:10]) if posted_iso else date.today()
    dl, st = parse_deadline(title, pub)
    if dl:
        return dl.isoformat(timespec="minutes"), "title"
    dl, st, _ = find_deadlines(body, pub)
    if dl:
        return dl.isoformat(timespec="minutes"), "body"
    return to_iso(board_text), ("board_period" if board_text else None)


def to_notice(row, det):
    c, f = row["cells"], det["fields"]
    posted = to_iso(f.get("등록일") or c.get("등록일시") or c.get("등록일") or "", last=False)
    deadline, src = best_deadline(row["title"], posted, det["body"], f, c, row["list"])
    return {
        "source": "job.ssu", "list": row["list"], "title": row["title"],
        "company": c.get("회사명") or f.get("회사명") or f.get("기관명") or f.get("작성자"),
        "employment_type": c.get("채용구분") or f.get("채용구분"),
        "region": c.get("지역") or f.get("근무지역"),
        "job_category": f.get("직종/직무"),
        "posted": posted, "deadline": deadline, "deadline_source": src,
        "deadline_raw": f.get("모집기간") or f.get("게시기간") or "",
        "url": row["detail_url"] + "?" + urlencode(row["params"]),
        "body": det["body"], "fields": f, "attachments": det["attachments"], "images": det["images"],
        "content_kind": "TEXT" if len(det["body"]) >= 100 else ("이미지" if det["images"] else ("첨부만" if det["attachments"] else "본문없음")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--detail", type=int, default=5, help="목록마다 상세를 가져올 개수")
    a = ap.parse_args()
    out = []
    for name, path in LISTS.items():
        rows = []
        for p in range(1, a.pages + 1):
            rows += parse_list(get(BASE + path, {"currentPageNo": p}), name, path)
        print(f"\n=== {name}: 목록 {len(rows)}개 (공지 고정글 {sum(r['is_pinned'] for r in rows)}개)")
        for r in rows[:a.detail]:
            try:
                html = get(r["detail_url"], r["params"])
            except Exception as e:                      # noqa: BLE001
                print("  상세 실패:", r["title"][:30], e)
                continue
            if not any(x["list"] == name for x in out):          # 목록마다 첫 상세 HTML을 저장해 구조를 확인할 수 있게 한다
                open(f"raw_job_detail_{path.rsplit('/', 1)[-1].replace('List.do', '')}.html", "w", encoding="utf-8").write(html)
            n = to_notice(r, parse_detail(html, r["title"]))
            out.append(n)
            print(f"  {n['deadline'] or '-':<17} {n['deadline_source'] or '-':<12} {n['content_kind']:<4} 본문 {len(n['body']):>5}자 첨부 {len(n['attachments'])} 이미지 {len(n['images'])} | {n['title'][:34]}")
    json.dump(out, open("job_notices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n저장: job_notices.json ({len(out)}개) / raw_job_detail_*.html 3개")


if __name__ == "__main__":
    main()
