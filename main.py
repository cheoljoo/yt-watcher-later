"""WL -> 수집(info/댓글/자막) -> 분석 -> DB 저장 -> 일별 HTML 리포트.
사용:  uv run main.py [--limit N] [--only VIDEO_ID] [--show-top N] [--no-report]"""
import argparse, datetime, json, pathlib, tomllib, sys
import db as D
from fetch_list import fetch_playlist
from collect import collect, RateLimited
import time
from analyze import analyze
import report, export_json

cfg = tomllib.loads(pathlib.Path("config.toml").read_text(encoding="utf-8"))
DATA = pathlib.Path("data")
LIVE = {"is_live", "was_live", "is_upcoming", "post_live"}   # 생방송 출신: 자막이 며칠 뒤에 생길 수 있음
RETRY_DAYS = 1 * 7

def vocab(con):
    return [r[0] for r in con.execute("SELECT tag FROM tags GROUP BY tag ORDER BY count(*) DESC LIMIT 60")]

def store(con, v, pos, col, res, model):
    m, vid = col["meta"], v["id"]
    summary = "\n".join(f"- {p}" for p in res["summary_points"])
    mac = res.get("macro") or {}
    old = con.execute("SELECT first_seen_at, wl_position, transcript_attempts FROM videos WHERE id=?", (vid,)).fetchone()
    con.execute("""INSERT OR REPLACE INTO videos(id,url,title,channel,channel_id,channel_url,uploader_id,upload_date,
        duration_sec,view_count,like_count,comment_count,yt_categories,yt_tags,description,thumbnail,live_status,
        wl_position,first_seen_at,processed_at,processed_date,status,error,transcript_lang,model,
        category,subtag,extra_tags,one_liner,summary,keywords,comments_insight,macro_phase,macro_phase_reason,
        indicators_to_watch,analysis_json,watched_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
        (SELECT watched_at FROM videos WHERE id=?))""",
        (vid, v["url"], v["title"], m["channel"], m["channel_id"], m["channel_url"], m["uploader_id"], m["upload_date"],
         m["duration_sec"], m["view_count"], m["like_count"], m["comment_count"], m["yt_categories"], m["yt_tags"],
         m["description"], m["thumbnail"], m["live_status"],
         old["wl_position"] if old else pos, old["first_seen_at"] if old else D.now(), D.now(), D.today(),
         "done", None, col["lang"], model,
         res["category"], res["subtag"], json.dumps(res["extra_tags"], ensure_ascii=False), res["one_liner"], summary,
         json.dumps(res["keywords"], ensure_ascii=False), res["comments_insight"], mac.get("phase"), mac.get("phase_reason"),
         json.dumps(mac.get("indicators_to_watch", []), ensure_ascii=False), json.dumps(res, ensure_ascii=False), vid))
    att = ((old["transcript_attempts"] or 0) if old else 0) + 1
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

def retry_pending(con):
    """생방송 출신인데 스크립트가 없던 영상을 7일 뒤 1회 재시도. 그래도 없으면 포기(gave_up)."""
    rows = con.execute("SELECT id,url,title,wl_position FROM videos WHERE transcript_status='pending_retry' AND transcript_retry_at<=?", (D.today(),)).fetchall()
    for r in rows:
        vid = r["id"]; d = DATA / vid
        print(f"[재시도] {vid} {r['title']}", flush=True)
        try:
            for f in d.glob(f"{vid}.*.vtt"): f.unlink()
            (d / f"{vid}.info.json").unlink(missing_ok=True)
            col = collect(vid, cfg)
            if col["transcript"]:
                res = analyze(dict(r), col, vocab(con), D.today(), cfg["model"])
                store(con, dict(r), r["wl_position"], col, res, cfg["model"])
                print("   스크립트 확보 -> 재분석 완료", flush=True)
            else:
                con.execute("UPDATE videos SET transcript_status='gave_up', transcript_retry_at=NULL, transcript_attempts=2 WHERE id=?", (vid,)); con.commit()
                print("   여전히 스크립트 없음 -> 포기(gave_up)", flush=True)
        except RateLimited as e:
            print(f"   429 — 내일 다시 시도: {e}", flush=True); break
        except Exception as e:
            print(f"   오류(내일 다시 시도): {str(e)[:200]}", flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0); ap.add_argument("--only"); ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--show-top", type=int, default=0)
    a = ap.parse_args()
    con = D.connect()
    vids = fetch_playlist(cfg["playlist_url"], cfg.get("cookies", ""))
    if a.show_top:
        for i, v in enumerate(vids[:a.show_top]): print(f"{i:3d} {v['id']} [{v['channel']}] {v['title']}")
        return
    if a.only:
        targets = [(i, v) for i, v in enumerate(vids) if v["id"] == a.only] or [(-1, {"id": a.only, "title": a.only, "channel": None, "url": f"https://www.youtube.com/watch?v={a.only}"})]
    else:
        targets = list(enumerate(vids))
    if not a.only: retry_pending(con)
    print(f"재생목록 {len(vids)}개 중 대상 {len(targets)}개", flush=True)
    n = 0; rl = 0
    for pos, v in targets:
        r = con.execute("SELECT status FROM videos WHERE id=?", (v["id"],)).fetchone()
        if r and r["status"] == "done" and not a.only: continue
        if a.limit and n >= a.limit: break
        n += 1; print(f"[{n}] {v['id']} {v['title']}", flush=True)
        try:
            col = collect(v["id"], cfg)
            res = analyze(v, col, vocab(con), D.today(), cfg["model"])
            store(con, v, pos, col, res, cfg["model"])
            print(f"   완료 [{res['category']}/{res['subtag']}] 확인항목 {len(res['checks'])}개", flush=True)
            rl = 0; time.sleep(cfg.get("sleep_between_videos", 5))
        except Exception as e:
            msg = str(e)
            con.execute("INSERT OR REPLACE INTO videos(id,url,title,status,error,first_seen_at,wl_position) VALUES(?,?,?,?,?,?,?)",
                        (v["id"], v["url"], v["title"], "error", msg[:500], D.now(), pos)); con.commit()
            print(f"   오류: {msg[:200]}", flush=True)
            rl = rl + 1 if isinstance(e, RateLimited) or "429" in msg else 0
            if rl >= 3: print("YouTube 429가 연속 발생해 중단합니다. 잠시(수십 분) 후 다시 실행하세요.", flush=True); break
            if "usage limit" in msg.lower() or "rate limit" in msg.lower(): print("사용량 한도로 보여 중단합니다.", flush=True); break
    print(f"이번 실행 처리 {n}개", flush=True)
    if not a.no_report: report.build_all(con); print('JSON:', export_json.export(con), export_json.export(con, 'data/watchlater_full.json', True), flush=True)

if __name__ == "__main__":
    main()
