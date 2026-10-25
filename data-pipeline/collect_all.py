"""수집 → AI 추출(선택) → DB 저장 → 공통 JSON 내보내기를 한 번에 돌린다.

실행 (ssu-steps 폴더에서, PowerShell):
  python collect_all.py                      # 기본: 슈캐치 카테고리당 5개, 잡슈 1페이지·상세 5개
  python collect_all.py --catch 20 --pages 2 --detail 20     # 더 많이
  python collect_all.py --skip-collect       # 이미 받은 json으로 DB·내보내기만 다시
결과: hyetaek.db (서버 DB) / common_notices.json (팀 공통 형식) / feed.json (앱 API 응답 예시)

AI(Gemini) 단계는 환경변수 GEMINI_API_KEY 가 있을 때만 돈다(키는 코드에 쓰지 않는다).
나중에 FastAPI/스케줄러에서는 run_once() 를 그대로 불러 쓰면 된다."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def sh(args: list[str]) -> bool:
    print("\n$", " ".join(args), flush=True)
    return subprocess.run([sys.executable, *args]).returncode == 0


def run_once(catch: int = 5, pages: int = 1, detail: int = 5, skip_collect: bool = False, ai: bool | None = None) -> dict:
    ok = {}
    if not skip_collect:
        ok["슈캐치"] = sh(["step3_verify_body.py", str(catch)])                       # 정중한 수집(1초 간격)은 각 수집 코드가 지킨다
        ok["잡슈 공지"] = sh(["job_collect.py", "--pages", str(pages), "--detail", str(detail)])
        ok["잡슈 프로그램"] = sh(["program_collect.py", "--pages", str(pages), "--detail", str(detail)])
    use_ai = bool(os.environ.get("GEMINI_API_KEY")) if ai is None else ai
    if use_ai:
        ok["AI 추출"] = sh(["step4_extract.py", "--all"])        # 이미 처리한 공지는 건너뛰므로 새 공지만 호출한다
    else:
        print("\n(GEMINI_API_KEY 없음 → AI 추출 건너뜀. 규칙으로 읽은 값만 저장됩니다)")
    ok["DB 저장"] = sh(["-m", "hyetaek.build_db"])
    ok["공통 JSON"] = sh(["export_common.py"])
    print("\n=== 결과 ===")
    for k, v in ok.items():
        print(f"  {'OK ' if v else 'FAIL'} {k}")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--catch", type=int, default=5, help="슈캐치: 카테고리당 받을 공지 수")
    ap.add_argument("--pages", type=int, default=1, help="잡슈: 목록 페이지 수")
    ap.add_argument("--detail", type=int, default=5, help="잡슈: 목록마다 상세를 받을 개수")
    ap.add_argument("--skip-collect", action="store_true", help="수집은 건너뛰고 DB 저장·내보내기만")
    a = ap.parse_args()
    run_once(a.catch, a.pages, a.detail, a.skip_collect)
