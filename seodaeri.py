"""서대리TV 투자 방식 정리 페이지 (reports/seodaeri.html).

조사 내용(규칙·매매 이력·따라 하는 법)은 DB research 테이블, 가격은 research_prices 테이블에 있고
페이지는 DB 만 읽어 만든다. 가격은 만들 때마다 Yahoo 에서 새로 받아 '지금 상태'가 매일 갱신된다.

  uv run seodaeri.py import    # seodaeri_data.py 의 조사 내용을 DB 에 저장
  uv run seodaeri.py refresh   # SPY·QQQ·원/달러 가격 갱신(DB)
  uv run seodaeri.py build     # reports/seodaeri.html 만들기 (report.build_all 도 호출)
"""
import datetime, json, sys, urllib.parse
from html import escape as e
import db as D

SLUG = "seodaeri"
SYMS = {"SPY": ("SPY", "2y"), "QQQ": ("QQQ", "2y"), "USDKRW": ("KRW=X", "10y")}
RULE_DD = {"SPY": 0.20, "QQQ": 0.15}          # 추가 매수 기준: 고점 대비 하락률
DDL = """CREATE TABLE IF NOT EXISTS research(slug TEXT PRIMARY KEY, title TEXT, data_json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS research_prices(symbol TEXT, date TEXT, close REAL, PRIMARY KEY(symbol, date));"""


def con_():
    con = D.connect(); con.executescript(DDL); return con


def do_import(con):
    import seodaeri_data as S
    data = {k: getattr(S, k) for k in ("CHANNEL", "SUMMARY", "RULES", "TRADES", "NO_ADDITIONAL", "ACCOUNTS", "HOWTO", "CAUTIONS", "SOURCES")}
    con.execute("INSERT OR REPLACE INTO research VALUES(?,?,?,?)", (SLUG, "서대리TV 투자 방식", json.dumps(data, ensure_ascii=False), D.now()))
    con.commit(); print("research 저장:", {k: len(v) for k, v in data.items() if hasattr(v, "__len__")})


def _yahoo(symbol, rng):
    import marketdata as M
    t = M._get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={rng}&interval=1d")
    res = json.loads(t)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    return [(datetime.datetime.fromtimestamp(a + off, datetime.timezone.utc).date().isoformat(), c)
            for a, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]


def refresh(con):
    for name, (sym, rng) in SYMS.items():
        try:
            rows = _yahoo(sym, rng)
        except Exception as ex:
            print(f"  {name} 가격 갱신 실패: {ex}"); continue
        con.executemany("INSERT OR REPLACE INTO research_prices VALUES(?,?,?)", [(name, d, round(c, 4)) for d, c in rows])
        print(f"  {name}: {len(rows)}일, 최근 {rows[-1]}")
    con.commit()


def series(con, sym, since=None):
    q = "SELECT date, close FROM research_prices WHERE symbol=?" + (" AND date>=?" if since else "") + " ORDER BY date"
    return [(r[0], r[1]) for r in con.execute(q, (sym, since) if since else (sym,))]


