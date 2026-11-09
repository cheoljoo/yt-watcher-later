"""지표 추이 페이지(reports/indicator_trends.html): indicator_values·macro_daily 의 날짜별 이력을 그래프와 설명으로 보여준다.
DB만 읽고 LLM 은 쓰지 않는다(설명은 숫자로 규칙 기반 생성; 지표별 '그날의 의미'는 기존 LLM 해설을 인용). report.build_all 끝에서 호출."""
from html import escape as e
import db as D
from report import page, OUT, CAT_ICON

SIG = {"warning": "🚨 경고", "threshold": "⚠️ 임계값", "direction": "🔄 방향 전환"}

def fmt(v):
    if v is None: return "-"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}".rstrip("0").rstrip(".")

def chart(pts, lo, hi, marks=None, phase_days=(), W=300, H=96):
    """pts: [(date, value)] -> 인라인 SVG 선 그래프. 경고 임계값(lo/hi)이 범위 안이면 점선으로 표시."""
    vals = [v for _, v in pts]
    ys = vals + [x for x in (lo, hi) if x is not None and min(vals) - (max(vals) - min(vals)) * 1.0 <= x <= max(vals) + (max(vals) - min(vals)) * 1.0]
    mn, mx = min(ys), max(ys)
    if mn == mx: mn, mx = mn - 1, mx + 1
    X0, X1, Y0, Y1 = 8, W - 8, 14, H - 22
    px = lambda i: X0 + (X1 - X0) * (i / (len(pts) - 1) if len(pts) > 1 else .5)
    py = lambda v: Y1 - (Y1 - Y0) * (v - mn) / (mx - mn)
    s = f"<svg viewBox='0 0 {W} {H}' width='100%' role=img aria-label='추이 그래프'>"
    marks = marks or {}
    for i, (d, _) in enumerate(pts):   # 매크로 위치가 바뀐 날: 세로 띠
        if d in phase_days:
            s += f"<rect x={px(i) - 9:.1f} y=2 width=18 height={H - 20} fill='#7b5ea7' opacity=.14><title>{d}: 매크로 위치 변경</title></rect>"
    for val, lab in ((lo, "하한"), (hi, "상한")):
        if val is not None and mn <= val <= mx:
            s += f"<line x1={X0} x2={X1} y1={py(val):.1f} y2={py(val):.1f} stroke='#c0392b' stroke-dasharray='4 3' opacity=.6 /><text x={X1} y={py(val) - 2:.1f} text-anchor=end font-size=9 fill='#c0392b'>경고 {lab} {fmt(val)}</text>"
    if len(pts) > 1:
        s += "<polyline fill=none stroke='var(--ac)' stroke-width=2 points='" + " ".join(f"{px(i):.1f},{py(v):.1f}" for i, (_, v) in enumerate(pts)) + "' />"
    for i, (d, v) in enumerate(pts):
        m = marks.get(d)
        if m:   # 중요한 날: 큰 붉은 원 + 바깥 고리 + 이유
            s += f"<circle cx={px(i):.1f} cy={py(v):.1f} r=9 fill=none stroke='#c0392b' stroke-width=2><title>{d}: {e(m)}</title></circle><circle cx={px(i):.1f} cy={py(v):.1f} r=5 fill='#c0392b'><title>{d}: {fmt(v)} — {e(m)}</title></circle>"
        else:
            s += f"<circle cx={px(i):.1f} cy={py(v):.1f} r=3.5 fill='var(--ac)'><title>{d}: {fmt(v)}</title></circle>"
        anc = "start" if i == 0 and len(pts) > 1 else "end" if i == len(pts) - 1 and len(pts) > 1 else "middle"
        s += f"<text x={px(i):.1f} y={py(v) - 7:.1f} text-anchor={anc} font-size=9.5 fill=currentColor>{fmt(v)}</text>"
        s += f"<text x={px(i):.1f} y={H - 6} text-anchor={anc} font-size=9 fill=currentColor opacity=.6>{d[5:]}</text>"
    return s + "</svg>"

