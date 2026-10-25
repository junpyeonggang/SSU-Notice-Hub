"""4단계: AI로 '규칙이 못 하는 것'만 처리한다. (마감 확정 / 신청 조건 / 한 줄 요약)

사용법 (PowerShell)
  python step4_extract.py --list-models          # 내 키로 쓸 수 있는 모델 이름 확인
  python step4_extract.py --dry-run              # AI 호출 없이 대상과 프롬프트만 확인
  python step4_extract.py --limit 3              # 3개만 먼저 시험
  python step4_extract.py                        # AI가 필요한 공지 전부 (기본 12개 안팎)
  python step4_extract.py --all                  # 텍스트 공지 전부 (요약/조건까지)
  python step4_extract.py --images               # 이미지만 있는 공지도 읽기

키: 환경변수 GEMINI_API_KEY (코드/JSON에 절대 넣지 않는다)
모델: --model 또는 환경변수 GEMINI_MODEL (모델 이름은 --list-models 결과에서 고른다)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"
NEED_AI = {"CHECK_BODY", "BODY_MULTIPLE"}
PROMPT_VERSION = "v2"      # 안내문을 바꾸면 올린다 → 이전 버전으로 처리한 공지는 다음 실행 때 자동으로 다시 처리

PROMPT = """너는 대학 공지에서 정보를 뽑는 도구다. 아래 공지 '본문'에 적힌 내용만 사용한다. 추측 금지.
JSON 하나만 출력한다. 모르면 null. 키는 정확히 다음과 같다.

{{
 "deadline": "신청/접수/지원/제출 마감 일시 'YYYY-MM-DD HH:MM' (시간 모르면 23:59). 없거나 불확실하면 null",
 "deadline_evidence": "마감 근거가 되는 본문 문장을 그대로 복사 (null이면 null)",
 "deadlines": [ {{"label": "프로그램/구분 이름", "datetime": "YYYY-MM-DD HH:MM", "evidence": "본문 문장 그대로"}} ],
 "events": [ {{"label": "행사/훈련/설명회/시험 이름", "datetime": "YYYY-MM-DD HH:MM", "evidence": "본문 문장 그대로"}} ],
 "gender": "MALE_ONLY 또는 FEMALE_ONLY 또는 null",
 "gender_evidence": "성별 제한의 근거 문장을 그대로 복사 (null이면 null)",
 "summary": "공지를 60자 이내 한 문장으로 요약",
 "conditions": [
   {{"type": "grade|department|status|nationality|gpa|other",
     "value": "예: 3학년 / 컴퓨터학부 / 재학생 / 외국인 / 평점 3.0 이상",
     "evidence": "근거가 되는 본문 문장을 그대로 복사"}}
 ]
}}

규칙
- 여러 일정이 있으면 '신청 마감'만 deadline에 넣는다. 면접/발표/운영/임용 기간은 아니다.
- 프로그램/구분별로 마감이 여러 개이면(표 등) deadline은 null로 두고 deadlines에 모두 넣는다. 마감이 하나면 deadlines는 [].
- 마감이 '조기/일반'처럼 둘이면 일반(최종) 마감을 deadline에, 둘 다 deadlines에 넣는다.
- events는 '열리는 날'이다(훈련, 설명회, 시험, 행사 일시). 신청 마감이 아니다. 없으면 [].
- gender는 본문이 남학생만/여학생만 대상이라고 분명히 쓴 경우만 쓴다(예: 예비군 훈련 = MALE_ONLY). 모르면 null.
- 재학 상태 조건은 value에 '재학생', '휴학생', '졸업예정자', '졸업생' 중 해당하는 말을 그대로 쓴다. 본문이 '휴학·졸업·수료자는 제외'처럼 제외 대상을 적었으면, 그 말들은 쓰지 말고 남는 '재학생'을 value로 쓴다.
- conditions는 '지원 자격 제한'만이다: 학년/학과/재학상태/국적/성적/나이 등. 아래는 조건이 아니다.
  · "외국인의 경우 여권 제출" 같은 해당자만 내는 제출서류 · "숭실대 학생분들 참여 바랍니다" 같은 인사말 · 프로그램 소개 문장
- 조건이 없으면 [].
- evidence는 본문에 있는 문장을 한 글자도 바꾸지 말고 복사한다.