# ---------- 차트(인라인 SVG) ----------
def _svg(pts, hlines, marks, w=880, h=270, unit="", fmt="{:,.0f}"):
    """pts [(date, v)], hlines [(v, label, color, dash)], marks [(date, label)]"""
    if not pts: return "<p class=meta>가격 자료 없음</p>"
    L, R, T, B = 52, 14, 14, 26
    ds = [datetime.date.fromisoformat(d) for d, _ in pts]
    vs = [v for _, v in pts] + [x[0] for x in hlines]
    lo, hi = min(vs) * 0.98, max(vs) * 1.02
    d0, d1 = ds[0].toordinal(), ds[-1].toordinal()
    X = lambda d: L + (d.toordinal() - d0) / max(1, d1 - d0) * (w - L - R)
    Y = lambda v: T + (hi - v) / (hi - lo) * (h - T - B)
    s = f"<svg viewBox='0 0 {w} {h}' style='width:100%;height:auto;max-width:{w}px' role=img>"
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        s += f"<line x1={L} x2={w-R} y1={Y(v):.1f} y2={Y(v):.1f} stroke='var(--bd)'/><text x=4 y={Y(v)+4:.1f} font-size=11 fill='var(--mu)'>{fmt.format(v)}</text>"
    m0 = datetime.date(ds[0].year, ds[0].month, 1)
    while m0 <= ds[-1]:
        if m0 >= ds[0] and m0.month in (1, 4, 7, 10):
            s += f"<line x1={X(m0):.1f} x2={X(m0):.1f} y1={T} y2={h-B} stroke='var(--bd)' stroke-dasharray='2 4'/><text x={X(m0)-18:.1f} y={h-8} font-size=11 fill='var(--mu)'>{m0.year}-{m0.month:02d}</text>"
        m0 = datetime.date(m0.year + (m0.month == 12), m0.month % 12 + 1, 1)
    s += "<polyline fill=none stroke='var(--ac)' stroke-width=1.8 points='" + " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, (_, v) in zip(ds, pts)) + "'/>"
    for v, lab, col, dash in hlines:
        s += f"<line x1={L} x2={w-R} y1={Y(v):.1f} y2={Y(v):.1f} stroke='{col}' stroke-width=1.4 stroke-dasharray='{dash}'/><text x={w-R-4} y={Y(v)-4:.1f} text-anchor=end font-size=11 fill='{col}'>{e(lab)}</text>"
    pd = dict(pts)
    for d, lab in marks:
        dd = datetime.date.fromisoformat(d)
        v = pd.get(d) or next((x for dt, x in reversed(pts) if dt <= d), None)
        if v is None: continue
        x, y = X(dd), Y(v)
        s += f"<g><title>{e(lab)}</title><path d='M{x:.1f} {y-3:.1f} l-6 -11 h12 z' fill='#1a8a4a' stroke='#fff' stroke-width=.8/></g>"
    return s + "</svg>"


def _pct(a, b): return (a / b - 1) * 100


def status_block(con):
    spy, qqq, fx = series(con, "SPY"), series(con, "QQQ"), series(con, "USDKRW")
    if not (spy and qqq): return "<p class=meta>가격 자료가 아직 없습니다(`uv run seodaeri.py refresh`).</p>"
    rows, notes = "", []
    for name, s in (("SPY", spy), ("QQQ", qqq)):
        hi_d, hi = max(s, key=lambda x: x[1]); cur_d, cur = s[-1]
        dd = RULE_DD[name]; tgt = hi * (1 - dd)
        need = _pct(tgt, cur)             # 기준가까지 더 필요한 등락률(음수)
        state = "🟢 기준가 이하 — 월적립일에 추가 매수 조건 충족" if cur <= tgt else ("🟠 기준가 근접(5% 이내)" if cur <= tgt * 1.05 else "⚪ 기준가 위 — 월적립만")
        rows += (f"<tr><td><b>{name}</b><td>{hi:,.2f}<br><span class=meta>{hi_d}</span><td>{cur:,.2f}<br><span class=meta>{cur_d}</span>"
                 f"<td>{_pct(cur, hi):+.1f}%<td>-{dd*100:.0f}% → <b>{tgt:,.2f}</b><td>{need:+.1f}%<td>{state}</tr>")
        if cur <= tgt * 1.05: notes.append(name)
    out = ("<table><tr><th>ETF<th>고점(조회 2년 내)<th>현재가<th>고점 대비<th>추매 기준가(서대리 규칙)<th>기준가까지<th>상태</tr>" + rows + "</table>")
    if fx:
        fx10 = sum(c for _, c in fx) / len(fx); cur_d, cur = fx[-1]
        fstate = "🟢 10년 평균보다 낮음 — 서대리 기준 추가 환전 구간" if cur < fx10 else "⚪ 10년 평균보다 높음 — 추가 환전 안 함(월적립 환전만)"
        out += (f"<table style='margin-top:10px'><tr><th>원/달러<th>현재<th>최근 10년 평균(DB 일별값)<th>평균 대비<th>상태</tr>"
                f"<tr><td>USD/KRW<td>{cur:,.1f}원<br><span class=meta>{cur_d}</span><td>{fx10:,.1f}원<td>{_pct(cur, fx10):+.1f}%<td>{fstate}</tr></table>"
                "<p class=meta>서대리가 영상(2026-09-14)에서 말한 10년 평균은 1,252원이다. 여기 값은 Yahoo 일별 종가 평균이라 약간 다를 수 있다.</p>")
    return out, notes