def key_days(rows, big=3.0):
    """중요한 날: 신호(경고·임계값·방향 전환)가 켜진 날, 전일 대비 |변화| >= big% 인 날."""
    out = {}
    prev = None
    for r in rows:
        why = []
        if r["signal"]: why.append(SIG.get(r["signal"], r["signal"]) + (f" — {r['signal_reason']}" if r["signal_reason"] else ""))
        if prev is not None and prev["value"] and abs((r["value"] - prev["value"]) / abs(prev["value"]) * 100) >= big:
            why.append(f"전일 대비 {(r['value'] - prev['value']) / abs(prev['value']) * 100:+.1f}%")
        if why: out[r["date"]] = " · ".join(why)
        prev = r
    return out

def explain(name, unit, pts, rows, ind):
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    last = rows[-1]
    if len(pts) == 1:
        t = f"{d1} 값은 {last['value_text'] or fmt(v1)}입니다. 아직 하루치만 있어 추이는 알 수 없습니다."
    else:
        ch = (v1 - v0) / abs(v0) * 100 if v0 else None
        word = "올랐습니다" if v1 > v0 else "내렸습니다" if v1 < v0 else "변화가 없습니다"
        t = f"{d0} {fmt(v0)}{unit or ''} → {d1} {fmt(v1)}{unit or ''}" + (f" ({ch:+.1f}%)로 {word}." if ch is not None and v1 != v0 else ". 변화가 없습니다.")
        if v1 == v0: t += " (시세가 갱신되지 않는 지표이거나 발표 주기가 길어 같은 값이 이어질 수 있습니다.)"
    if ind["warn_high"] is not None and v1 >= ind["warn_high"]: t += f" 경고 상한 {fmt(ind['warn_high'])}을 넘었습니다."
    if ind["warn_low"] is not None and v1 <= ind["warn_low"]: t += f" 경고 하한 {fmt(ind['warn_low'])} 이하입니다."
    if last["signal"]: t += f" 신호: {SIG.get(last['signal'], last['signal'])}" + (f" — {last['signal_reason']}" if last["signal_reason"] else "")
    return t

def situation(con, series):
    """전체 상황 요약(규칙 기반): 매크로 위치 변화, 상승/하락 개수, 신호가 켜진 지표, 변동 큰 지표."""
    mac = con.execute("SELECT date, phase_index, phase FROM macro_daily ORDER BY date").fetchall()
    out = []
    if mac:
        tl = " → ".join(f"{m['date'][5:]} {m['phase_index']}단계({m['phase']})" for m in mac)
        out.append(f"<b>매크로 위치</b>: {e(tl)}. " + ("위치가 바뀌었습니다." if len({m['phase_index'] for m in mac}) > 1 else "기간 중 위치는 같습니다."))
    moves = []
    for s in series:
        if len(s["pts"]) > 1 and s["pts"][0][1]:
            moves.append(((s["pts"][-1][1] - s["pts"][0][1]) / abs(s["pts"][0][1]) * 100, s))
    up = sum(1 for m, _ in moves if m > 0.05); dn = sum(1 for m, _ in moves if m < -0.05)
    out.append(f"<b>변화</b>: 이력이 2일 이상인 지표 {len(moves)}개 중 상승 {up}개 · 하락 {dn}개 · 변화 없음 {len(moves) - up - dn}개.")
    big = sorted(moves, key=lambda x: -abs(x[0]))[:5]
    if big: out.append("<b>변동이 큰 지표</b>: " + ", ".join(f"{e(s['name'])} {m:+.1f}%" for m, s in big if abs(m) > 0.05) + ".")
    sig = [s for s in series if s["rows"][-1]["signal"]]
    flips = [m for a, m in zip(mac, mac[1:]) if a["phase_index"] != m["phase_index"]]
    if flips: out.append("<b>중요한 날</b>: " + ", ".join(f"{m['date']} 매크로 위치 → {m['phase_index']}단계({e(m['phase'])})" for m in flips) + " (그래프의 보라색 띠).")
    if sig: out.append("<b>신호가 켜진 지표</b>: " + ", ".join(f"{e(s['name'])}({SIG.get(s['rows'][-1]['signal'], '')})" for s in sig[:12]) + (f" 외 {len(sig) - 12}개" if len(sig) > 12 else "") + ".")
    return "<ul>" + "".join(f"<li>{x}" for x in out) + "</ul>"

