import sqlite3, pathlib, datetime
DB_PATH = pathlib.Path("data/watchlater.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, url TEXT, title TEXT,
  -- YouTube 정보
  channel TEXT, channel_id TEXT, channel_url TEXT, uploader_id TEXT,
  upload_date TEXT,            -- YouTube 업로드(생성)일 YYYY-MM-DD
  duration_sec INTEGER, view_count INTEGER, like_count INTEGER, comment_count INTEGER,
  yt_categories TEXT, yt_tags TEXT, description TEXT, thumbnail TEXT, live_status TEXT,
  -- WL / 처리 이력
  wl_position INTEGER,         -- 처음 발견 시 WL 내 순번(0=가장 최근 추가)
  first_seen_at TEXT,          -- 이 도구가 WL에서 처음 발견한 시각
  watched_at TEXT,             -- 사용자가 본 날짜(수동 입력; check.py watched)
  processed_at TEXT, processed_date TEXT,
  status TEXT, error TEXT, transcript_lang TEXT, model TEXT,
  -- 분석 결과
  category TEXT,               -- 1단계 태그(경제/AI/IT/...)
  subtag TEXT,                 -- 2단계 태그(skill, llm-wiki, 금리 ...)
  extra_tags TEXT,             -- 추가 태그(JSON 배열)
  one_liner TEXT, summary TEXT, keywords TEXT,
  comments_insight TEXT,       -- 댓글 중 의미 있는 내용 정리
  macro_phase TEXT, macro_phase_reason TEXT, indicators_to_watch TEXT,  -- 경제용
  analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS people(video_id TEXT, name TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS links(video_id TEXT, url TEXT, kind TEXT, context TEXT);
CREATE TABLE IF NOT EXISTS tags(video_id TEXT, level INTEGER, tag TEXT);  -- 1=category 2=subtag 3=extra
CREATE TABLE IF NOT EXISTS checks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT,
  kind TEXT,                   -- indicator | stock | event
  target TEXT, what_to_check TEXT, expectation TEXT,
  check_date TEXT,             -- 확인해야 할 미래 시점
  status TEXT DEFAULT 'pending',  -- pending | confirmed | refuted | partial | unknown
  checked_at TEXT, result TEXT, opinion TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_due ON checks(status, check_date);
CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(processed_date);
"""

def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(videos)")}
    for name, typ in (("transcript", "TEXT"), ("transcript_status", "TEXT"),
                      ("transcript_retry_at", "TEXT"), ("transcript_attempts", "INTEGER DEFAULT 0")):
        if name not in cols:                           # 기존 DB 마이그레이션
            db.execute(f"ALTER TABLE videos ADD COLUMN {name} {typ}")
    db.commit()
    return db

def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def today(): return datetime.date.today().isoformat()
