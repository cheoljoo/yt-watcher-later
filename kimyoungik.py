"""김영익 교수 투자 방식 정리 페이지 (reports/kimyoungik.html).

조사 내용(규칙·국면별 비중·점검 지표)은 DB research 표, '지금 상태'는 indicator_values 표에서 읽어 만든다(웹 호출 없음).
교재·영상 요약은 kimyoungik_data.py.

  uv run kimyoungik.py import    # kimyoungik_data.py 의 조사 내용을 DB 에 저장
  uv run kimyoungik.py build     # reports/kimyoungik.html 만들기 (report.build_all 도 호출)
"""
import json, sys
from html import escape as e
import db as D

SLUG = "kimyoungik"
DDL = """CREATE TABLE IF NOT EXISTS research(slug TEXT PRIMARY KEY, title TEXT, data_json TEXT, updated_at TEXT);"""
KEYS = ("CHANNEL", "SUMMARY", "RULES", "PHASES", "ALLOC", "CHECKLIST", "FAIR", "SIGNALS", "AVOID", "SCENARIOS", "HOWTO", "CAUTIONS", "SOURCES")


def con_():
    con = D.connect(); con.executescript(DDL); return con


def do_import(con):
    import kimyoungik_data as S
    data = {k: getattr(S, k) for k in KEYS}
    con.execute("INSERT OR REPLACE INTO research VALUES(?,?,?,?)", (SLUG, "김영익 교수 투자 방식", json.dumps(data, ensure_ascii=False), D.now()))
    con.commit(); print("research 저장:", {k: len(v) for k, v in data.items() if hasattr(v, "__len__")})


def latest(con, sym, asof=None):
    """(source, symbol) 지표의 최근 값 (date, value). asof 가 있으면 그 날짜 이전 마지막 값."""
    if not sym: return None
    q = ("SELECT v.date, v.value FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id "
         "WHERE i.source=? AND i.symbol=? AND i.active=1" + (" AND v.date<=?" if asof else "") + " ORDER BY v.date DESC LIMIT 1")
    r = con.execute(q, (sym[0], sym[1]) + ((asof,) if asof else ())).fetchone()
    return (r[0], r[1]) if r else None


