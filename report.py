"""처리 날짜별 HTML 리포트 생성 (reports/YYYY-MM-DD.html, reports/index.html)."""
import json, pathlib, html
from html import escape as e

OUT = pathlib.Path("reports")
CAT_ICON = {"경제": "📈", "AI": "🤖", "IT": "💻", "정치·사회": "🏛️", "과학·건강": "🔬", "기타": "📌"}
KIND_ICON = {"indicator": "📊", "stock": "💹", "event": "📅"}
ST_ICON = {"pending": "⏳", "confirmed": "✅", "refuted": "❌", "partial": "➗", "unknown": "❔"}
def favicon(emoji):
    """이모지를 SVG 파비콘(data URI)으로. 따옴표까지 모두 퍼센트 인코딩해 속성이 깨지지 않게 한다."""
    import urllib.parse
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><text y='52' font-size='52'>{emoji}</text></svg>"
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")
CSS = """:root{--bg:#fafaf8;--fg:#1c1c1a;--mu:#6b6b66;--card:#fff;--bd:#e3e2dc;--ac:#2b5fd9;--chip:#eef1fa}
@media(prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mu:#9a9990;--card:#1f1f1c;--bd:#33332f;--ac:#7ea2f5;--chip:#262b3a}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,'Noto Sans KR',sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px}h2{font-size:15px;margin:18px 0 6px;color:var(--mu)}
a{color:var(--ac)}.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:16px 18px;margin:16px 0}
.card h3{margin:0 0 4px;font-size:17px}.meta{color:var(--mu);font-size:13px}.chip{display:inline-block;background:var(--chip);border-radius:99px;padding:1px 10px;margin:2px 4px 2px 0;font-size:12.5px}
.chip.cat{font-weight:600}table{border-collapse:collapse;width:100%;font-size:13.5px}td,th{border-top:1px solid var(--bd);padding:5px 8px;text-align:left;vertical-align:top}
ul{margin:4px 0;padding-left:20px}.cat-h{font-size:19px;margin:34px 0 4px;padding-bottom:4px;border-bottom:2px solid var(--ac);color:var(--fg)}.sub-h{font-size:15px;margin:20px 0 -4px;color:var(--ac)}.due{border-left:4px solid #d9822b}.st-pending{color:#b86e00}.st-confirmed{color:#1a8a4a}.st-refuted{color:#c0392b}"""

def L(s):
    try: return json.loads(s) if s else []
    except Exception: return []

def page(title, body, icon="▶️"):
    return f"<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)}</title><link rel=icon type=image/svg+xml href='{favicon(icon)}'><style>{CSS}</style><main>{body}</main></html>"

