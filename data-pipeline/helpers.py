"""모든 단계가 같이 쓰는 도구 모음. (요청 보내기 / 목록 읽기 / 본문 읽기)"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString

BASE = "https://scatch.ssu.ac.kr"
LIST_URL = BASE + "/공지사항/"
UA = "SSU-Hyetaek-Student-Project (mobile programming class)"
RAW = Path("raw")
_last = 0.0
DATE_RE = re.compile(r"(20\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")
ATTACH_EXT = (".pdf", ".hwp", ".hwpx", ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx", ".zip", ".jpg", ".png")


# ---------- 1. 요청 ----------
def get_html(url: str, name: str | None = None) -> str:
    """HTML을 받아온다. 사이트 부담을 줄이려고 요청 사이에 1초 쉬고, 받은 원본은 raw/에 저장한다."""
    global _last
    wait = 1.0 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    _last = time.time()
    r.raise_for_status()
    RAW.mkdir(exist_ok=True)
    if name:
        (RAW / name).write_text(r.text, encoding="utf-8")
    return r.text


def list_url(category: str | None = None) -> str:
    return LIST_URL + ("?category=" + quote(category) if category else "")


# ---------- 2. 목록 읽기 ----------
def categories_from(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select("a[href*='category=']"):
        for v in parse_qs(urlparse(a["href"]).query).get("category", []):
            v = unquote(v).strip()
            if v and v not in out:
                out.append(v)
    return out


def _date_near(node, up: int = 4):
    """링크 주변에서 게시 날짜를 찾는다. 단, 링크 글자(제목) 안의 날짜는 제외한다.
    (제목에 '~2026.12.25.' 같은 마감일이 있어도 게시일로 오인하지 않기 위해)"""
    own = node.get_text(" ", strip=True)
    cur = node
    for _ in range(up):
        cur = cur.parent
        if cur is None:
            return None
        text = cur.get_text(" ", strip=True).replace(own, " ")
        m = DATE_RE.search(text)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
    return None


def notices_from(html: str, category: str) -> list[dict]:
    """목록 페이지 → [{title, url, slug, date}]"""
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.select("a[href*='slug=']"):
        href = urljoin(BASE, a["href"])
        slug = unquote(parse_qs(urlparse(href).query)["slug"][0])
        title = a.get_text(" ", strip=True)
        if not title or slug in seen:
            continue
        seen.add(slug)
        if title.startswith(category + " "):      # 링크 글자 앞에 카테고리명이 붙어 있어서 제거
            title = title[len(category):].strip()
        out.append({"title": title, "url": href, "slug": slug, "date": _date_near(a), "category": category})
    return out


# ---------- 3. 본문 읽기 ----------
_NOISE = re.compile(r"sidebar|menu|nav|footer|header|comment|related|breadcrumb|share|widget|prev|next", re.I)
_BLOCKS = ["p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table"]


def block_text(el) -> str:
    """문단 태그에서만 줄을 바꾸고 span 같은 건 이어 붙인다."""
    for b in el.find_all(_BLOCKS):
        b.append(NavigableString("\n"))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in el.get_text("").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _drop_hot_sidebar(soup):
    """'HOT 공지사항'으로 시작하는 사이드바 목록을 통째로 지운다.
    (본문이 짧거나 이미지/첨부뿐인 글에서 이 목록이 '글자가 가장 많은 블록'으로 오인되기 때문)"""
    def hot(el):
        t = el.get_text(" ", strip=True)
        return t.startswith("HOT 공지사항") and len(t) < 1500
    targets = [el for el in soup.find_all(True) if hot(el)]
    ids = {id(el) for el in targets}
    for el in targets:
        if id(el.parent) not in ids:            # 가장 바깥(최대) 블록만 지운다
            el.decompose()


def dominant_block(soup):
    """메뉴/푸터를 지운 뒤, 글자가 가장 많이 몰린 안쪽 블록(=본문)을 찾는다."""
    _drop_hot_sidebar(soup)
    for t in soup.find_all("aside"):
        t.decompose()
    for t in soup.find_all(True):
        if t.attrs is None:
            continue
        ident = " ".join(t.get("class", [])) + " " + (t.get("id") or "")
        if _NOISE.search(ident) and t.name not in ("html", "body"):
            t.decompose()
    cur = soup.body or soup
    while True:
        total = len(cur.get_text("", strip=True))
        nxt = next((c for c in cur.find_all(["div", "section", "article", "main", "td", "p"], recursive=False)
                    if total and len(c.get_text("", strip=True)) >= 0.6 * total), None)
        if nxt is None:
            return cur
        cur = nxt


def strip_header(body: str, title: str, category: str) -> str:
    """본문 맨 앞의 카테고리명/제목/날짜/조회수 줄을 제거 (앞 6줄 안에서만)."""
    t = title.replace(" ", "")
    lines, i = body.splitlines(), 0
    while i < min(len(lines), 6):
        ln = lines[i].strip()
        c = ln.replace(" ", "")
        is_date = re.fullmatch(r"20\d{2}[.\-/년]\d{1,2}[.\-/월]\d{1,2}일?\.?", c)
        if ln == category or ln.isdigit() or is_date or (len(c) > 5 and (c in t or (t in c and len(c) <= len(t) + 6))):
            i += 1
        else:
            break
    return "\n".join(lines[i:])


def cut_tail(body: str) -> str:
    """본문 뒤에 붙는 '목록 / 이전글·다음글 / HOT 공지사항' 구간을 잘라낸다."""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("HOT 공지"):                      # 어느 위치에 있어도 잘라낸다
            return "\n".join(lines[:i])
        if i >= 1 and (ln.strip() == "목록" or ln.startswith(("이전글", "다음글"))):
            return "\n".join(lines[:i])
    return body


_FILE_LINE = re.compile(r"\.(pdf|hwp|hwpx|xlsx?|docx?|pptx?|zip|jpe?g|png)$", re.I)


def drop_filename_lines(body: str) -> str:
    """본문에 섞인 첨부파일 이름 줄(예: '붙임1-공고문.pdf')을 제거한다. 첨부는 attachments에 따로 있다."""
    keep = [ln for ln in body.splitlines() if not (_FILE_LINE.search(ln.strip()) and " " not in ln.strip())]
    return "\n".join(keep)


def parse_detail(html: str, title: str, category: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "form"]):
        t.decompose()
    attachments = []
    for a in soup.select("a[href]"):
        h = a["href"]
        if "download.php" in h or h.lower().split("?")[0].endswith(ATTACH_EXT):
            attachments.append({"name": a.get_text(" ", strip=True) or h.rsplit("/", 1)[-1], "url": urljoin(BASE, h)})
    block = dominant_block(soup)
    images, seen = [], set()
    for im in block.find_all("img"):
        src = im.get("data-src") or im.get("src") or ""
        w = im.get("width") or ""
        if not src or src.startswith("data:") or (w.isdigit() and int(w) < 80):
            continue
        if any(k in src.lower() for k in ("icon", "logo", "emoji", "btn_", "blank")):
            continue
        u = urljoin(BASE, src)
        if u not in seen:
            seen.add(u)
            images.append(u)
    body = drop_filename_lines(cut_tail(strip_header(block_text(block), title, category)))
    return {"body": body, "attachments": attachments, "images": images}
