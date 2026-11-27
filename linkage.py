"""지표 연결 페이지(reports/linkage.html): 서로 이어진 지표들을 한 묶음으로 보고 어떤 순서로 분석할지 보여 준다.
정의는 linkage_data.py(LINKS)에 있고, 값·그래프·현재 판정은 DB(indicator_values)로 만든다. LLM 은 쓰지 않는다."""
import datetime, statistics
from html import escape as e
import db as D
import linkage_data as L

YEARS = 3
COL = ["#2b5fd9", "#d9822b", "#1a8a4a", "#c0392b", "#7b5ea7"]


def find(con, src, sym):
    r = con.execute("""SELECT i.id, i.name, i.unit FROM indicators i WHERE i.source=? AND i.symbol=? AND i.active=1 AND i.alias_of IS NULL
                       ORDER BY (SELECT count(*) FROM indicator_values v WHERE v.indicator_id=i.id) DESC LIMIT 1""", (src, sym)).fetchone()
    return dict(r) if r else None


def series(con, iid):
    cut = (datetime.date.today() - datetime.timedelta(days=int(YEARS * 365.25))).isoformat()
    d = {}
    for r in con.execute("SELECT date, value, value_date FROM indicator_values WHERE indicator_id=? AND value IS NOT NULL ORDER BY date", (iid,)):
        x = r["value_date"] or r["date"]
        if x >= cut: d[x] = r["value"]
    return sorted(d.items())


def at(pts, day):
    """day 이하의 마지막 값."""
    best = None
    for d, v in pts:
        if d <= day: best = v
        else: break
    return best


def back(pts, days):
    if not pts: return None
    t = (datetime.date.fromisoformat(pts[-1][0]) - datetime.timedelta(days=days)).isoformat()
    return at(pts, t)


def change(pts, days, kind):
    """days 일 전 대비 변화: rate→(bp), growth→(%p), level→(%)."""
    p = back(pts, days)
    if p is None or not pts: return None
    v = pts[-1][1]
    return (v - p) * 100 if kind == "rate" else (v - p) if kind == "growth" else ((v / p - 1) * 100 if p else None)


def fmtc(c, kind):
    if c is None: return "-"
    if round(c) == 0 and kind == "rate": c = 0.0
    return f"{c:+,.0f}bp" if kind == "rate" else f"{c:+.1f}%p" if kind == "growth" else f"{c:+.1f}%"


def rank3m(pts, kind):
    """최신 3개월 변화가 최근 3년의 3개월 변화 중 몇 % 위치인지(0~100, 높을수록 많이 오른 편)."""
    if len(pts) < 30: return None
    ch = []
    for d, v in pts:
        p = at(pts, (datetime.date.fromisoformat(d) - datetime.timedelta(days=91)).isoformat())
        if p is not None and pts[0][0] <= (datetime.date.fromisoformat(d) - datetime.timedelta(days=91)).isoformat():
            ch.append((v - p) if kind in ("rate", "growth") else ((v / p - 1) if p else 0))
    if len(ch) < 20: return None
    cur = ch[-1]
    return 100.0 * sum(1 for x in ch if x <= cur) / len(ch)


def fv(v, kind, unit=""):
    return "-" if v is None else f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"