def build(con=None, refresh_prices=True):
    import report as R
    con = con or con_()
    row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    if not row:
        do_import(con); row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    if refresh_prices:
        try: refresh(con)
        except Exception as ex: print("  서대리 가격 갱신 실패:", ex)
    d = json.loads(row["data_json"])
    src = {s["id"]: s for s in d["SOURCES"]}
    link = lambda i: f"<a href='https://www.youtube.com/watch?v={e(i)}' target=_blank>{e(src[i]['date'] if i in src else '')}</a>" if i in src else ""
    links = lambda csv: " ".join(link(i) for i in csv.split(",") if i)
    st = status_block(con)
    status, near = (st if isinstance(st, tuple) else (st, []))

    spy, qqq, fx = series(con, "SPY", "2025-10-01"), series(con, "QQQ", "2025-10-01"), series(con, "USDKRW", "2025-10-01")
    buys = [(t["date"], f"{t['date']} {t['kind']}: {t['what'][:70]}…") for t in d["TRADES"] if t["kind"] in ("적립", "매도→매수", "기타") and t["date"][:2] == "20" and len(t["date"]) == 10]
    fx10 = (lambda s: sum(c for _, c in s) / len(s) if s else 0)(series(con, "USDKRW"))
    charts = ""
    for name, s in (("SPY", spy), ("QQQ", qqq)):
        full = series(con, name)
        if not full: continue
        hi = max(full, key=lambda x: x[1])[1]; tgt = hi * (1 - RULE_DD[name])
        charts += (f"<h3>{name} — 월적립(▲)과 추가 매수 기준가</h3>"
                   + _svg(s, [(hi, f"고점 {hi:,.0f}", "#888", "4 4"), (tgt, f"추매 기준가 {tgt:,.0f} (-{RULE_DD[name]*100:.0f}%)", "#c0392b", "6 3")], buys, fmt="{:,.0f}"))
    if fx:
        charts += "<h3>원/달러 — 서대리의 추가 환전 기준(10년 평균)</h3>" + _svg(fx, [(fx10, f"10년 평균 {fx10:,.0f}원", "#c0392b", "6 3")] if fx10 else [], buys, fmt="{:,.0f}")
    charts += "<p class=meta>▲ = 영상으로 확인된 매수·매매일(마우스를 올리면 내용). 확인되지 않은 달(1·3·4·6월)은 표시하지 않았다. 추매(규칙 기반 추가 매수)는 2026년에 한 번도 없었다.</p>"

    kind_color = {"적립": "#1a8a4a", "추매": "#2b5fd9", "매도": "#c0392b", "매도→매수": "#d9822b", "기타": "#6b6b66"}
    trows = "".join(f"<tr><td>{e(t['date'])}<td><b style='color:{kind_color.get(t['kind'], '#666')}'>{e(t['kind'])}</b><td>{e(t['acct'])}<td>{e(t['what'])}<td>{links(t['src'])}</tr>" for t in sorted(d["TRADES"], key=lambda t: t["date"], reverse=True))
    rules = "".join(f"<section class=card><h3>{i}. {e(r['title'])}</h3><p>{e(r['body'])}</p><div class=meta>근거 영상: {links(','.join(r['src']))}</div></section>" for i, r in enumerate(d["RULES"], 1))
    acc = "".join(f"<tr><td><b>{e(a['acct'])}</b><td>{e(a['plan'])}<td>{e(a['what'])}<td>{links(a['src'])}</tr>" for a in d["ACCOUNTS"])
    how = "".join(f"<li><b>{e(h['step'])}</b><br>{e(h['body'])}</li>" for h in d["HOWTO"])
    cau = "".join(f"<li>{e(c)}</li>" for c in d["CAUTIONS"])
    srows = "".join(f"<tr><td>{e(s['date'])}<td><a href='https://www.youtube.com/watch?v={e(s['id'])}' target=_blank>{e(s['title'])}</a><td>{'✅' if s['read'] else '자막 없음'}</tr>" for s in sorted(d["SOURCES"], key=lambda s: s["date"], reverse=True))
    n_read = sum(1 for s in d["SOURCES"] if s["read"])

    if near:
        rec = (f"<p>⚠️ {', '.join(near)} 가 추매 기준가에 5% 이내로 가까워졌습니다. 서대리 규칙대로라면 <b>기준가에 닿아도 그날 바로 사지 않고 월적립일(25일 전후)에 가격을 확인</b>해, 기준가 이하일 때만 "
               "달러 RP·파킹 ETF를 팔아 추가 매수합니다. 이전에 정해 둔 현금이 없다면 추매는 할 수 없고 월적립만 합니다.</p>")
    else:
        rec = "<p>현재는 두 ETF 모두 기준가보다 5% 넘게 위에 있어 서대리 규칙상 월적립만 합니다.</p>"
    rec += ("<ul><li><b>월적립</b>: 이번 달도 월급날(25일 전후)에 평소처럼 매수. 중단하지 않는다.</li>"
            "<li><b>추가 매수</b>: 위 표의 기준가 이하일 때만. 그 전에는 하지 않는다.</li>"
            "<li><b>환전</b>: 원/달러가 10년 평균보다 낮아질 때만 추가 환전.</li>"
            "<li><b>매도</b>: 하지 않는다(만기 있는 돈은 애초에 투자하지 않는다).</li></ul>")
    body = (f"<h1>📺 서대리TV 투자 방식 — 어떻게 하고, 어떻게 따라 하나</h1>"
            f"<p class=meta>채널 <a href='{e(d['CHANNEL']['url'])}' target=_blank>{e(d['CHANNEL']['name'])}</a> · 영상 {len(d['SOURCES'])}개 조사(자막을 읽은 영상 {n_read}개) · 조사 내용 저장 {e(row['updated_at'][:16])} · 가격은 이 페이지를 만들 때마다 갱신 · <a href='index.html'>🏠 홈</a></p>"
            f"<section class=card><h3>한 줄 요약</h3><p>{e(d['SUMMARY'])}</p></section>"
            f"<h2 class=cat-h>📍 지금 상태 (서대리 규칙으로 계산)</h2>{status}"
            f"<section class=card><h3>지금 서대리 방식으로는?</h3>{rec}<p class=meta>서대리의 규칙을 그대로 적용한 계산이며 투자 권유가 아닙니다. 서대리가 '지금 이것을 추천한다'고 한 종목은 없고, 영상(2026-11-06)에서는 기준가에 못 미쳐 추가 매수를 하지 않고 월적립만 이어간다고 했습니다.</p></section>"
            f"<h2 class=cat-h>📈 언제 사고 팔았나 (차트)</h2>{charts}"
            f"<h2 class=cat-h>🧾 매매 이력 (영상에서 확인된 것)</h2><div style='overflow-x:auto'><table><tr><th>날짜<th>구분<th>계좌<th>내용<th>근거</tr>{trows}</table></div>"
            f"<p class=meta>{e(d['NO_ADDITIONAL'])}</p>"
            f"<h2 class=cat-h>🧭 핵심 규칙</h2>{rules}"
            f"<h2 class=cat-h>🏦 계좌별 구조</h2><div style='overflow-x:auto'><table><tr><th>계좌<th>월 납입<th>운용<th>근거</tr>{acc}</table></div>"
            f"<h2 class=cat-h>🛠️ 따라 하려면</h2><ol class=how>{how}</ol>"
            f"<h2 class=cat-h>⚠️ 주의할 점</h2><ul>{cau}</ul>"
            f"<h2 class=cat-h>🎬 조사한 영상</h2><details><summary>{len(d['SOURCES'])}개 보기</summary><div style='overflow-x:auto'><table><tr><th>업로드<th>제목<th>자막</tr>{srows}</table></div></details>")
    (R.OUT / "seodaeri.html").write_text(R.page("서대리TV 투자 방식", "<style>ol.how li{margin:10px 0}</style>" + body, "📺"), encoding="utf-8")


if __name__ == "__main__":
    c = con_()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "import": do_import(c)
    elif cmd == "refresh": refresh(c)
    else: build(c); print("reports/seodaeri.html 생성")
