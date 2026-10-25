# SSU:Pick 공지 수집 파이프라인

숭실대 **슈캐치(학교 공지)**와 **잡슈(채용·알바·공모전·진로 프로그램)**를 수집해서
**팀 공통 JSON**과 **SQLite DB**로 만드는 서버 쪽 코드입니다.
앱(Android, Java)은 이 결과를 받아서 폰 안에서 맞춤 추천과 마감 알림을 합니다.

---

## 1. 빠른 시작 — `collect_all.py` 하나만 실행하면 됩니다

### ① 설치 (처음 한 번)
```powershell
cd data-pipeline
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### ② Gemini 키 설정 (처음 한 번, 선택)
키는 https://aistudio.google.com/apikey 에서 각자 만들고, **환경변수에만** 넣습니다. 코드·JSON·채팅에 쓰지 않습니다.
```powershell
setx GEMINI_API_KEY "내 키"
setx GEMINI_MODEL "gemini-3.5-flash-lite"
```
설정 후 PowerShell 창을 새로 엽니다. 키가 없어도 실행은 되지만 AI 단계만 건너뛰어 마감·조건·요약 정보가 많이 비게 됩니다.

### ③ 실행
```powershell
python collect_all.py
```
수집 → AI 추출 → DB 저장 → 공통 JSON 내보내기까지 한 번에 합니다. 마지막에 `=== 결과 ===`가 모두 `OK`면 성공입니다.

더 많이 받으려면: `python collect_all.py --catch 20 --pages 2 --detail 20`
(슈캐치는 카테고리마다 20개, 잡슈는 목록마다 2쪽·상세 20개. 처음 실행은 5~30분 걸립니다)

### ④ 결과 확인 (선택)
```powershell
python validate_common.py
```
`오류 0건`이면 공통 형식에 맞게 만들어진 것입니다.

---

## 2. 수집한 전체 DB

`collect_all.py`를 실행하면 두 가지가 만들어집니다. **둘은 같은 데이터**이고, JSON은 DB를 공통 형식으로 내보낸 것입니다.

| 파일 | 무엇인가 | 저장소 |
|---|---|---|
| `hyetaek.db` | **서버 DB (SQLite)**. 수집한 공지 전체와 마감·첨부·카테고리를 표로 저장 | 실행하면 생성 (바이너리라 올리지 않음) |
| **`common_notices.json`** | **최종 DB를 팀 공통 형식 JSON으로 내보낸 전체 목록 (243건)**. 앱·팀원이 쓰는 최종 결과 | **포함** (2026-10-24 실행본) |
| `common_notices.sample.json` | 위 전체에서 유형별로 고른 14건 (빠르게 훑어보기용) | 포함 |

`common_notices.json`은 학교 사이트에 공개된 공지를 그대로 담고 있습니다(본문·담당자 연락처 포함). 다시 실행하면 최신 공지로 새로 만들어집니다.

### 2026-10-24 실행 결과 (`--catch 20 --pages 2 --detail 20`)

| 항목 | 값 |
|---|---|
| 전체 | **243건** (중복 제거 후), 형식 검사 243/243 통과 |
| 출처 | 슈캐치 151 · 잡슈 92 |
| 게시일 범위 | 2025-03-19 ~ 2026-10-23 |
| 주제 | 비교과·프로그램 44 · 채용·인턴 38 · 학사 30 · 아르바이트 20 · 공모전·대외활동 20 · 장학 17 · 봉사 15 · 해외·교환 15 · 교원채용 15 · 기타 15 · 유학생 14 |
| 마감 상태 | FIXED 184 · UNKNOWN 42 · NONE 15 · OPEN 2 |
| 본문 유형 | 텍스트 200 · 첨부만 25 · 이미지 16 · 본문없음 2 |
| 추가로 뽑은 정보 | 요약 203건 · 대상 조건 98건 · 행사 일정 84건 |

UNKNOWN은 주로 본문 없이 이미지·첨부에만 내용이 있는 공지입니다. 앱에서 "확인 필요"로 보여 줍니다.

### DB 표 구조 (`hyetaek/schema.sql`)

| 표 | 내용 |
|---|---|
| `notices` | 공지 한 건 = 한 줄. 제목, 원문 링크, 주제, 게시일, 대표 마감, 마감 상태, 요약, 본문, 대상 조건(`audience_json`), 출처별 정보(`extra_json`), 중복 여부(`dup_of`), 변경 번호(`version`) |
| `notice_deadlines` | 마감이 여러 개인 공지의 마감 목록 (프로그램별, 1·2차 등) |
| `notice_categories` | 사이트 카테고리 (한 글이 여러 카테고리에 올라온 경우) |
| `notice_files` | 첨부·이미지 링크 (파일은 내려받지 않음) |
| `ai_runs`, `crawl_state` | AI 실행 기록·수집 상태용으로 만들어 둔 표 (FastAPI 단계에서 사용 예정) |

- `version`은 공지가 새로 생기거나 바뀔 때마다 올라갑니다. 앱은 "내가 가진 마지막 version 이후"만 받으면 됩니다.
- 사용자 정보(학과·학년·평점·관심 분야)는 이 DB에 없습니다.
- DB → 공통 JSON 변환은 `export_common.py`가 합니다. (`audience_json` → `eligibility`, `notice_deadlines` + 행사일 → `deadlines` 등)

---

## 3. 공통 JSON 구조 (형식 통일 방법)

출처마다 HTML·필드가 다르지만, 모든 공지를 **하나의 모양**으로 맞춥니다.

| 파일 | 역할 |
|---|---|
| **`notice.schema.json`** | **공통 구조의 기준(규칙)**. 어떤 필드가 있고, 필수인지, 어떤 값만 되는지 정의 |
| `examples.json` | 기준에 맞춘 손으로 쓴 예시 4건 (슈캐치·인스타·청년몽땅·LH) |
| `common_notices.sample.json` | 기준에 맞춘 실제 결과 14건 |
| `validate_common.py` | JSON이 기준에 맞는지 검사 (`python validate_common.py 파일명`) |

다른 출처(인스타그램, 청년몽땅, LH, SH)도 **`notice.schema.json`에 맞춰 내보내면** 같은 DB·앱에서 그대로 쓸 수 있습니다.

### 필드

**필수 8개**

| 필드 | 설명 | 예 |
|---|---|---|
| `id` | `출처:번호` (전체에서 유일) | `ssu_catch:28ef28380247` |
| `source` | 출처 | `ssu_catch` `job_ssu` `instagram` `youth_mongddang` `lh` `sh` |
| `source_id` | 출처 안의 번호 | `28ef28380247` |
| `url` | 원문 링크 | |
| `title` | 제목 | |
| `topic` | 주제 | 장학, 학사, 채용·인턴, 아르바이트, 비교과·프로그램, 해외·교환, 봉사, 공모전·대외활동, 유학생, 교원채용, 주거, 청년지원, 기타 |
| `deadline_status` | 마감 상태 | `FIXED`(날짜 있음) `OPEN`(상시) `NONE`(마감 없음) `UNKNOWN`(못 찾음 → 확인 필요) |
| `deadlines` | 마감·일정 목록 (없으면 `[]`) | 아래 참고 |

**선택**

| 필드 | 설명 |
|---|---|
| `posted_at` | 게시일 `YYYY-MM-DD` |
| `updated_at` | 수집기가 마지막으로 바뀐 걸 확인한 시각 (ISO8601) |
| `deadline_at` | 대표 마감 (홈 정렬·D-day). 행사일은 넣지 않음 |
| `eligibility` | 대상 조건 (아래 참고) |
| `summary` | 한 줄 요약 |
| `body` | 본문(글자만) |
| `needs_review` | 사람이 확인해야 하면 `true` |
| `content_kind` | `TEXT` `이미지` `첨부만` `본문없음` |
| `attachments` | 첨부 `[{name, url}]` — 링크만 |
| `extra` | 출처별 추가 정보 (회사, 근무지 등) |

**`deadlines` 항목**

| 필드 | 설명 |
|---|---|
| `kind` | `APPLICATION`(신청) `SCHOOL_NOMINATION`(학교 추천) `DOCUMENT`(서류) `INTERVIEW`(면접) `EVENT`(행사·훈련·설명회) `OTHER` |
| `label` | 이름 (예: 1차 모집) |
| `date`, `at` | `2026-11-12`, `2026-11-12T09:00:00+09:00` |
| `precision` | `MINUTE`(시각까지) `DAY`(날짜만) |

**`eligibility` (대상 조건)** — 비어 있으면 "제한 없음 또는 모름"이고, 앱은 **모르면 제외하지 않습니다**.

| 필드 | 값 |
|---|---|
| `scope`, `colleges`, `depts` | 학과 범위 `ALL` / `COLLEGE` / `DEPT`와 단과대·학과 이름 |
| `grades` | 학년 `[3, 4]` |
| `min_semester`, `max_semester` | 학기 범위 (1학년 1학기=1 … 4학년 2학기=8). "2~7학기" → 2, 7 |
| `levels` | `UNDERGRAD` `GRAD` |
| `statuses` | `ENROLLED`(재학) `RETURNING`(복학예정) `LEAVE`(휴학) `GRADUATING`(졸업예정) `GRADUATE`(졸업) `JOB_SEEKER`(취준생) |
| `gender` | `MALE_ONLY` `FEMALE_ONLY` (제한 있을 때만) |
| `nationality` | `DOMESTIC_ONLY` `FOREIGN_ONLY` |
| `min_age`, `max_age`, `regions`, `min_gpa` | 나이·지역·평점 |
| `other_conditions` | 구조로 못 옮긴 조건 (앱에 "확인 필요"로 표시) |
| `confidence` | `high` `medium` `low` |

"마감됨"은 JSON에 두지 않습니다. 앱이 `deadline_at`과 현재 시각을 비교해 계산합니다.

---

## 4. 동작 방식

`collect_all.py`가 내부에서 아래 순서로 실행합니다.

```
① 수집      step3_verify_body.py   슈캐치         → step3_notices.json
            job_collect.py         잡슈 공고      → job_notices.json
            program_collect.py     잡슈 프로그램  → program_notices.json
