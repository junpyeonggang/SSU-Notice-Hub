"""STEP 3: 카테고리마다 N개씩 본문까지 받아서 '본문을 제대로 가져왔는지' 자동 점검한다.
실행: python step3_verify_body.py        (카테고리당 2개)
      python step3_verify_body.py 5      (카테고리당 5개)
"""
import json
import sys

from deadline import find_deadlines, missing_kind, parse_deadline
from helpers import categories_from, get_html, list_url, notices_from, parse_detail

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2
NOISE_WORDS = ["Copyright", "개인정보처리방침", "사이트맵", "HOT 공지사항", "이전글", "다음글"]   # 메뉴/푸터/사이드바 글자가 섞였는지 검사용

cats = categories_from(get_html(list_url()))
rows, seen = [], {}
for cat in cats:
    for it in notices_from(get_html(list_url(cat)), cat)[:N]:
        key = (" ".join(it["title"].split()), str(it["date"]))   # 같은 글이 여러 카테고리에 올라온 경우 합침
        if key in seen:
            seen[key]["categories"].append(cat)
            continue
        d = parse_detail(get_html(it["url"]), it["title"], cat)
        body = d["body"]
        dl, st, cands = (None, "NOT_FOUND", [])
        if it["date"]:
            dl, st = parse_deadline(it["title"], it["date"])            # 1순위: 제목
            if not dl:
                dl, st, cands = find_deadlines(body, it["date"])        # 2순위: 본문 (신청/접수 줄만)
        kind = "TEXT" if len(body) >= 100 else ("첨부만" if d["attachments"] else ("이미지" if d["images"] else "본문없음"))
        if st == "NOT_FOUND":
            st = missing_kind(it["title"], kind)            # 마감이 없는 정보 공지인지, 확인이 필요한 건지 구분
        checks = {
            "본문있음": len(body) >= 100,
            "잡음없음": not any(w in body for w in NOISE_WORDS),
        }
        rows.append({**it, "date": str(it["date"]), "body": body, "attachments": d["attachments"], "images": d["images"],
                     "deadline": dl.isoformat(timespec="minutes") if dl else None, "deadline_status": st,
                     "checks": checks, "categories": [cat], "content_kind": kind, "deadline_candidates": cands})
        seen[key] = rows[-1]

print(f"{'카테고리':<8}{'본문글자':>7}  유형   잡음 첨부 마감       상태             제목")
for r in rows:
    c = r["checks"]
    print(f"{r['category']:<8}{len(r['body']):>7}  {r['content_kind']:<5} {'O' if c['잡음없음'] else 'X'}    "
          f"{len(r['attachments']):>2}  {(r['deadline'] or '-')[:10]:<10} {r['deadline_status'][:16]:<16} {r['title'][:24]}")

ok = sum(all(r["checks"].values()) for r in rows)
print(f"\n종합: {len(rows)}개 중 {ok}개 통과 ({ok/len(rows):.0%})" if rows else "수집된 공지 없음")
n = len(rows)
kinds = {k: sum(1 for r in rows if r["content_kind"] == k) for k in ("TEXT", "첨부만", "이미지", "본문없음")}
print(f"본문 유형: 텍스트 {kinds['TEXT']} / 첨부만 {kinds['첨부만']} / 이미지만 {kinds['이미지']} / 본문없음 {kinds['본문없음']}")
print("마감일 찾음:", sum(1 for r in rows if r["deadline"]), "/", n,
      " (제목", sum(1 for r in rows if r["deadline"] and not r["deadline_status"].startswith("BODY")),
      "· 본문", sum(1 for r in rows if r["deadline"] and r["deadline_status"].startswith("BODY")), ")",
      " 후보 여러 개:", sum(1 for r in rows if r["deadline_status"] == "BODY_MULTIPLE"),
      " 상시:", sum(1 for r in rows if r["deadline_status"] == "OPEN_ENDED"))
print("마감 없음(정보 공지):", sum(1 for r in rows if r["deadline_status"] == "INFO_NO_DEADLINE"),
      " / 확인 필요: 본문", sum(1 for r in rows if r["deadline_status"] == "CHECK_BODY"),
      "· 첨부", sum(1 for r in rows if r["deadline_status"] == "CHECK_ATTACHMENT"))
json.dump(rows, open("step3_notices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
print("저장: step3_notices.json  (VS Code로 열어서 본문 2~3개를 브라우저와 비교해 보세요)")
