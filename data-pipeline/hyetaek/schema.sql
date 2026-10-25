-- 서버 DB (SQLite로 시작, 나중에 PostgreSQL로 옮겨도 같은 구조).
-- 원칙: 사용자 정보(학과/학년/성적/관심 분야)는 이 DB에 절대 없다. 공지의 '구조화된 사실'만 있다.

CREATE TABLE IF NOT EXISTS notices (
  id            TEXT PRIMARY KEY,          -- sha1(source|source_key)[:16]. 같은 글이면 항상 같은 값
  version       INTEGER NOT NULL,          -- 전역 증가 번호. 앱은 '내가 가진 마지막 version 이후'만 받는다
  source        TEXT NOT NULL,             -- ssu_catch | job_ssu | ssu_path
  source_key    TEXT NOT NULL,
  url           TEXT NOT NULL,
  title         TEXT NOT NULL,
  source_category TEXT,                    -- 사이트가 붙인 원래 카테고리
  topic         TEXT NOT NULL,             -- 앱 공통 주제(고정 목록). 사용자의 '관심 분야'와 비교하는 값
  posted_at     TEXT,                      -- YYYY-MM-DD
  deadline_at   TEXT,                      -- 대표 마감 YYYY-MM-DDTHH:MM (없으면 NULL)
  deadline_kind TEXT NOT NULL,             -- FIXED | OPEN(상시/채용시마감) | NONE(정보 공지) | UNKNOWN
  summary       TEXT,                      -- AI 한 줄 요약(≤60자)
  body_text     TEXT,
  content_kind  TEXT,                      -- TEXT | 이미지 | 첨부만 | 본문없음
  needs_review  INTEGER NOT NULL DEFAULT 0,-- 1 = 이미지에서 AI가 읽음 등, 근거 검증이 안 된 값 포함
  audience_json TEXT NOT NULL,             -- 아래 audience 구조 (JSON)
  extra_json    TEXT,                      -- 출처별 추가 정보 (회사/근무지/채용구분/path_seq ...)
  content_hash  TEXT NOT NULL,             -- 본문이 바뀌었는지, 같은 글인지 판단
  dup_of        TEXT,                      -- 중복이면 대표 글의 id (피드에는 대표만 보낸다)
  is_active     INTEGER NOT NULL DEFAULT 1,
  first_seen_at TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  UNIQUE (source, source_key)
);
CREATE INDEX IF NOT EXISTS ix_notices_version  ON notices(version);
CREATE INDEX IF NOT EXISTS ix_notices_deadline ON notices(deadline_at);
CREATE INDEX IF NOT EXISTS ix_notices_topic    ON notices(topic);

-- 마감이 여러 개인 공지(프로그램별 / 조기·일반 / 본교·상대교)
CREATE TABLE IF NOT EXISTS notice_deadlines (
  notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
  label     TEXT,
  at        TEXT NOT NULL
);
-- 사이트 카테고리가 둘 이상인 글
CREATE TABLE IF NOT EXISTS notice_categories (
  notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
  category  TEXT NOT NULL,
  PRIMARY KEY (notice_id, category)
);
CREATE TABLE IF NOT EXISTS notice_files (
  notice_id TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL,                 -- attachment | image
  name      TEXT,
  url       TEXT NOT NULL
);
-- AI는 (본문 해시, 프롬프트 버전) 당 한 번만 부른다. 같은 글을 다시 수집해도 비용이 늘지 않는다.
CREATE TABLE IF NOT EXISTS ai_runs (
  notice_id      TEXT NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
  content_hash   TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model          TEXT NOT NULL,
  result_json    TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  PRIMARY KEY (notice_id, content_hash, prompt_version)
);
CREATE TABLE IF NOT EXISTS crawl_state (
  source TEXT PRIMARY KEY, last_run_at TEXT, last_ok_at TEXT, last_error TEXT, interval_min INTEGER
);