[제목] {title}
[게시일] {date}
[본문]
{body}
"""

IMG_PROMPT = PROMPT.replace("아래 공지 '본문'에 적힌 내용만 사용한다.", "첨부된 공지 이미지와 '본문'에 적힌 내용만 사용한다.")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


COND_TYPES = {"grade", "department", "status", "nationality", "gpa", "age", "other"}
_GREETING = {"숭실대학교", "숭실대", "숭실대학교학생", "숭실대학교학생분들", "숭실대학생", "본교학생", "본교"}


def validate(res: dict, body: str, from_image: bool = False) -> dict:
    """AI 답을 믿기 전에 검사한다. 근거 문장이 본문에 없으면 그 값은 버린다. (이미지는 검증 불가 → 확인 표시)"""
    out = {"deadline": None, "deadline_evidence": None, "deadlines": [], "events": [], "gender": None, "summary": None, "conditions": [], "dropped": [],
           "needs_review": bool(from_image)}
    nb = norm(body)

    def ok(ev):
        return from_image or (bool(ev) and norm(ev) in nb)

    dl = res.get("deadline")
    if dl:
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}( \d{2}:\d{2})?", str(dl).strip()) and ok(res.get("deadline_evidence")):
            out["deadline"] = str(dl).strip()
            out["deadline_evidence"] = res.get("deadline_evidence")
        else:
            out["dropped"].append(f"deadline:{dl}")
    for d in res.get("deadlines") or []:
        if (isinstance(d, dict) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}( \d{2}:\d{2})?", str(d.get("datetime", "")).strip())
                and ok(d.get("evidence"))):
            out["deadlines"].append({"label": d.get("label"), "datetime": str(d["datetime"]).strip(), "evidence": d.get("evidence")})
        else:
            out["dropped"].append(f"deadlines:{(d or {}).get('datetime') if isinstance(d, dict) else d}")
    for d in res.get("events") or []:
        if (isinstance(d, dict) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}( \d{2}:\d{2})?", str(d.get("datetime", "")).strip())
                and ok(d.get("evidence"))):
            out["events"].append({"label": d.get("label"), "datetime": str(d["datetime"]).strip(), "evidence": d.get("evidence")})
        else:
            out["dropped"].append(f"events:{(d or {}).get('datetime') if isinstance(d, dict) else d}")
    if res.get("gender") in ("MALE_ONLY", "FEMALE_ONLY"):
        if ok(res.get("gender_evidence")):
            out["gender"] = res["gender"]
        else:
            out["dropped"].append(f"gender:{res['gender']}")
    s = res.get("summary")
    if isinstance(s, str) and s.strip():
        out["summary"] = s.strip()[:80]
    for c in res.get("conditions") or []:
        if isinstance(c, dict) and c.get("value") and norm(str(c["value"])) not in _GREETING and ok(c.get("evidence")):
            t = c.get("type") if c.get("type") in COND_TYPES else "other"
            out["conditions"].append({"type": t, "value": c["value"], "evidence": c.get("evidence")})
        else:
            out["dropped"].append(f"condition:{(c or {}).get('value') if isinstance(c, dict) else c}")
    return out


def call_gemini(key: str, model: str, prompt: str, images: list[tuple[str, bytes]] | None = None, tries: int = 4) -> dict:
    parts = [{"text": prompt}]
    for mime, data in images or []:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    payload = {"contents": [{"parts": parts}],
               "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    url = f"{API}/models/{model}:generateContent"
    for i in range(tries):
        r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                          json=payload, timeout=90)
        if r.status_code in (429, 500, 503):
            wait = 15 * (i + 1)
            print(f"   (한도/일시 오류 {r.status_code}, {wait}초 후 재시도)")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    raise RuntimeError("재시도 실패 (무료 한도일 수 있음: 잠시 뒤 다시 실행하면 이어서 합니다)")


def fetch_images(urls: list[str], limit: int = 4) -> list[tuple[str, bytes]]:
    out = []
    for u in urls[:limit]:
        r = requests.get(u, timeout=30, headers={"User-Agent": "SSU-Hyetaek-Student-Project (mobile programming class)"})
        mime = r.headers.get("Content-Type", "").split(";")[0]
        if r.status_code == 200 and mime.startswith("image/") and len(r.content) < 7_000_000:
            out.append((mime, r.content))
        time.sleep(1)
    return out


def pick_targets(rows: list[dict], all_text: bool, images: bool) -> list[dict]:
    t = []
    for r in rows:
        if r.get("deadline_source") == "program_field" and (r.get("eligibility") or {}).get("parsed") and r["content_kind"] != "이미지":
            continue                                   # 진로취업프로그램: 마감·대상이 사이트에 구조화돼 있어 AI 불필요
        if r["content_kind"] == "TEXT" and (all_text or r.get("deadline_status") in NEED_AI):
            t.append(r)
        elif images and r["content_kind"] == "이미지":
            t.append(r)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", ""))
    ap.add_argument("--delay", type=float, default=7.0, help="호출 사이 대기(초). 무료 한도 보호")
    ap.add_argument("--src", nargs="+", default=["archive_step3_notices.json", "archive_job_notices.json", "archive_program_notices.json",
                                                   "step3_notices.json", "job_notices.json", "program_notices.json"], help="읽을 수집 결과 파일들(모아 둔 것 + 이번 것)")
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY", "")

    if a.list_models:
        if not key:
            sys.exit("GEMINI_API_KEY 가 설정되지 않았습니다.")
        r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=30)
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print(m["name"].replace("models/", ""))
        return

    rows = list({x["url"]: x for f in a.src if os.path.exists(f) for x in json.load(open(f, encoding="utf-8"))}.values())   # 같은 공지는 한 번만
    targets = pick_targets(rows, a.all, a.images)
    if a.limit:
        targets = targets[:a.limit]
    chars = sum(len(r["body"]) for r in targets)
    print(f"대상 {len(targets)}개 / 본문 합계 약 {chars:,}자")

    if a.dry_run:
        for r in targets:
            print(f" - [{r.get('deadline_status', r.get('list'))}] {r['content_kind']} {len(r['body']):>5}자  {r['title'][:40]}")
        if targets:
            print("\n--- 첫 번째 프롬프트(앞 700자) ---")
            print(PROMPT.format(title=targets[0]["title"], date=targets[0].get("date") or (targets[0].get("posted") or "")[:10], body=targets[0]["body"])[:700])
        return
    if not key or not a.model:
        sys.exit("GEMINI_API_KEY 와 --model(또는 GEMINI_MODEL)이 필요합니다. 먼저 --list-models 를 실행하세요.")

    results = []
    if os.path.exists("step4_results.json"):                     # 한도에 걸려 끊겨도 이어서
        results = json.load(open("step4_results.json", encoding="utf-8"))
    done = {r["url"] for r in results if r.get("prompt_version") == PROMPT_VERSION}   # 옛 버전 결과는 새로 처리해 덮어쓴다
    skipped = failed = 0
    for n, r in enumerate(targets, 1):
        if r["url"] in done:
            skipped += 1
            print(f"[{n}/{len(targets)}] (이미 처리됨) {r['title'][:40]}")
            continue
        print(f"[{n}/{len(targets)}] {r['title'][:40]}", flush=True)
        imgs = fetch_images(r.get("images", [])) if r["content_kind"] == "이미지" else None
        tpl = IMG_PROMPT if imgs else PROMPT
        try:
            raw = call_gemini(key, a.model, tpl.format(title=r["title"], date=r.get("date") or (r.get("posted") or "")[:10], body=r["body"] or "(본문 없음)"), imgs)
        except Exception as e:                                    # noqa: BLE001
            print("   실패:", e)
            failed += 1
            if "재시도 실패" in str(e):      # 한도 문제면 더 호출해도 소용없음
                break
            continue
        try:
            v = validate(raw, r["body"], from_image=bool(imgs))
        except Exception as e:                                    # noqa: BLE001
            print("   검증 실패(AI 응답 형식 이상):", e, "| 원문:", str(raw)[:200])
            failed += 1
            continue
        rule = r["deadline"]
        print(f"   규칙: {rule or '-'} ({r.get('deadline_status', r.get('deadline_source'))})  →  AI: {v['deadline'] or '-'}  | 요약: {v['summary']}")
        if v["conditions"]:
            print("   조건:", "; ".join(f"{c['type']}={c['value']}" for c in v["conditions"]))
        if v["events"]:
            print("   행사 일정:", "; ".join(f"{d['label']}={d['datetime']}" for d in v["events"]))
        if v["gender"]:
            print("   성별 제한:", v["gender"])
        if v["deadlines"]:
            print("   마감 목록:", "; ".join(f"{d['label']}={d['datetime']}" for d in v["deadlines"]))
        if v["dropped"]:
            print("   버린 값(근거 없음):", v["dropped"])
        final, src = (v["deadline"], "ai") if v["deadline"] and not v["needs_review"] else (rule, "rule")
        if not final and v["deadline"]:
            final, src = v["deadline"], "ai_image"
        results = [x for x in results if x["url"] != r["url"]]
        results.append({"prompt_version": PROMPT_VERSION, "final_deadline": final, "final_source": src if final else None, "url": r["url"], "title": r["title"], "date": r.get("date") or (r.get("posted") or "")[:10], "rule_deadline": rule,
                        "rule_status": r.get("deadline_status", r.get("deadline_source")), "rule_candidates": r.get("deadline_candidates", []), **v})
        json.dump(results, open("step4_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        time.sleep(a.delay)
    left = [t for t in targets if t["url"] not in {x["url"] for x in results if x.get("prompt_version") == PROMPT_VERSION}]
    print(f"\n저장: step4_results.json ({len(results)}개) | 이번에 건너뜀 {skipped} | 실패 {failed} | 대상 중 아직 없음 {len(left)}")
    for t in left:
        print("   미처리:", t["title"][:50])
    if left:
        print("→ 같은 명령을 다시 실행하면 미처리분만 이어서 합니다.")


if __name__ == "__main__":
    main()
