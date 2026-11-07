"""재생목록(여러 소유자) -> 병렬 수집(info/댓글/자막) -> 영상별 Claude 분석 -> DB 저장 -> 일별 HTML 리포트.
사용:  uv run main.py [--limit N] [--only VIDEO_ID] [--show-top N] [--no-report]"""
import argparse, datetime, json, pathlib, tomllib, sys
import db as D
from fetch_list import fetch_playlist
from concurrent.futures import ThreadPoolExecutor
from fetcher import collect_many, write_log
from analyze import analyze, UsageLimit
import report, export_json, indicators, autocheck

cfg = tomllib.loads(pathlib.Path("config.toml").read_text(encoding="utf-8"))
DATA = pathlib.Path("data")
LIVE = {"is_live", "was_live", "is_upcoming", "post_live"}   # 생방송 출신: 자막이 며칠 뒤에 생길 수 있음
RETRY_DAYS = 1 * 7

def vocab(con):
    return [r[0] for r in con.execute("SELECT tag FROM tags GROUP BY tag ORDER BY count(*) DESC LIMIT 60")]

COLS = ["url","title","owner","playlist_name","channel","channel_id","channel_url","uploader_id","upload_date","duration_sec",
        "view_count","like_count","comment_count","yt_categories","yt_tags","description","thumbnail","live_status",
        "processed_at","processed_date","status","error","transcript_lang","model","category","subtag","extra_tags","one_liner",
        "summary","keywords","comments_insight","macro_phase","macro_phase_reason","indicators_to_watch","analysis_json"]

