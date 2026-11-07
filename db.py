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
  owner TEXT,                  -- 이 영상을 재생목록에 모아 둔 사람(누가 정리하는가)
  playlist_name TEXT,
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
-- 매일 추적하는 지표/종목 (분석할 때마다 계속 늘어남)
CREATE TABLE IF NOT EXISTS indicators(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE,
  category TEXT,               -- 금리/물가/환율/주가지수/고용/원자재/유동성/종목/기타
  unit TEXT, description TEXT, interpretation TEXT,   -- 무엇인지 / 어떻게 해석하는지
  baseline TEXT,               -- 평균·균형·기본값(정상 범위)
  importance TEXT DEFAULT 'normal',                   -- high | normal
  warn_low REAL, warn_high REAL,                      -- 경고 임계값(넘거나 내려가면 알림)
  enriched_at TEXT, first_seen_at TEXT, active INTEGER DEFAULT 1,
  source TEXT, symbol TEXT, mapped_at TEXT, alias_of INTEGER           -- 실제 시세 출처: yahoo(심볼) | fred(시리즈) | none
);
CREATE TABLE IF NOT EXISTS indicator_sources(indicator_id INTEGER, video_id TEXT, why TEXT, PRIMARY KEY(indicator_id, video_id));
CREATE TABLE IF NOT EXISTS indicator_values(
  indicator_id INTEGER, date TEXT,                    -- 기록한 날
  value REAL, value_text TEXT, value_date TEXT,       -- 값 / 표시용 문자열 / 값의 기준일
  prev_value REAL, change_pct REAL, direction TEXT,   -- up | down | flat | unknown
  signal TEXT, signal_reason TEXT,                    -- warning | threshold | direction | NULL
  meaning TEXT, PRIMARY KEY(indicator_id, date)
);
CREATE TABLE IF NOT EXISTS macro_daily(date TEXT PRIMARY KEY, phase_index INTEGER, phase TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS idx_checks_due ON checks(status, check_date);
CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(processed_date);
"""

def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(videos)")}
    for name, typ in (("transcript", "TEXT"), ("transcript_status", "TEXT"),
                      ("transcript_retry_at", "TEXT"), ("owner", "TEXT"), ("playlist_name", "TEXT"), ("transcript_attempts", "INTEGER DEFAULT 0")):
        if name not in cols:                           # 기존 DB 마이그레이션
            db.execute(f"ALTER TABLE videos ADD COLUMN {name} {typ}")
    icols = {r[1] for r in db.execute("PRAGMA table_info(indicators)")}
    for name in ("source", "symbol", "mapped_at", "alias_of"):
        if name not in icols: db.execute(f"ALTER TABLE indicators ADD COLUMN {name} TEXT")
    db.execute("UPDATE videos SET owner='cheoljoo', playlist_name='my-watch-later' WHERE owner IS NULL")
    db.commit()
    return db

def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def today(): return datetime.date.today().isoformat()
