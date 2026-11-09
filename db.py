import os
import sqlite3, pathlib, datetime, json
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
  checked_at TEXT, result TEXT, opinion TEXT, reason TEXT,
  rationale TEXT,              -- 예상의 근거(직접 등록 시 왜 그렇게 보는지)
  created_at TEXT              -- 등록 시점(영상 없는 직접 등록 항목의 기준일)
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
CREATE TABLE IF NOT EXISTS dup_seen(video_id TEXT, owner TEXT, playlist_name TEXT, seen_at TEXT, PRIMARY KEY(video_id, owner, playlist_name));  -- 이미 분석된 영상이 다른 재생목록에도 저장돼 있음을 기록(분석은 건너뜀)
CREATE TABLE IF NOT EXISTS backlog(video_id TEXT PRIMARY KEY, title TEXT, owner TEXT, playlist_name TEXT, pos INTEGER, seen_at TEXT);  -- 재생목록에 있으나 아직 분석 안 된 영상(collect 때 갱신)
CREATE TABLE IF NOT EXISTS analysis_runs(      -- 분석 실행 기록: 어떤 도구(engine)·모델이 이 영상을 어떻게 분석했는가 (여러 도구의 결과를 나란히 보관)
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, engine TEXT, model TEXT, run_at TEXT, source TEXT,
  category TEXT, subtag TEXT, one_liner TEXT, n_summary INTEGER, n_checks INTEGER, n_links INTEGER, n_people INTEGER,
  analysis_json TEXT, UNIQUE(video_id, engine, model, run_at)
);
CREATE TABLE IF NOT EXISTS highlights(          -- 제일 인상 깊은 영상 모음(highlight.py / yt-highlight 스킬): 상세 분석 JSON 보관
  video_id TEXT PRIMARY KEY, url TEXT, title TEXT, channel TEXT, channel_url TEXT, upload_date TEXT, duration_sec INTEGER, view_count INTEGER,
  note TEXT, added_at TEXT, engine TEXT, model TEXT, analysis_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_video ON analysis_runs(video_id);
CREATE INDEX IF NOT EXISTS idx_checks_due ON checks(status, check_date);
CREATE INDEX IF NOT EXISTS idx_videos_date ON videos(processed_date);
"""

def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    cols = {r[1] for r in db.execute("PRAGMA table_info(videos)")}
    for name, typ in (("transcript", "TEXT"), ("transcript_status", "TEXT"),
                      ("transcript_retry_at", "TEXT"), ("owner", "TEXT"), ("playlist_name", "TEXT"), ("transcript_attempts", "INTEGER DEFAULT 0"), ("engine", "TEXT"), ("run_id", "TEXT"), ("lessons", "TEXT"), ("business", "TEXT")):
        if name not in cols:                           # 기존 DB 마이그레이션
            db.execute(f"ALTER TABLE videos ADD COLUMN {name} {typ}")
    ccols = {r[1] for r in db.execute("PRAGMA table_info(checks)")}
    for name in ("rationale", "created_at"):
        if name not in ccols: db.execute(f"ALTER TABLE checks ADD COLUMN {name} TEXT")
    for tbl, col in (("indicator_values", "llm"), ("macro_daily", "llm")):          # 어떤 AI(엔진 · 모델)가 만든 값인가
        if col not in {r[1] for r in db.execute(f"PRAGMA table_info({tbl})")}: db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
    icols = {r[1] for r in db.execute("PRAGMA table_info(indicators)")}
    for name in ("source", "symbol", "mapped_at", "alias_of", "enrich_llm", "map_llm"):
        if name not in icols: db.execute(f"ALTER TABLE indicators ADD COLUMN {name} TEXT")
    # 중복 정리: 영상은 id(URL 의 v=) 가 키라 중복 불가. 하위 표의 중복 행 제거 + 유일 인덱스, 이미 분석된 영상의 backlog 제거
    db.execute("DELETE FROM indicator_sources WHERE rowid NOT IN (SELECT min(rowid) FROM indicator_sources GROUP BY indicator_id, video_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_indicator_sources ON indicator_sources(indicator_id, video_id)")
    db.execute("DELETE FROM backlog WHERE video_id IN (SELECT id FROM videos WHERE status='done')")
    db.execute("UPDATE videos SET engine='claude' WHERE engine IS NULL AND status='done'")
    if "enrich_llm" in {r[1] for r in db.execute("PRAGMA table_info(indicators)")}:    # 기존 값 채우기: 이전 값은 모두 claude · sonnet (2026-11-08 17시 이후 agy 처리분 제외)
        db.execute("UPDATE indicators SET enrich_llm=CASE WHEN enriched_at>='2026-11-08T17:00' THEN 'agy · Gemini 3.8 Flash (Medium)' ELSE 'claude · sonnet' END WHERE enriched_at IS NOT NULL AND enrich_llm IS NULL")
        db.execute("UPDATE indicators SET map_llm=CASE WHEN mapped_at>='2026-11-08T17:00' THEN 'agy · Gemini 3.8 Flash (Medium)' ELSE 'claude · sonnet' END WHERE mapped_at IS NOT NULL AND map_llm IS NULL")
        db.execute("UPDATE indicator_values SET llm='claude · sonnet' WHERE meaning IS NOT NULL AND llm IS NULL")
        db.execute("UPDATE macro_daily SET llm='claude · sonnet' WHERE llm IS NULL")
    if not db.execute("SELECT 1 FROM analysis_runs LIMIT 1").fetchone():           # 기존 분석 결과를 실행 기록으로 한 번 옮긴다
        for r in db.execute("SELECT id, model, processed_at, analysis_json FROM videos WHERE status='done' AND analysis_json IS NOT NULL").fetchall():
            add_run(db, r["id"], "claude", r["model"] or "sonnet", json.loads(r["analysis_json"]), r["processed_at"], "production")
    db.execute("UPDATE videos SET owner='cheoljoo', playlist_name='my-watch-later' WHERE owner IS NULL")
    db.commit()
    return db

def add_run(db, vid, engine, model, res, run_at=None, source="production"):
    """분석 결과(res: analyze.SCHEMA 형태)를 실행 기록에 남긴다. 같은 (영상,도구,모델,시각)이면 무시."""
    db.execute("""INSERT OR IGNORE INTO analysis_runs(video_id,engine,model,run_at,source,category,subtag,one_liner,n_summary,n_checks,n_links,n_people,analysis_json)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (vid, engine, model, run_at or now(), source, res.get("category"), res.get("subtag"), res.get("one_liner"),
                len(res.get("summary_points") or []), len(res.get("checks") or []), len(res.get("links") or []), len(res.get("people") or []),
                json.dumps(res, ensure_ascii=False)))

def llm_tag():
    """지금 일하는 AI 표기 '엔진 · 모델' (run_skill.sh 가 YT_ENGINE/YT_MODEL 을 지정, 없으면 claude · config 의 모델)."""
    eng = os.environ.get("YT_ENGINE") or "claude"
    mod = os.environ.get("YT_MODEL")
    if not mod:
        import tomllib; mod = tomllib.load(open(pathlib.Path(__file__).parent / "config.toml", "rb")).get("model", "sonnet")
    return f"{eng} · {mod}"
_RUN = {}
def run_id(engine):
    """이번 실행의 리포트 이름 '날짜_시분-엔진' (환경변수 YT_RUN 이 있으면 그것, 없으면 프로세스에서 처음 쓸 때 정해 계속 사용)."""
    if os.environ.get("YT_RUN"): return os.environ["YT_RUN"]
    return _RUN.setdefault(engine, f"{datetime.datetime.now():%Y-%m-%d_%H%M}-{engine}")
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def today(): return datetime.date.today().isoformat()