def chart(con, spec):
    """여러 계열을 한 그래프에(같은 축). norm=시작 100 맞춤, zero=0 선."""
    ss = []
    for k, t in enumerate(spec["series"]):
        ind = find(con, t[0], t[1])
        if not ind: continue
        pts = series(con, ind["id"])
        if len(pts) < 2: continue
        if spec.get("norm"):
            b = pts[0][1]; pts = [(d, v / b * 100) for d, v in pts]
        ss.append((t[2] if len(t) > 2 else ind["name"], COL[k % len(COL)], pts))
    if not ss: return ""
    W, H, X0, X1, Y0, Y1 = 820, 280, 52, 800, 30, 238
    d0 = min(p[0][0] for _, _, p in ss); d1 = max(p[-1][0] for _, _, p in ss)
    D0, D1 = datetime.date.fromisoformat(d0), datetime.date.fromisoformat(d1); span = max((D1 - D0).days, 1)
    vals = [v for _, _, p in ss for _, v in p] + ([0] if spec.get("zero") else [])
    lo, hi = min(vals), max(vals)
    if lo == hi: lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.06; lo -= pad; hi += pad
    px = lambda d: X0 + (X1 - X0) * (datetime.date.fromisoformat(d) - D0).days / span
    py = lambda v: Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)
    o = [f"<svg viewBox='0 0 {W} {H}' class=lk role=img aria-label='{e(spec['title'])}'>"]
    for g in range(5):
        v = lo + (hi - lo) * g / 4
        o.append(f"<line x1={X0} x2={X1} y1={py(v):.1f} y2={py(v):.1f} class=gr /><text x={X0 - 6} y={py(v) + 4:.1f} text-anchor=end class=m>{fv(v, 'x')}</text>")
    y = D0.year + 1
    while datetime.date(y, 1, 1) <= D1:
        x = px(f"{y}-01-01"); o.append(f"<line x1={x:.1f} x2={x:.1f} y1={Y0} y2={Y1} class=gr stroke-dasharray='3,3' /><text x={x:.1f} y={Y1 + 16} text-anchor=middle class=m>{y}</text>"); y += 1
    if spec.get("zero"): o.append(f"<line x1={X0} x2={X1} y1={py(0):.1f} y2={py(0):.1f} stroke='var(--fg)' stroke-width=1.2 opacity=.6 />")
    lx = X0
    for name, c, pts in ss:
        step = max(1, len(pts) // 220); idx = sorted(set(range(0, len(pts), step)) | {len(pts) - 1})
        o.append(f"<polyline fill=none stroke='{c}' stroke-width=2 points='" + " ".join(f"{px(pts[i][0]):.1f},{py(pts[i][1]):.1f}" for i in idx) + "' />")
        if len(pts) <= 40:
            for d, v in pts: o.append(f"<circle cx={px(d):.1f} cy={py(v):.1f} r=3.5 fill='{c}'><title>{e(name)} {d}: {fv(v, 'x')}</title></circle>")
        else:
            for i in idx[::max(1, len(idx) // 50)]: o.append(f"<circle cx={px(pts[i][0]):.1f} cy={py(pts[i][1]):.1f} r=5 fill=transparent><title>{e(name)} {pts[i][0]}: {fv(pts[i][1], 'x')}</title></circle>")
        d, v = pts[-1]; o.append(f"<circle cx={px(d):.1f} cy={py(v):.1f} r=3.5 fill='{c}' /><text x={min(px(d) + 5, W - 4):.1f} y={py(v) + 4:.1f} text-anchor={'start' if px(d) + 60 < W else 'end'} class=m style='fill:{c};font-weight:700'>{fv(v, 'x')}</text>")
        o.append(f"<rect x={lx} y=6 width=12 height=12 fill='{c}' /><text x={lx + 17} y=16 class=m>{e(name)}</text>"); lx += 34 + 13 * len(name)
    return "".join(o) + "</svg>"


def table(con, members):
    rows, data = "", {}
    for src, sym, short, kind in members:
        ind = find(con, src, sym)
        if not ind: continue
        pts = series(con, ind["id"])
        if not pts: continue
        data[sym] = (pts, kind, ind)
        r = rank3m(pts, kind)
        rk = "-" if r is None else f"{r:.0f}%"
        cls = "" if r is None else " class=up" if r >= 80 else " class=down" if r <= 20 else ""
        slow = "분기 값" if src == "sec" else ""
        rows += (f"<tr><td><a href='indicator_trends.html#i-{ind['id']}'>{e(short)}</a><td>{fv(pts[-1][1], kind)}<span class=meta> {e(ind['unit'] or '')}</span><br><span class=meta>{pts[-1][0]} {slow}</span>"
                 f"<td>{fmtc(change(pts, 30, kind), kind)}<td>{fmtc(change(pts, 91, kind), kind)}<td>{fmtc(change(pts, 182, kind), kind)}<td>{fmtc(change(pts, 365, kind), kind)}<td{cls}>{rk}</tr>")
    return ("<div style='overflow-x:auto'><table><tr><th>지표<th>최신 값<th>1개월 변화<th>3개월 변화<th>6개월 변화<th>1년 변화<th>3개월 변화 순위<sup>*</sup></tr>" + rows + "</table></div>"
            "<p class=meta><sup>*</sup> 최근 3년의 3개월 변화 중 몇 % 위치인지(80% 이상 = 이례적으로 많이 오른 편, 20% 이하 = 많이 내린 편). 금리·스프레드의 변화는 bp(0.01%p).</p>"), data


# ── 현재 판정(규칙) ──────────────────────────────────────────────
def j_rates(d):
    o = []
    g = lambda s: d.get(s, (None,))[0]
    ff, s2, s10, t102, t103 = g("DFF"), g("DGS2"), g("DGS10"), g("T10Y2Y"), g("T10Y3M")
    if ff:
        c = change(ff, 182, "rate"); o.append(f"미국 기준금리 {ff[-1][1]:.2f}% — 6개월 {fmtc(c, 'rate')}으로 {'내려가는(완화) 중' if c is not None and c < -10 else '오르는(긴축) 중' if c is not None and c > 10 else '거의 변화 없이 유지'}.")
    if s10 and s2: o.append(f"국채 2년 {s2[-1][1]:.2f}% · 10년 {s10[-1][1]:.2f}% — 10년물 3개월 {fmtc(change(s10, 91, 'rate'), 'rate')}.")
    for nm, sr in (("10년-2년", t102), ("10년-3개월", t103)):
        if sr:
            v, c = sr[-1][1], change(sr, 91, "rate")
            o.append(f"미국 장단기 금리차({nm}) {v:+.2f}%p — {'역전(경기 둔화 신호)' if v < 0 else '정상(플러스)'}, 3개월 {fmtc(c, 'rate')}{' → 기울기가 가팔라지는 중(정상화)' if c is not None and c > 20 else ' → 기울기가 눌리는 중' if c is not None and c < -20 else ''}.")
    ic = "🟡" if (t102 and t102[-1][1] < 0.3) or (ff and change(ff, 182, "rate") not in (None,) and abs(change(ff, 182, "rate")) > 25) else "🟢"
    return ic, o


def j_credit(d):
    o, warn = [], 0
    g = lambda s: d.get(s, (None,))[0]
    for sym, nm in (("BAMLC0A0CM", "IG 스프레드"), ("BAMLH0A0HYM2", "HY 스프레드"), ("817Y002/D/010300000|minus=010200000", "한국 AA- 스프레드")):
        pts = g(sym)
        if not pts: continue
        v = pts[-1][1]; med = statistics.median(x for _, x in pts); c3, r = change(pts, 91, "rate"), rank3m(pts, "rate")
        fast = r is not None and r >= 80 and c3 is not None and c3 > 0
        warn += fast
        o.append(f"{nm} {v:.2f}%p (3년 중앙값 {med:.2f}) — 3개월 {fmtc(c3, 'rate')}{f'(변화 순위 {r:.0f}%)' if r is not None else ''}: " + ("확대 속도가 이례적으로 빠름 ⚠️" if fast else "벌어지는 속도는 보통 이하" if c3 is not None and c3 <= 0 or (r is not None and r < 80) else ""))
    hy, ig = g("BAMLH0A0HYM2"), g("BAMLC0A0CM")
    if hy and ig: o.append(f"HY-IG 스프레드 격차 {hy[-1][1] - ig[-1][1]:.2f}%p — 3개월 전 {(back(hy, 91) or 0) - (back(ig, 91) or 0):.2f}%p.")
    return ("🔴" if warn >= 2 else "🟡" if warn == 1 else "🟢"), o


def j_bigtech(d):
    o = []
    g = lambda s: d.get(s, (None,))[0]
    de, ca, oc = g("BIGTECH:DEBT_YOY"), g("BIGTECH:CAPEX_YOY"), g("BIGTECH:OCF_YOY")
    fcf, cur, debt = g("BIGTECH:FCF"), g("BIGTECH:DEBTCUR"), g("BIGTECH:DEBT")
    ic = "🟢"
    if de and ca and oc:
        a, b, c = de[-1][1], ca[-1][1], oc[-1][1]
        o.append(f"증가율(전년 동기 대비): 부채 {a:+.0f}% · CAPEX {b:+.0f}% · 영업현금흐름 {c:+.0f}% — " + ("부채가 CAPEX·현금흐름보다 빠르게 늘어 투자를 빚으로 메우는 모습 ⚠️" if a > b and b > c else "CAPEX 가 현금흐름보다 빠르게 늘어 여유가 줄어드는 중" if b > c else "현금흐름 증가가 투자 증가를 앞섬"))
        if a > b > c: ic = "🔴"
        elif b > c: ic = "🟡"
    if fcf:
        v = fcf[-1][1]; o.append(f"잉여현금흐름 {v:+,.1f}십억달러({fcf[-1][0]}) — {'0 아래: 투자가 번 돈을 넘어 외부 자금에 의존' if v < 0 else '플러스'}" + (f", 4분기 전 {back(fcf, 365):+,.1f}." if back(fcf, 365) is not None else "."))
        if v < 0 and ic == "🟢": ic = "🟡"
    if cur and debt:
        sh = cur[-1][1] / (cur[-1][1] + debt[-1][1]) * 100; p = back(cur, 365); pd_ = back(debt, 365)
        sh0 = (p / (p + pd_) * 100) if p is not None and pd_ else None
        o.append(f"1년 내 만기 부채 {cur[-1][1]:.1f}십억달러 — 전체 부채의 {sh:.1f}%" + (f"(1년 전 {sh0:.1f}%)" if sh0 is not None else "") + f": {'단기 차환 물량이 몰리는 편' if sh > 10 else '만기가 대부분 길어 당장의 차환 부담은 크지 않음'}.")
    return ic, o


def j_impact(d):
    o, ic = [], "🟢"
    g = lambda s: d.get(s, (None,))[0]
    gold, spx, hy = g("GC=F"), g("^GSPC"), g("BAMLH0A0HYM2")
    if gold and spx:
        a, b = change(gold, 91, "level"), change(spx, 91, "level"); h = change(hy, 91, "rate") if hy else None
        o.append(f"3개월 변화 — 금 {a:+.1f}% · S&P500 {b:+.1f}%" + (f" · HY 스프레드 {fmtc(h, 'rate')}" if h is not None else "") + ".")
        wide = h is not None and h > 30
        if b < -5 and wide: ic = "🔴"; o.append("스프레드가 벌어지는 가운데 주가도 내리고 있다 — 신용 경고가 가격에 반영되기 시작한 모습이다.")
        elif b < 0 and wide: ic = "🟡"; o.append("스프레드가 벌어지고 주가가 약해지는 초기 단계다.")
        elif b > 0 and wide: ic = "🟡"; o.append("주가가 오르는데 스프레드가 벌어지고 있다 — 아직 반영 전일 수 있다.")
        else: o.append("스프레드가 크게 벌어지지 않아 주가와 신용 신호가 어긋나지 않는다.")
        if a > 5: o.append("금 강세가 함께 나타나 안전자산 선호가 보인다.")
        elif a < -5: o.append("금은 내리고 있어 안전자산 선호는 뚜렷하지 않다.")
    return ic, o


JUDGE = {"rates": j_rates, "credit": j_credit, "bigtech": j_bigtech, "impact": j_impact}

CSS = """<style>.lk{width:100%;min-width:680px;height:auto;display:block;background:var(--card);border:1px solid var(--bd);border-radius:8px;margin:6px 0}
.lk .gr{stroke:var(--bd);stroke-width:1}.lk .m{font-size:11.5px;fill:var(--mu)}
.flow{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}.flow span.n{background:var(--chip);border:1px solid var(--bd);border-radius:10px;padding:5px 10px;font-size:13.5px;font-weight:600}
.flow span.a{color:var(--mu)}.jd li{margin:3px 0}.up{color:#c0392b;font-weight:700}.down{color:#1a8a4a;font-weight:700}ol.st li{margin:4px 0}</style>"""


def build_case(con, case):
    """사례 하나의 페이지(linkage_<id>.html)를 만들고 [(층, 아이콘, 판정 줄들)]을 돌려준다."""
    import report as R
    secs, summ = "", []
    for lk in case["layers"]:
        tb, data = table(con, lk["members"])
        charts = "".join(f"<h4 style='margin:14px 0 2px'>{e(c['title'])}</h4><div style='overflow-x:auto'>{chart(con, c)}</div>" for c in lk["charts"])
        ic, lines = JUDGE[lk["judge"]](data) if lk.get("judge") in JUDGE else ("", [])
        summ.append((lk, ic, lines))
        steps = "".join(f"<li>{e(s_)}" for s_ in lk["steps"])
        secs += (f"<section class=card id='{lk['id']}'><h3>{lk['icon']} {e(lk['title'])} <span style='font-size:20px'>{ic}</span></h3><p><b>질문</b> {e(lk['question'])}</p>"
                 f"<p><b>분석 순서</b></p><ol class=st>{steps}</ol>{charts}<h4 style='margin:14px 0 2px'>지표별 값과 변화량</h4>{tb}"
                 f"<h4 style='margin:14px 0 2px'>지금 읽기 <span class=meta>(숫자를 규칙에 대입한 기계적 요약)</span></h4><ul class=jd>{''.join(f'<li>{e(x)}' for x in lines) or '<li>판정할 값이 없습니다'}</ul></section>")
    flow = "<div class=flow>" + "<span class=a>→</span>".join(f"<span class=n>{lk['icon']} {e(lk['title'].split(' — ')[0])} {ic}</span>" for lk, ic, _ in summ) + "</div>"
    now = "".join(f"<li>{lk['icon']} <b>{e(lk['title'].split(' — ')[0])}</b> {ic} — {e(lines[0]) if lines else ''}" for lk, ic, lines in summ)
    body = (f"<h1>🔗 {e(case['title'])}</h1><p class=meta><a href='linkage.html'>‹ 지표 연결(복합지수) 목록</a> · <a href='indicators.html'>📊 지표 대시보드</a> · <a href='indicator_trends.html'>📉 지표 추이</a> · <a href='index.html'>🏠 홈</a></p>"
            f"<section class=card><h3>이 사례가 묻는 것</h3><p>{e(case['question'])}</p><h3>한 줄 요약</h3><p>{e(case['summary'])}</p>{flow}"
            f"<p><b>지금 층별 상태</b> <span class=meta>🟢 보통 · 🟡 주의 · 🔴 경계 (규칙 기반)</span></p><ul class=jd>{now}</ul></section>"
            + secs + "<section class=card><h3>읽을 때 조심할 점</h3><ul>" + "".join(f"<li>{e(c)}" for c in case["cautions"]) + "</ul></section>")
    (R.OUT / f"linkage_{case['id']}.html").write_text(R.page(case["title"], CSS + body, "🔗"), encoding="utf-8")
    return summ


def build(con):
    """목록(linkage.html) + 사례별 페이지. 사례는 linkage_data.CASES 에 계속 추가한다."""
    import report as R
    cards = ""
    for n, case in enumerate(L.CASES, 1):
        summ = build_case(con, case)
        chips = " ".join(f"<span class=chip>{lk['icon']} {e(lk['title'].split(' — ')[0])} {ic}</span>" for lk, ic, _ in summ)
        cards += (f"<section class=card><h3>사례 {n}. <a href='linkage_{case['id']}.html'>{e(case['title'])}</a></h3><p>{e(case['question'])}</p>"
                  f"<p class=meta>{e(case['summary'])}</p><div class=flow>{chips}</div><p><a href='linkage_{case['id']}.html'>사례 보기 ›</a></p></section>")
    body = (f"<h1>🔗 지표 연결(복합지수)</h1><p class=meta>서로 이어진 지표들을 한 묶음으로 보고, 어떻게 연결해 분석할지 정리한 사례 모음입니다 · 사례 {len(L.CASES)}개 · "
            "<a href='indicators.html'>📊 지표 대시보드</a> · <a href='indicator_trends.html'>📉 지표 추이</a> · <a href='index.html'>🏠 홈</a></p>"
            "<p class=meta>사례는 계속 추가됩니다. 새 사례는 <code>linkage_data.py</code> 의 <code>CASES</code> 에 (묻는 것·층별 지표·그래프·분석 순서)를 넣으면 이 목록과 홈 사이트 맵에 자동으로 나타납니다.</p>" + cards)
    (R.OUT / "linkage.html").write_text(R.page("지표 연결(복합지수)", CSS + "<style>.chip{background:var(--chip);border:1px solid var(--bd);border-radius:10px;padding:3px 9px;font-size:13px}</style>" + body, "🔗"), encoding="utf-8")
