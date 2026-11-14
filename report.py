"""처리 날짜별 HTML 리포트 생성 (reports/YYYY-MM-DD.html, reports/index.html)."""
import json, pathlib, html
import db as D
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
main{counter-reset:vc}section.vc>h3::before{counter-increment:vc;content:"#" counter(vc) "  ";color:var(--ac);font-weight:700}table.num{counter-reset:n}table.num tr+tr>td:first-child::before{counter-increment:n;content:counter(n) ". ";font-weight:700;color:var(--ac)}ul{margin:4px 0;padding-left:20px}.cat-h{font-size:19px;margin:34px 0 4px;padding-bottom:4px;border-bottom:2px solid var(--ac);color:var(--fg)}.sub-h{font-size:15px;margin:20px 0 -4px;color:var(--ac)}.due{border-left:4px solid #d9822b}.st-pending{color:#b86e00}.st-confirmed{color:#1a8a4a}.st-refuted{color:#c0392b}"""

def L(s):
    try: return json.loads(s) if s else []
    except Exception: return []

def page(title, body, icon="▶️"):
    return f"<!doctype html><html lang=ko><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)}</title><link rel=icon type=image/svg+xml href='{favicon(icon)}'><style>{CSS}</style><main><div class=meta style='text-align:right'>🕒 만든 시각 {D.now().replace('T', ' ')}</div>{body}</main></html>"

def dur(s): return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}" if s and s >= 3600 else (f"{s//60}:{s%60:02d}" if s else "-")
def num(n): return f"{n:,}" if isinstance(n, int) else "-"

def checks_table(rows, with_video=False):
    if not rows: return ""
    h = "<table class=num><tr><th>📅 확인일<th>🎯 대상<th>🔎 확인할 것 / 영상의 예상<th>상태·결과</tr>"
    for c in rows:
        res = f"<span class=st-{c['status']}>{ST_ICON.get(c['status'], '')} {e(c['status'])}</span>"
        if c["checked_at"]: res += f" ({e(c['checked_at'])})<br>{e(c['result'] or '')}{('<br><span class=meta>📈 업로드→확인일 변화: ' + e(c['since_upload']) + '</span>') if c['since_upload'] else ''}<br><i>{e(c['opinion'] or '')}</i> {e(c['reason'] or '')}"
        vid = f"<br><span class=meta>{e((c['title'] or '')[:40])}</span>" if with_video else ""
        h += f"<tr><td>{e(c['check_date'])}<td>{KIND_ICON.get(c['kind'], '')} {e(c['target'])}{vid}<td>{e(c['what_to_check'])}<br><span class=meta>예상: {e(c['expectation'])}</span>{('<br><span class=meta>🟢 맞을 때: ' + e(c['if_right']) + '</span>') if c['if_right'] else ''}{('<br><span class=meta>🔴 틀릴 때: ' + e(c['if_wrong']) + '</span>') if c['if_wrong'] else ''}<td>{res}</tr>"
    return h + "</table>"

def other_runs(con, v):
    """같은 영상을 다른 도구·모델이 분석한 결과(있으면)를 접어서 나란히 보여준다."""
    main = (v["engine"] or "claude", v["model"] or "")
    rows = con.execute("SELECT * FROM analysis_runs WHERE video_id=? ORDER BY run_at DESC", (v["id"],)).fetchall()
    seen, out = {main}, ""
    for r in rows:
        key = (r["engine"], r["model"])
        if key in seen: continue
        seen.add(key)
        res = json.loads(r["analysis_json"])
        pts = "".join(f"<li>{e(x)}</li>" for x in res.get("summary_points", []))
        diff = "" if (r["category"], r["subtag"]) == (v["category"], v["subtag"]) else " <b>(분류가 다름)</b>"
        out += (f"<details><summary>🤖 다른 분석: {e(r['engine'])} · {e(r['model'])} — {e(r['category'])}/{e(r['subtag'])}{diff} · 확인항목 {r['n_checks']}개 · 링크 {r['n_links']}개</summary>"
                f"<p><b>{e(r['one_liner'] or '')}</b></p><ul>{pts}</ul><p class=meta>{e(r['source'] or '')} · {e(r['run_at'])}</p></details>")
    return out

def card(con, v):
    vid = v["id"]
    tags = [r["tag"] for r in con.execute("SELECT tag FROM tags WHERE video_id=? AND level=3", (vid,))]
    ppl = con.execute("SELECT name,role FROM people WHERE video_id=?", (vid,)).fetchall()
    lks = con.execute("SELECT url,kind,context FROM links WHERE video_id=?", (vid,)).fetchall()
    chk = con.execute("SELECT * FROM checks WHERE video_id=? ORDER BY check_date", (vid,)).fetchall()
    h = f"<section class='card vc' id='v-{vid}'><h3><a href='{e(v['url'])}'>{e(v['title'])}</a></h3>"
    h += f"<div class=meta>👤 {e(v['owner'] or '-')} 님이 저장 · 📺 <a href='{e(v['channel_url'] or '#')}'>{e(v['channel'] or '')}</a> · 업로드 {e(v['upload_date'] or '-')} · {dur(v['duration_sec'])} · 조회 {num(v['view_count'])} · 👍 {num(v['like_count'])} · 댓글 {num(v['comment_count'])}"
    h += f" · 본 날짜 {e(v['watched_at'] or '미기록')}"
    h += f" · 🤖 {e(v['engine'] or 'claude')} · {e(v['model'] or '-')}</div>"
    for d in con.execute("SELECT owner,playlist_name,seen_at FROM dup_seen WHERE video_id=?", (vid,)):
        h += f"<div class=meta>♻️ {e(d['owner'])} 님의 {e(d['playlist_name'] or '')} 에도 저장됨 (발견 {e((d['seen_at'] or '')[:10])}) — 이미 분석해서 다시 하지 않았습니다</div>"
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
    h += other_runs(con, v)
    if ppl: h += "<h2>🧑 등장 인물</h2><ul>" + "".join(f"<li>{e(p['name'])} <span class=meta>{e(p['role'])}</span></li>" for p in ppl) + "</ul>"
    if lks: h += "<h2>🔗 언급된 소스/링크</h2><ul>" + "".join(f"<li>[{e(l['kind'])}] <a href='{e(l['url'])}'>{e(l['url'])}</a> <span class=meta>{e(l['context'])}</span></li>" for l in lks) + "</ul>"
    les = L(v["lessons"])
    if les: h += "<h2>🎓 이 영상에서 배울 점</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in les) + "</ul>"
    biz = L(v["business"])
    if biz:
        icon = {"가능": "💰", "조건부": "🟡", "어려움": "⚪"}.get(biz.get("possible"), "💰")
        h += f"<h2>{icon} 돈 버는 사업이 될 수 있나</h2><p><b>{e(biz.get('possible', ''))}</b> — {e(biz.get('idea', ''))}</p><p><b>어떻게</b> {e(biz.get('how', ''))}</p>"
    if v["comments_insight"] and v["comments_insight"] != "없음": h += f"<h2>💬 댓글에서 의미 있는 내용</h2><p>{e(v['comments_insight'])}</p>"
    import opinions
    return h + opinions.box(con, vid) + "</section>"

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

def backlog_block(con):
    rows = con.execute("SELECT b.* FROM backlog b WHERE b.video_id NOT IN (SELECT id FROM videos WHERE status='done') ORDER BY b.pos").fetchall()
    if not rows: return "<p class=meta>⏳ 분석 대기 영상 0개 — 모두 처리됨</p>"
    import tomllib; mx = tomllib.loads(open("config.toml", encoding="utf-8").read()).get("max_analyze", 30)
    items = "".join(f"<li>👤 {e(r['owner'] or '-')} · {e(r['title'] or r['video_id'])}</li>" for r in rows[:100])
    more = f"<li>… 외 {len(rows) - 100}개</li>" if len(rows) > 100 else ""
    return (f"<section class='card due'><h3>⏳ 아직 분석되지 않은 영상 {len(rows)}개</h3>"
            f"<p class=meta>한 번 실행할 때 Claude 분석은 최대 {mx}개까지입니다. 남은 영상은 다음 실행(매일 새벽 1시)에서 재생목록 앞쪽부터 이어서 처리합니다.</p>"
            f"<details><summary>목록 보기</summary><ul>{items}{more}</ul></details></section>")

def build_day(con, day):
    vs = con.execute("SELECT * FROM videos WHERE COALESCE(run_id,processed_date)=? AND status='done'", (day,)).fetchall()
    due = con.execute("SELECT c.*, v.title FROM checks c LEFT JOIN videos v ON v.id=c.video_id WHERE c.status='pending' AND c.check_date<=? ORDER BY c.check_date", (day,)).fetchall()
    g = grouped(vs)
    body = f"<h1>🗓️ {e(day)} 처리 리포트</h1><p class=meta>영상 {len(vs)}개 · 카테고리별 → 비슷한 주제(2단계 태그)별 → 업로드일 오래된 순 · <a href='index.html'>🏠 홈</a></p>"
    import report_extra
    body += report_extra.macro_block(con, day[:10])
    if day[:10] == D.today(): body += backlog_block(con)
    toc = "".join(f"<a class=chip href='#c{i}'>{CAT_ICON.get(c, '📌')} {e(c)} {sum(len(x) for _, x in subs)}</a>" for i, (c, subs) in enumerate(g))
    body += f"<p>{toc}</p>"
    if due: body += "<section class='card due'><h3>⏰ 확인 시점이 도래한 항목</h3>" + checks_table(due, True) + "</section>"
    for i, (c, subs) in enumerate(g):
        body += f"<h2 class=cat-h id='c{i}'>{CAT_ICON.get(c, '📌')} {e(c)} <span class=meta>({sum(len(x) for _, x in subs)})</span></h2>"
        for t, items in subs:
            body += f"<h3 class=sub-h>{e(t)} <span class=meta>({len(items)}) · {e(items[0]['upload_date'] or '-')} ~ {e(items[-1]['upload_date'] or '-')}</span></h3>"
            body += "".join(card(con, v) for v in items)
    import opinions
    (OUT / f"{day}.html").write_text(page(f"{day} 리포트", opinions.OP_CSS + body + opinions.OP_JS, "🗓️"), encoding="utf-8")


FLOW_CSS = """<style>
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:6px;margin:8px 0}
.flow .st{flex:1 1 150px;border:1px solid var(--bd);border-radius:10px;padding:8px 10px;background:var(--chip);font-size:13px}
.flow .st b{display:block;margin-bottom:2px}.flow .st small{color:var(--mu)}
.flow .ar{align-self:center;color:var(--mu);font-size:18px}
.smap{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin:8px 0}
.smap a.n{display:block;border:1px solid var(--bd);border-radius:10px;padding:8px 10px;text-decoration:none;font-size:13px}
.smap a.n b{display:block;color:var(--ac)}.smap a.n small{color:var(--mu)}
</style>"""

def how_block():
    st = [("1️⃣ 수집","재생목록 → yt-dlp<br><small>자막·메타·댓글 (fetch_list, collect, fetcher)</small>"),
          ("2️⃣ 분석","Claude/agy 가 JSON 생성<br><small>요약·분류·배울 점·사업성·확인 항목 (work.py, analyze.py)</small>"),
          ("3️⃣ 저장","SQLite data/watchlater.db<br><small>이미 분석한 영상은 다시 안 함 (db.py, main.py)</small>"),
          ("4️⃣ 보강","지표 설명·시세·의미 해설·매크로 위치·확인 판정<br><small>(indicators.py, autocheck.py)</small>"),
          ("5️⃣ 리포트","DB만 읽어 HTML/JSON 생성<br><small>(report.py, report_extra.py, stats.py, highlight.py)</small>"),
          ("6️⃣ 공개","reports/ → nginx<br><small>psncs.iptime.org/yt_watch_later/</small>")]
    flow = '<span class=ar>›</span>'.join(f"<div class=st><b>{a}</b>{b}</div>" for a, b in st)
    pages = [("index.html","🏠 index (지금 이 화면)","실행(날짜_시분-LLM)별 리포트 목록"),
             ("#runs","🗓️ 실행별 리포트","카테고리 → 주제 → 영상 카드 (아래 처리 목록에서 선택)"),
             ("checks_pending.html","⏳ 앞으로 확인할 것","확인 예정 항목(예상이 맞을 때/틀릴 때 포함)"),
             ("checks_done.html","✅ 확인한 것","판정 결과"),
             ("indicators.html","📊 지표","설명·시세·의미·매크로 (AI 표기)"),
             ("indicator_trends.html","📉 지표 추이","날짜별 그래프·중요한 날·상황 설명"),
             ("stats.html","📈 시청 성향","많이 보는 채널·인물"),
             ("stats_channels.html","📺 모든 채널","stats 에서 연결"),
             ("opinions.html","💬 나와 AI 의견","내가 남긴 의견과 AI 의견"),
             ("highlights.html","⭐ 인상 깊은 영상","왼쪽 목록·오른쪽 상세"),
             ("browse.html","🗂️ 날짜·주제별 보기","업로드일 최신순, 주제·기간·페이지 크기 선택"),
             ("watchlater.json","🧾 전체 데이터","JSON")]
    smap = "".join(f"<a class=n href='{u}'><b>{t}</b><small>{d}</small></a>" for u, t, d in pages)
    return (FLOW_CSS + "<details open class=card><summary><b>🔧 이 페이지는 어떻게 만들어지나</b></summary>"
            "<p class=meta>매일 01:00 cron → run_skill.sh --agy (flock 으로 중복 실행 방지). 수집·DB·리포트는 코드가 하고, LLM 은 JSON 만 만든다. 모든 페이지는 실행 끝에 코드가 다시 만든다.</p>"
            f"<div class=flow>{flow}</div>"
            "<p class=meta><b>🗺️ 사이트 맵</b></p>" f"<div class=smap>{smap}</div></details>")

def build_all(con):
    OUT.mkdir(exist_ok=True)
    days = [r[0] for r in con.execute("SELECT DISTINCT COALESCE(run_id,processed_date) k FROM videos WHERE status='done' AND processed_date IS NOT NULL ORDER BY 1 DESC")]
    for d in days: build_day(con, d)
    rows = ""
    for d in days:
        n, cats = con.execute("SELECT count(*), group_concat(DISTINCT category) FROM videos WHERE COALESCE(run_id,processed_date)=? AND status='done'", (d,)).fetchone()
        who = ", ".join(r[0] or "-" for r in con.execute("SELECT DISTINCT owner FROM videos WHERE COALESCE(run_id,processed_date)=? AND status='done'", (d,)))
        rows += f"<tr><td><a href='{d}.html'>{d}</a><td>{n}<td>👤 {e(who)}<td>{' '.join(CAT_ICON.get(x, '📌') + e(x) for x in (cats or '').split(','))}</tr>"
    pend = con.execute("SELECT count(*) FROM checks WHERE status='pending'").fetchone()[0]
    last = con.execute("SELECT max(checked_at) FROM checks WHERE checked_at IS NOT NULL").fetchone()[0]
    yday = con.execute("SELECT c.*, v.title FROM checks c LEFT JOIN videos v ON v.id=c.video_id WHERE c.checked_at=? ORDER BY c.check_date, c.id", (last,)).fetchall() if last else []
    late = con.execute("SELECT c.*, v.title FROM checks c LEFT JOIN videos v ON v.id=c.video_id WHERE c.status='pending' AND c.check_date<? ORDER BY c.check_date", (D.today(),)).fetchall()
    body = f"<h1>▶️ YouTube 나중에 볼 동영상 리포트</h1><p class=meta>미확인 항목 {pend}개 · <a href='checks_pending.html'>⏳ 앞으로 확인할 것</a> · <a href='checks_done.html'>✅ 확인한 것</a> · <a href='indicators.html'>📊 지표</a> · <a href='indicator_trends.html'>📉 지표 추이</a> · <a href='stats.html'>📈 시청 성향</a> · <a href='highlights.html'>⭐ 인상 깊은 영상</a> · <a href='browse.html'>🗂️ 날짜·주제별 보기</a> · <a href='opinions.html'>💬 나와 AI 의견</a> · <a href='watchlater.json'>전체 데이터(JSON)</a> · <a href='/'>홈</a></p>"
    body += how_block()
    body += backlog_block(con)
    if yday: body += f"<section class=card><h3>✅ 어제 확인한 항목 ({len(yday)})</h3><p class=meta>확인일이 어제까지인 항목을 {e(last[:10])} 새벽 실행에서 AI가 판정한 결과입니다. 오늘 날짜 항목은 내일 새벽에 확인합니다.</p>" + checks_table(yday, True) + "</section>"
    if late: body += f"<section class='card due'><h3>🟠 확인일이 지났지만 아직 확인 못 한 항목 ({len(late)})</h3><p class=meta>사용량 한도 등으로 못 한 것은 다음 실행에서 이어서 확인합니다.</p>" + checks_table(late, True) + "</section>"
    body += f"<table id=runs><tr><th>🗓️ 처리(날짜_시분-LLM)<th>영상 수<th>저장한 사람<th>카테고리</tr>{rows}</table>"
    (OUT / "index.html").write_text(page("WL 리포트", body), encoding="utf-8")
    import report_extra; report_extra.build(con)
    import stats; stats.build(con)
    import indicator_trends; indicator_trends.build(con)
    import highlight; highlight.build(con)
    import browse; browse.build(con)
    import opinions; opinions.build(con)
    print(f"리포트 생성: {OUT.resolve()}/index.html ({len(days)}일)", flush=True)
