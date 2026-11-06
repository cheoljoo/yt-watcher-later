"""DB -> 사람이 읽기 좋은 JSON.
  uv run export_json.py            # reports/watchlater.json   (웹 공개용, 스크립트 원문 제외)
  uv run export_json.py --full     # data/watchlater_full.json (스크립트 원문 포함, 웹에 노출되지 않는 경로)"""
import json, sys, pathlib
import db as D

JSON_COLS = ("yt_categories", "yt_tags", "extra_tags", "keywords", "indicators_to_watch")

def export(con, out="reports/watchlater.json", with_transcript=False):
    videos = []
    for r in con.execute("SELECT * FROM videos ORDER BY processed_date DESC, wl_position"):
        v = dict(r)
        if not with_transcript: v.pop("transcript", None)
        v.pop("analysis_json", None)                       # 중복 원본은 제외(필드로 모두 풀려 있음)
        for c in JSON_COLS:
            try: v[c] = json.loads(v[c]) if v.get(c) else []
            except Exception: pass
        v["summary_points"] = [l[2:] for l in (v.pop("summary", "") or "").splitlines() if l.startswith("- ")]
        q = lambda sql: [dict(x) for x in con.execute(sql, (v["id"],))]
        v["people"] = q("SELECT name, role FROM people WHERE video_id=?")
        v["links"] = q("SELECT url, kind, context FROM links WHERE video_id=?")
        v["tags"] = {"category": v.get("category"), "subtag": v.get("subtag"), "extra": v.get("extra_tags")}
        v["checks"] = q("SELECT id, kind, target, what_to_check, expectation, check_date, status, checked_at, result, opinion, reason FROM checks WHERE video_id=? ORDER BY check_date")
        videos.append({k: val for k, val in v.items() if val not in (None, "", [])})
    doc = {"generated_at": D.now(), "video_count": len(videos), "videos": videos}
    p = pathlib.Path(out); p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p

if __name__ == "__main__":
    full = "--full" in sys.argv; args = [a for a in sys.argv[1:] if a != "--full"]
    print(export(D.connect(), *(args[:1] or ["data/watchlater_full.json" if full else "reports/watchlater.json"]), with_transcript=full))