def store(con, v, col, res, model):
    """분석 결과를 DB에 저장(메인 스레드 전용). watched_at / first_seen_at / wl_position 은 보존."""
    m, vid = col["meta"], v["id"]
    summary = "\n".join(f"- {p}" for p in res["summary_points"])
    mac = res.get("macro") or {}
    row = dict(m, url=v["url"], title=v["title"], owner=v["owner"], playlist_name=v["playlist"],
               processed_at=D.now(), processed_date=D.today(), status="done", error=None, transcript_lang=col["lang"], model=model,
               category=res["category"], subtag=res["subtag"], extra_tags=json.dumps(res["extra_tags"], ensure_ascii=False),
               one_liner=res["one_liner"], summary=summary, keywords=json.dumps(res["keywords"], ensure_ascii=False),
               comments_insight=res["comments_insight"], macro_phase=mac.get("phase"), macro_phase_reason=mac.get("phase_reason"),
               indicators_to_watch=json.dumps(mac.get("indicators_to_watch", []), ensure_ascii=False),
               analysis_json=json.dumps(res, ensure_ascii=False))
    con.execute(f"""INSERT INTO videos(id,wl_position,first_seen_at,{",".join(COLS)}) VALUES(?,?,?,{",".join("?" * len(COLS))})
        ON CONFLICT(id) DO UPDATE SET {",".join(f"{c}=excluded.{c}" for c in COLS)}""",
        (vid, v["pos"], D.now(), *[row[c] for c in COLS]))
    old = con.execute("SELECT transcript_attempts FROM videos WHERE id=?", (vid,)).fetchone()
    att = (old["transcript_attempts"] or 0) + 1
    if col["transcript"]: st, ra = "ok", None
    elif m["live_status"] in LIVE and att < 2:
        st, ra = "pending_retry", (datetime.date.today() + datetime.timedelta(days=RETRY_DAYS)).isoformat()
    elif m["live_status"] in LIVE: st, ra = "gave_up", None
    else: st, ra = "none", None
    con.execute("UPDATE videos SET transcript=?, transcript_status=?, transcript_retry_at=?, transcript_attempts=? WHERE id=?",
                (col["transcript"], st, ra, att, vid))
    for t in ("people", "links", "tags"):
        con.execute(f"DELETE FROM {t} WHERE video_id=?", (vid,))
    con.execute("DELETE FROM checks WHERE video_id=? AND status='pending'", (vid,))   # 기록된 확인결과는 보존
    con.executemany("INSERT INTO people VALUES(?,?,?)", [(vid, p["name"], p["role"]) for p in res["people"]])
    con.executemany("INSERT INTO links VALUES(?,?,?,?)", [(vid, l["url"], l["kind"], l["context"]) for l in res["links"]])
    con.execute("INSERT INTO tags VALUES(?,1,?)", (vid, res["category"]))
    con.execute("INSERT INTO tags VALUES(?,2,?)", (vid, res["subtag"]))
    con.executemany("INSERT INTO tags VALUES(?,3,?)", [(vid, t) for t in res["extra_tags"]])
    con.executemany("INSERT INTO checks(video_id,kind,target,what_to_check,expectation,check_date) VALUES(?,?,?,?,?,?)",
                    [(vid, c["kind"], c["target"], c["what_to_check"], c["expectation"], c["check_date"]) for c in res["checks"]])
    con.commit()
    d = DATA / vid
    (d / "analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "summary.md").write_text(f"# {v['title']}\n\n**{res['category']} / {res['subtag']}**\n\n{res['one_liner']}\n\n{summary}\n", encoding="utf-8")

def mark_error(con, v, msg):
    con.execute("""INSERT INTO videos(id,url,title,owner,playlist_name,status,error,first_seen_at,wl_position) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET status='error', error=excluded.error""",
        (v["id"], v["url"], v["title"], v["owner"], v["playlist"], "error", msg[:500], D.now(), v["pos"]))
    con.commit()

def run_pipeline(con, targets, refresh=False):
    """1단계 수집(병렬·적응형) -> 2단계 분석(영상별 Claude 호출, 병렬) -> 3단계 DB 저장. 처리 건수 반환."""
    if not targets: return 0
    if refresh:
        for v in targets:
            for f in (DATA / v["id"]).glob(f"{v['id']}.*.vtt"): f.unlink()
            (DATA / v["id"] / f"{v['id']}.info.json").unlink(missing_ok=True)
    print(f"[1/3] 수집 {len(targets)}개 (병렬 최대 {cfg.get('parallel_collect', 3)})", flush=True)
    got, bad, lines = collect_many(targets, cfg)
    for vid, msg in bad.items(): mark_error(con, next(v for v in targets if v["id"] == vid), msg)
    print(f"      수집 성공 {len(got)} / 실패 {len(bad)}  — 로그: {write_log(lines)}", flush=True)
    todo = [v for v in targets if v["id"] in got]
    print(f"[2/3] 분석 {len(todo)}개 (병렬 {cfg.get('parallel_analyze', 2)}, 영상별 개별 호출)", flush=True)
    voc, today, n, stop, errs = vocab(con), D.today(), 0, False, []
    def one(v):
        if stop: return v, None, None
        try: return v, analyze(v, got[v["id"]], voc, today, cfg["model"]), None
        except Exception as ex: return v, None, ex
    with ThreadPoolExecutor(max(1, cfg.get("parallel_analyze", 2))) as ex:
        for v, res, err in ex.map(one, todo):
            if res is None and err is None: continue          # 한도로 건너뜀
            if err is not None:
                errs.append(f"[{v['id']}] {str(err)[:300]}"); mark_error(con, v, str(err))
                print(f"   오류 {v['id']}: {str(err)[:120]}", flush=True)
                if isinstance(err, UsageLimit) and not stop: stop = True; print("   사용량 한도 — 남은 분석은 다음 실행으로 미룹니다.", flush=True)
                continue
            store(con, v, got[v["id"]], res, cfg["model"]); n += 1
            print(f"[3/3] 저장 {v['owner']}/{v['id']} [{res['category']}/{res['subtag']}] 확인항목 {len(res['checks'])}개", flush=True)
    if errs: write_log(errs, "analyze-errors")
    return n

def retry_pending(con):
    """생방송 출신인데 스크립트가 없던 영상을 7일 뒤 1회 재시도. 그래도 없으면 포기(gave_up)."""
    rows = con.execute("SELECT id,url,title,wl_position,owner,playlist_name FROM videos WHERE transcript_status='pending_retry' AND transcript_retry_at<=?", (D.today(),)).fetchall()
    ts = [{"id": r["id"], "url": r["url"], "title": r["title"], "pos": r["wl_position"], "owner": r["owner"] or "cheoljoo", "playlist": r["playlist_name"]} for r in rows]
    if not ts: return
    print(f"[재시도] 생방송 스크립트 재확인 {len(ts)}개", flush=True)
    run_pipeline(con, ts, refresh=True)
    con.execute("UPDATE videos SET transcript_status='gave_up', transcript_retry_at=NULL WHERE transcript_status='pending_retry' AND transcript_attempts>=2 AND transcript_retry_at<=?", (D.today(),))
    con.commit()

def load_playlists():
    """config 의 모든 재생목록을 읽어 영상 목록(중복 제거: 먼저 나온 소유자 우선) 반환."""
    seen, out = set(), []
    for pl in cfg["playlists"]:
        vids = fetch_playlist(pl["url"], cfg.get("cookies", ""))
        print(f"재생목록 {pl['owner']}/{pl['name']}: {len(vids)}개", flush=True)
        for i, v in enumerate(vids):
            if v["id"] in seen: continue
            seen.add(v["id"]); out.append(dict(v, pos=i, owner=pl["owner"], playlist=pl["name"]))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--only"); ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--show-top", type=int, default=0); ap.add_argument("--no-indicators", action="store_true"); ap.add_argument("--indicators-only", action="store_true")
    a = ap.parse_args()
    con = D.connect()
    if a.indicators_only:
        indicators.update(con, cfg, force=True); autocheck.run(con, cfg); report.build_all(con); return
    vids = load_playlists()
    if a.show_top:
        for i, v in enumerate(vids[:a.show_top]): print(f"{i:3d} {v['id']} {v['owner']} [{v['channel']}] {v['title']}")
        return
    if a.only:
        targets = [v for v in vids if v["id"] == a.only] or [{"id": a.only, "title": a.only, "channel": None, "pos": -1, "owner": "cheoljoo", "playlist": None, "url": f"https://www.youtube.com/watch?v={a.only}"}]
    else:
        retry_pending(con)
        done = {r[0] for r in con.execute("SELECT id FROM videos WHERE status='done'")}
        targets = [v for v in vids if v["id"] not in done]
    if a.limit: targets = targets[:a.limit]
    print(f"전체 {len(vids)}개 중 대상 {len(targets)}개", flush=True)
    n = run_pipeline(con, targets, refresh=bool(a.only))
    print(f"이번 실행 처리 {n}개", flush=True)
    if not a.no_indicators: indicators.update(con, cfg); autocheck.run(con, cfg)
    if not a.no_report: report.build_all(con); print('JSON:', export_json.export(con), export_json.export(con, 'data/watchlater_full.json', True), flush=True)

if __name__ == "__main__":
    main()
