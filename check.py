"""확인 항목 관리.
  uv run check.py list [--due]                      # 대기 중인 확인 항목(--due: 확인일 도래분)
  uv run check.py set ID --status confirmed|refuted|partial|unknown --result "..." --opinion "..." --reason "..."
  uv run check.py add --target "알파벳A(GOOGL) 주가" --what "..." --expect "..." --date 2026-12-31 [--kind stock] [--why "근거"]
  uv run check.py watched VIDEO_ID [YYYY-MM-DD]     # 본 날짜 기록"""
import argparse, db as D
ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
l = sub.add_parser("list"); l.add_argument("--due", action="store_true")
s = sub.add_parser("set"); s.add_argument("id", type=int); s.add_argument("--status", required=True, choices=["confirmed","refuted","partial","unknown"])
for f in ("result", "opinion", "reason"): s.add_argument(f"--{f}", default="")
ad = sub.add_parser("add")
ad.add_argument("--target", required=True); ad.add_argument("--what", required=True); ad.add_argument("--expect", required=True)
ad.add_argument("--date", required=True); ad.add_argument("--kind", default="stock", choices=["indicator", "stock", "event"]); ad.add_argument("--why", default="")
w = sub.add_parser("watched"); w.add_argument("video_id"); w.add_argument("date", nargs="?")
a = ap.parse_args(); con = D.connect()
if a.cmd == "list":
    q = "SELECT c.*, v.title FROM checks c LEFT JOIN videos v ON v.id=c.video_id WHERE c.status='pending'" + (" AND c.check_date<=?" if a.due else "") + " ORDER BY c.check_date"
    for r in con.execute(q, (D.today(),) if a.due else ()):
        print(f"#{r['id']} {r['check_date']} [{r['kind']}] {r['target']} — {r['what_to_check']}\n     예상: {r['expectation']}  (영상: {(r['title'] or '직접 등록')[:40]})")
elif a.cmd == "set":
    con.execute("UPDATE checks SET status=?, checked_at=?, result=?, opinion=?, reason=? WHERE id=?", (a.status, D.today(), a.result, a.opinion, a.reason, a.id)); con.commit(); print("기록 완료")
elif a.cmd == "add":
    cur = con.execute("INSERT INTO checks(video_id,kind,target,what_to_check,expectation,check_date,rationale,created_at) VALUES(NULL,?,?,?,?,?,?,?)",
                      (a.kind, a.target, a.what, a.expect, a.date, a.why, D.now())); con.commit(); print(f"등록 완료 #{cur.lastrowid}")
else:
    con.execute("UPDATE videos SET watched_at=? WHERE id=?", (a.date or D.today(), a.video_id)); con.commit(); print("기록 완료")