def dur(s): return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}" if s and s >= 3600 else (f"{s//60}:{s%60:02d}" if s else "-")
def num(n): return f"{n:,}" if isinstance(n, int) else "-"

def checks_table(rows, with_video=False):
    if not rows: return ""
    h = "<table><tr><th>📅 확인일<th>🎯 대상<th>🔎 확인할 것 / 영상의 예상<th>상태·결과</tr>"
    for c in rows:
        res = f"<span class=st-{c['status']}>{ST_ICON.get(c['status'], '')} {e(c['status'])}</span>"
        if c["checked_at"]: res += f" ({e(c['checked_at'])})<br>{e(c['result'] or '')}<br><i>{e(c['opinion'] or '')}</i> {e(c['reason'] or '')}"
        vid = f"<br><span class=meta>{e((c['title'] or '')[:40])}</span>" if with_video else ""
        h += f"<tr><td>{e(c['check_date'])}<td>{KIND_ICON.get(c['kind'], '')} {e(c['target'])}{vid}<td>{e(c['what_to_check'])}<br><span class=meta>예상: {e(c['expectation'])}</span><td>{res}</tr>"
    return h + "</table>"

def card(con, v):
    vid = v["id"]
    tags = [r["tag"] for r in con.execute("SELECT tag FROM tags WHERE video_id=? AND level=3", (vid,))]
    ppl = con.execute("SELECT name,role FROM people WHERE video_id=?", (vid,)).fetchall()
    lks = con.execute("SELECT url,kind,context FROM links WHERE video_id=?", (vid,)).fetchall()
    chk = con.execute("SELECT * FROM checks WHERE video_id=? ORDER BY check_date", (vid,)).fetchall()
    h = f"<section class=card id='v-{vid}'><h3><a href='{e(v['url'])}'>{e(v['title'])}</a></h3>"
    h += f"<div class=meta>👤 {e(v['owner'] or '-')} 님이 저장 · 📺 <a href='{e(v['channel_url'] or '#')}'>{e(v['channel'] or '')}</a> · 업로드 {e(v['upload_date'] or '-')} · {dur(v['duration_sec'])} · 조회 {num(v['view_count'])} · 👍 {num(v['like_count'])} · 댓글 {num(v['comment_count'])}"
    h += f" · 본 날짜 {e(v['watched_at'] or '미기록')}</div>"
    ts = v["transcript_status"]
    if ts == "pending_retry": h += f"<div class=meta>⚠ 스크립트 없음(생방송) — {e(v['transcript_retry_at'])} 재시도 예정. 현재 분석은 제목·설명·댓글 기반</div>"
    elif ts == "gave_up": h += "<div class=meta>⚠ 스크립트 확보 실패(재시도 후 포기). 분석은 제목·설명·댓글 기반</div>"
    elif ts == "none": h += "<div class=meta>⚠ 스크립트 없음. 분석은 제목·설명·댓글 기반</div>"
    h += f"<div><span class='chip cat'>{CAT_ICON.get(v['category'], '📌')} {e(v['category'])}</span><span class=chip>{e(v['subtag'])}</span>" + "".join(f"<span class=chip>{e(t)}</span>" for t in tags) + "</div>"
    h += f"<p><b>{e(v['one_liner'])}</b></p>" + "<ul>" + "".join(f"<li>{e(l[2:])}</li>" for l in v["summary"].splitlines() if l.startswith("- ")) + "</ul>"
    if v["macro_phase"]:
        h += f"<h2>🧭 매크로 국면</h2><p><b>{e(v['macro_phase'])}</b><br><span class=meta>{e(v['macro_phase_reason'] or '')}</span></p>"
        ind = L(v["indicators_to_watch"])
        if ind: h += "<h2>📊 봐야 할 지표</h2><ul>" + "".join(f"<li><b>{e(i['name'])}</b> — {e(i['why'])}</li>" for i in ind) + "</ul>"
    if chk: h += "<h2>⏳ 나중에 확인할 것</h2>" + checks_table(chk)
    if ppl: h += "<h2>🧑 등장 인물</h2><ul>" + "".join(f"<li>{e(p['name'])} <span class=meta>{e(p['role'])}</span></li>" for p in ppl) + "</ul>"
    if lks: h += "<h2>🔗 언급된 소스/링크</h2><ul>" + "".join(f"<li>[{e(l['kind'])}] <a href='{e(l['url'])}'>{e(l['url'])}</a> <span class=meta>{e(l['context'])}</span></li>" for l in lks) + "</ul>"
    if v["comments_insight"] and v["comments_insight"] != "없음": h += f"<h2>💬 댓글에서 의미 있는 내용</h2><p>{e(v['comments_insight'])}</p>"
    return h + "</section>"

CAT_ORDER = ["경제", "AI", "IT", "정치·사회", "과학·건강", "기타"]

def vkey(v):                                   # 오래된 것 -> 최신 (YouTube 업로드일, 같으면 처리 순서)
    return (v["upload_date"] or "9999-99-99", v["processed_at"] or "")

def grouped(vs):
    """카테고리 -> 서브태그(비슷한 것끼리) -> 날짜 오름차순.  서브태그 묶음도 가장 오래된 영상 순."""
    cats = {}
    for v in vs: cats.setdefault(v["category"] or "기타", {}).setdefault(v["subtag"] or "기타", []).append(v)
    order = sorted(cats, key=lambda c: CAT_ORDER.index(c) if c in CAT_ORDER else len(CAT_ORDER))
    return [(c, [(t, sorted(items, key=vkey)) for t, items in
                 sorted(cats[c].items(), key=lambda kv: min(vkey(x) for x in kv[1]))]) for c in order]

def build_day(con, day):
    vs = con.execute("SELECT * FROM videos WHERE processed_date=? AND status='done'", (day,)).fetchall()
    due = con.execute("SELECT c.*, v.title FROM checks c JOIN videos v ON v.id=c.video_id WHERE c.status='pending' AND c.check_date<=? ORDER BY c.check_date", (day,)).fetchall()
    g = grouped(vs)
    body = f"<h1>🗓️ {e(day)} 처리 리포트</h1><p class=meta>영상 {len(vs)}개 · 카테고리별 → 비슷한 주제(2단계 태그)별 → 업로드일 오래된 순 · <a href='index.html'>전체 목록</a></p>"
    import report_extra
    body += report_extra.macro_block(con, day)
    toc = "".join(f"<a class=chip href='#c{i}'>{CAT_ICON.get(c, '📌')} {e(c)} {sum(len(x) for _, x in subs)}</a>" for i, (c, subs) in enumerate(g))
    body += f"<p>{toc}</p>"
    if due: body += "<section class='card due'><h3>⏰ 확인 시점이 도래한 항목</h3>" + checks_table(due, True) + "</section>"
    for i, (c, subs) in enumerate(g):
        body += f"<h2 class=cat-h id='c{i}'>{CAT_ICON.get(c, '📌')} {e(c)} <span class=meta>({sum(len(x) for _, x in subs)})</span></h2>"
        for t, items in subs:
            body += f"<h3 class=sub-h>{e(t)} <span class=meta>({len(items)}) · {e(items[0]['upload_date'] or '-')} ~ {e(items[-1]['upload_date'] or '-')}</span></h3>"
            body += "".join(card(con, v) for v in items)
    (OUT / f"{day}.html").write_text(page(f"{day} 리포트", body, "🗓️"), encoding="utf-8")

def build_all(con):
    OUT.mkdir(exist_ok=True)
    days = [r[0] for r in con.execute("SELECT DISTINCT processed_date FROM videos WHERE status='done' AND processed_date IS NOT NULL ORDER BY 1 DESC")]
    for d in days: build_day(con, d)
    rows = ""
    for d in days:
        n, cats = con.execute("SELECT count(*), group_concat(DISTINCT category) FROM videos WHERE processed_date=? AND status='done'", (d,)).fetchone()
        who = ", ".join(r[0] or "-" for r in con.execute("SELECT DISTINCT owner FROM videos WHERE processed_date=? AND status='done'", (d,)))
        rows += f"<tr><td><a href='{d}.html'>{d}</a><td>{n}<td>👤 {e(who)}<td>{' '.join(CAT_ICON.get(x, '📌') + e(x) for x in (cats or '').split(','))}</tr>"
    pend = con.execute("SELECT count(*) FROM checks WHERE status='pending'").fetchone()[0]
    due = con.execute("SELECT c.*, v.title FROM checks c JOIN videos v ON v.id=c.video_id WHERE c.status='pending' AND c.check_date<=date('now','localtime') ORDER BY c.check_date").fetchall()
    body = f"<h1>▶️ YouTube 나중에 볼 동영상 리포트</h1><p class=meta>미확인 항목 {pend}개 · <a href='checks_pending.html'>⏳ 앞으로 확인할 것</a> · <a href='checks_done.html'>✅ 확인한 것</a> · <a href='indicators.html'>📊 지표</a> · <a href='watchlater.json'>전체 데이터(JSON)</a> · <a href='/'>홈</a></p>"
    if due: body += "<section class='card due'><h3>⏰ 지금 확인해야 할 항목</h3>" + checks_table(due, True) + "</section>"
    body += f"<table><tr><th>🗓️ 처리일<th>영상 수<th>저장한 사람<th>카테고리</tr>{rows}</table>"
    (OUT / "index.html").write_text(page("WL 리포트", body), encoding="utf-8")
    import report_extra; report_extra.build(con)
    print(f"리포트 생성: {OUT.resolve()}/index.html ({len(days)}일)", flush=True)