② AI 추출   step4_extract.py       Gemini         → step4_results.json
③ 변환·DB   hyetaek/build_db.py    공통 모양 + 중복 제거 → hyetaek.db
④ 내보내기  export_common.py       → common_notices.json
```

설계 원칙
- **출처마다 수집기를 따로** 둡니다. 사이트마다 HTML이 달라서입니다. ③부터는 모든 출처가 같은 길을 갑니다.
- **규칙(정규식)이 먼저, AI는 규칙이 못 하는 것만** 합니다. (여러 마감 중 최종 고르기, 문장 속 조건, 요약, 행사일, 성별)
- AI 값은 **근거 문장이 본문에 그대로 있을 때만** 받아들입니다. 없으면 버립니다.
- 이미 처리한 공지는 AI를 다시 부르지 않습니다. 수집한 공지는 `archive_*.json`에 모아 두어 규칙이 바뀌면 옛 공지도 다시 처리합니다.
- DB는 지우지 않고 **새 공지는 추가, 바뀐 공지만 갱신**(upsert)합니다. 앱은 `version`으로 바뀐 것만 받을 수 있습니다.

지키는 것
- 학교 사이트에는 1초 간격으로 접근하고, 첨부파일은 내려받지 않고 링크만 저장합니다.
- AI에는 공개된 공지 본문만 보냅니다.
- 개인정보(학과·학년·평점·관심 분야)는 서버에 없습니다. 맞춤 판정은 폰 안에서 합니다.
- u-SAINT 등 로그인 정보는 받거나 저장하지 않습니다.

---

## 5. 폴더 구조

```
data-pipeline/
├─ collect_all.py          ← 이것만 실행
├─ step3_verify_body.py    수집: 슈캐치
├─ job_collect.py          수집: 잡슈 공고
├─ program_collect.py      수집: 잡슈 프로그램
├─ helpers.py, deadline.py 수집용 함수 (HTML 읽기, 마감일 찾기)
├─ step4_extract.py        AI 추출
├─ export_common.py        DB → 공통 JSON
├─ validate_common.py      공통 JSON 검사
├─ notice.schema.json      ★ 공통 구조 기준
├─ examples.json           공통 구조 예시 (손으로 작성)
├─ common_notices.json   ★ 최종 결과: 전체 DB를 공통 JSON으로 (243건)
├─ common_notices.sample.json  공통 구조 예시 (실제 결과 14건)
├─ requirements.txt
└─ hyetaek/
   ├─ normalize.py         출처별 데이터 → 공통 모양
   ├─ build_db.py          DB 만들기
   ├─ store.py, schema.sql DB 저장·조회
   ├─ taxonomy.py          학과·단과대·주제 분류표
   └─ match.py             맞춤 판정 규칙 (앱 Java 구현의 기준, 서버는 사용 안 함)
```

## 6. 앞으로
- FastAPI 서버: `GET /v1/notices?since=N`(변경분), 공지 상세, 주기 수집(`collect_all.run_once()`를 정해진 시각에 실행)