def build(con=None):
    import report as R
    con = con or con_()
    row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    if not row:
        do_import(con); row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    d = json.loads(row["data_json"])
    src = {s["id"]: s for s in d["SOURCES"]}

    def link(i):
        if i == "PDF": return "<span class=chip>📘 교재</span>"
        s = src.get(i)
        return f"<a href='https://www.youtube.com/watch?v={e(i)}' target=_blank>{e(s['date'])}</a>" if s else ""
    links = lambda ids: " ".join(link(i) for i in ids)

    # ── 지금 상태 ──
    ref_day = "2026-11-04"      # 교재(2026-11-16 발행)가 시장 숫자를 맞춘 날 근처
    crow = ""
    for c in d["CHECKLIST"]:
        fmt = c.get("fmt", "{:,.2f}"); now = latest(con, tuple(c["sym"]) if c["sym"] else None)
        if now:
            then = latest(con, tuple(c["sym"]), ref_day)
            val = f"<b>{fmt.format(now[1])}</b><br><span class=meta>{e(now[0])}</span>"
            if then and then[0] != now[0]: val += f"<br><span class=meta>11-04경 {fmt.format(then[1])}</span>"
        else:
            val = "<span class=meta>직접 확인<br>(월 1회 발표)</span>"
        crow += (f"<tr><td><b>{e(c['name'])}</b><br><span class=meta>{e(c['cad'])} · {e(c['where'])}</span><td>{val}<td>{e(c['ref'])}<td>{e(c['how'])}</tr>")
    checklist = "<div style='overflow-x:auto'><table><tr><th>지표<th>현재값(우리 DB)<th>교수 자료의 기준·수치<th>어떻게 읽나</tr>" + crow + "</table></div>"

    frow = ""
    for f in d["FAIR"]:
        now = latest(con, tuple(f["sym"])); fmt = f["fmt"]
        if now:
            gap = (now[1] / f["fair"] - 1) * 100
            cell = f"<b>{fmt.format(now[1])}</b> <span class=meta>({e(now[0])})</span>"
            gcell = f"<b>{gap:+.1f}%</b> {'고평가' if gap > 3 else '저평가' if gap < -3 else '적정 근처'}"
        else:
            cell = gcell = "<span class=meta>값 없음</span>"
        frow += f"<tr><td><b>{e(f['name'])}</b><td>{cell}<td>{fmt.format(f['fair'])}<br><span class=meta>{e(f['fair_note'])}</span><td>{gcell}<br><span class=meta>{e(f['extra'])}</span></tr>"
    fair = ("<div style='overflow-x:auto'><table><tr><th>대상<th>현재(우리 DB)<th>교수 모형 적정 수준<th>현재가 적정 대비</tr>" + frow + "</table></div>"
            "<p class=meta>적정 수준은 교수 연구소가 2026년 11월 초에 추정한 값이라 이후 새 통계가 나오면 달라진다. 현재가가 적정보다 높다는 것이 곧 하락 예측은 아니다(교재도 '비싸다고 바로 떨어지지는 않는다'고 말한다).</p>")

    kofia = latest(con, ("kofia", "STATSCU0100000070BO:TMPV2"))
    extra = (f"<p class=meta>참고: 교수가 '빚으로 산 주식'을 경계하는 만큼, 한국 신용융자 잔고도 같이 본다 — "
             f"<b>{kofia[1]:.1f}조원</b> ({e(kofia[0])}, 금융투자협회). <a href='indicators.html'>📊 지표</a> 페이지에서 추이를 볼 수 있다.</p>") if kofia else ""

    # ── 본문 ──
    summary = f"<section class=card><h3>한 줄 요약</h3><p>{e(d['SUMMARY'])}</p></section>"
    rules = "".join(f"<section class=card><h3>{i}. {e(r['title'])}</h3><p>{e(r['body'])}</p><div class=meta>근거: {links(r['src'])}</div></section>" for i, r in enumerate(d["RULES"], 1))
    phases = "".join(f"<tr{' style=\"background:var(--chip)\"' if '지금' in p['phase'] else ''}><td><b>{e(p['phase'])}</b><br><span class=meta>{e(p['when'])}</span><td><b>{e(p['stock'])}</b><td>{e(p['cash'])}<td>{e(p['note'])}</tr>" for p in d["PHASES"])
    grp_tot = {}
    for a in d["ALLOC"]: grp_tot[a["grp"]] = grp_tot.get(a["grp"], 0) + a["pct"]
    bars = "".join(f"<div style='display:flex;align-items:center;gap:8px;margin:4px 0'><div style='width:120px'>{e(a['name'])}</div><div style='background:var(--ac);height:14px;width:{a['pct']*4}px;border-radius:3px'></div><b>{a['pct']}%</b><span class=meta>{e(a.get('note',''))}</span></div>" for a in d["ALLOC"])
    grp = " · ".join(f"{e(k)} {v}%" for k, v in grp_tot.items())
    alloc = f"<section class=card><h3>안정형 배분 예시 (선행지수 하락기)</h3>{bars}<p class=meta>성격별로 묶으면 {grp}. 교재는 '일반 원칙의 한 예시'라고 밝힌다.</p></section>"
    sig = lambda items: "".join(f"<li><b>{e(a)}</b> — {e(b)}</li>" for a, b in items)
    signals = (f"<div class=card><h3>🔻 위험을 줄일(지킬) 신호</h3><ul>{sig(d['SIGNALS']['reduce'])}</ul>"
               f"<h3>🔺 주식 비중 확대를 검토할 신호</h3><ul>{sig(d['SIGNALS']['add'])}</ul></div>")
    avoid = "<ul>" + sig(d["AVOID"]) + "</ul>"
    scen = "".join(f"<tr><td><b>{e(s['name'])}</b><td><b>{s['pct']}%</b><td>{e(s['body'])}</tr>" for s in d["SCENARIOS"])
    how = "".join(f"<li><b>{e(h['step'])}</b><br>{e(h['body'])}</li>" for h in d["HOWTO"])
    cau = "".join(f"<li>{e(c)}</li>" for c in d["CAUTIONS"])
    srows = "".join(f"<tr><td>{e(s['date'])}<td><a href='https://www.youtube.com/watch?v={e(s['id'])}' target=_blank>{e(s['title'])}</a><br><span class=meta>{e(s['gist'])}</span></tr>"
                    for s in sorted(d["SOURCES"], key=lambda s: s["date"], reverse=True))

    body = (f"<h1>🎓 김영익 교수 투자 방식 — 지표로 국면을 읽고 비중을 바꾼다</h1>"
            f"<p class=meta>채널 <a href='{e(d['CHANNEL']['url'])}' target=_blank>{e(d['CHANNEL']['name'])}</a> · 근거: 2027 자산배분 전략 바이블(교재, 2026-11-16) + 영상 {len(d['SOURCES'])}개 · 조사 내용 저장 {e(row['updated_at'][:16])} · '지금 상태'는 이 페이지를 만들 때마다 DB 값으로 갱신 · <a href='index.html'>🏠 홈</a></p>"
            f"{summary}"
            f"<h2 class=cat-h>🧭 국면별 비중 — 핵심 규칙</h2><div style='overflow-x:auto'><table><tr><th>국면<th>주식<th>나머지<th>메모</tr>{phases}</table></div>{alloc}"
            f"<h2 class=cat-h>📍 지금 상태 (교수의 점검 지표 + 우리 DB 값)</h2>{checklist}{extra}"
            f"<h2 class=cat-h>⚖️ 지금 가격은 교수 모형으로 어디쯤?</h2>{fair}"
            f"<h2 class=cat-h>🔔 비중을 바꿀 신호</h2>{signals}"
            f"<h2 class=cat-h>📚 투자 원칙 11가지</h2>{rules}"
            f"<h2 class=cat-h>⛔ 지금 피해야 할 세 가지</h2><section class=card>{avoid}</section>"
            f"<h2 class=cat-h>🎲 2027년 시나리오 (교수 추정 확률)</h2><div style='overflow-x:auto'><table><tr><th>경로<th>확률<th>내용</tr>{scen}</table></div>"
            f"<h2 class=cat-h>🛠️ 따라 하려면</h2><ol class=how>{how}</ol>"
            f"<h2 class=cat-h>⚠️ 주의할 점</h2><ul>{cau}</ul>"
            f"<h2 class=cat-h>🎬 조사한 영상</h2><details open><summary>{len(d['SOURCES'])}개</summary><div style='overflow-x:auto'><table><tr><th>업로드<th>제목과 요지</tr>{srows}</table></div></details>")
    (R.OUT / "kimyoungik.html").write_text(R.page("김영익 교수 투자 방식", "<style>ol.how li{margin:10px 0}.chip{background:var(--chip);border-radius:6px;padding:1px 7px;font-size:12px}</style>" + body, "🎓"), encoding="utf-8")


if __name__ == "__main__":
    c = con_()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "import": do_import(c)
    else: do_import(c); build(c); print("reports/kimyoungik.html 생성")