def build(con):
    inds = {r["id"]: r for r in con.execute("SELECT * FROM indicators WHERE alias_of IS NULL")}
    series = {}
    for r in con.execute("SELECT * FROM indicator_values WHERE value IS NOT NULL ORDER BY date"):
        if r["indicator_id"] in inds: series.setdefault(r["indicator_id"], []).append(r)
    ser = [{"id": i, "name": inds[i]["name"], "ind": inds[i], "rows": rs, "pts": [(r["date"], r["value"]) for r in rs]} for i, rs in series.items()]
    ser.sort(key=lambda s: (s["ind"]["category"] or "~", s["ind"]["importance"] != "high", s["name"]))
    days = sorted({d for s in ser for d, _ in s["pts"]})
    body = (f"<h1>📉 지표 추이</h1><p class=meta>날짜별로 DB에 쌓인 지표 값({days[0] if days else '-'} ~ {days[-1] if days else '-'}, {len(days)}일치) · 지표 {len(ser)}개 · "
            "<a href='indicators.html'>📊 지표 대시보드</a> · <a href='index.html'>목록</a></p>")
    body += "<section class=card><h3>🧭 전체 상황</h3>" + situation(con, ser) + "<p class=meta>숫자로 자동 생성한 요약입니다. 지표별 원인 해석은 아래 카드의 'AI 해설'과 대시보드를 참고하세요. 이력이 쌓일수록 정확해집니다.</p></section>"
    mac = con.execute("SELECT date, phase_index FROM macro_daily ORDER BY date").fetchall()
    phase_days = {m["date"] for a, m in zip(mac, mac[1:]) if a["phase_index"] != m["phase_index"]}
    body += "<p class=meta>범례: <span style='color:#c0392b'>●</span> 붉은 큰 점 = 중요한 날(경고·임계값·방향 전환 신호, 또는 전일 대비 ±3% 이상) · <span style='color:#7b5ea7'>▮</span> 보라색 띠 = 매크로 위치가 바뀐 날 · 점에 마우스를 올리면 이유가 보입니다</p>"
    cat = None
    for s in ser:
        c = s["ind"]["category"] or "기타"
        if c != cat:
            cat = c; body += f"<h2 class=cat-h>{CAT_ICON.get(c, '📌')} {e(c)}</h2>"
        last = s["rows"][-1]
        star = "⭐ " if s["ind"]["importance"] == "high" else ""
        km = key_days(s["rows"])
        body += (f"<section class='card vc' id='i-{s['id']}'><h3>{star}{e(s['name'])}</h3>{chart(s['pts'], s['ind']['warn_low'], s['ind']['warn_high'], km, phase_days)}"
                 f"<p>{e(explain(s['name'], s['ind']['unit'], s['pts'], s['rows'], s['ind']))}</p>")
        if km: body += "<p><b>🔴 중요한 날</b></p><ul>" + "".join(f"<li><b>{d}</b> {e(w)}" for d, w in km.items()) + "</ul>"
        if last["meaning"]: body += f"<p class=meta>🤖 AI 해설({e(last['llm'] or '-')}, {last['date']}): {e(last['meaning'])}</p>"
        body += "</section>"
    (OUT / "indicator_trends.html").write_text(page("지표 추이", body, "📉"), encoding="utf-8")
