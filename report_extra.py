"""추가 리포트: 매크로 주기 그림, 확인 항목(해야 할 것/한 것) 페이지, 지표 페이지."""
import math
from html import escape as e
import db as D
from indicators import CYCLE
from report import page, OUT, ST_ICON, KIND_ICON, CAT_ICON

SIG_ICON = {"warning": "🚨", "threshold": "⚠️", "direction": "🔄"}
SIG_TXT = {"warning": "경고", "threshold": "임계값", "direction": "방향 전환"}
COLORS = ["#4aa36c", "#2b9d8f", "#d9b02b", "#d9822b", "#c0392b", "#7b5ea7"]

def _arc(cx, cy, r, a0, a1):
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    return f"M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}"

def _wave_xy(t, W=460, X0=30, CY=100, A=62):
    """t(0~1) -> 화면 좌표. 바닥(t=0,1) -> 상승 -> 정점(t=0.5) -> 하강. y = -cos(2πt)."""
    return X0 + t * W, CY + A * math.cos(2 * math.pi * t)

def macro_block(con, day=None):
    """매크로 주기를 사인 곡선으로 보여준다: 6단계를 색으로 나누고, 현재 위치(●)와 최근 위치(○)를 곡선 위에 찍는다. 설명은 접어서 표시."""
    hist = con.execute("SELECT * FROM macro_daily WHERE date<=? ORDER BY date DESC LIMIT 8", (day or "9999-12-31",)).fetchall()
    cur = hist[0] if hist else None
    ci = cur["phase_index"] if cur else None
    n = len(CYCLE)
    svg = "<svg viewBox='0 0 520 232' width='100%' style='max-width:640px' role=img aria-label='매크로 주기 곡선'>"
    svg += f"<line x1=30 y1=100 x2=490 y2=100 stroke=currentColor stroke-dasharray='4 4' opacity=.35/><text x=492 y=104 font-size=10 fill=currentColor opacity=.6>평균</text>"
    svg += "<text x=30 y=22 font-size=10 fill=currentColor opacity=.6>▲ 과열·정점</text><text x=30 y=198 font-size=10 fill=currentColor opacity=.6>▼ 침체·저점</text>"
    for i, (name, _) in enumerate(CYCLE):
        pts = " ".join("%.1f,%.1f" % _wave_xy((i + k / 16) / n) for k in range(17))
        svg += f"<polyline points='{pts}' fill=none stroke='{COLORS[i]}' stroke-width={9 if i == ci else 5} stroke-linecap=round opacity={1 if i == ci else .6}/>"
        mx, _y = _wave_xy((i + .5) / n)
        svg += f"<text x={mx:.0f} y=222 text-anchor=middle font-size=11 fill=currentColor font-weight={'700' if i == ci else '400'}>{i + 1}. {e(name)}</text>"
    for h in hist[1:]:                                    # 최근 위치(흐리게)
        x, y = _wave_xy((h["phase_index"] + .5) / n)
        svg += f"<circle cx={x:.1f} cy={y:.1f} r=5 fill=none stroke=currentColor opacity=.45><title>{e(h['date'])} {e(h['phase'])}</title></circle>"
    if ci is not None:
        x, y = _wave_xy((ci + .5) / n)
        up = ci in (0, 1, 2)
        svg += f"<circle cx={x:.1f} cy={y:.1f} r=9 fill='{COLORS[ci]}' stroke=#fff stroke-width=3 />"
        ty = y - 18 if y > 60 else y + 30
        svg += f"<text x={x:.0f} y={ty:.0f} text-anchor=middle font-size=12 font-weight=700 fill=currentColor>현재: {e(CYCLE[ci][0])} {'↗ 상승 국면' if up else '↘ 하강 국면'}</text>"
    svg += "</svg>"
    det = "".join(f"<details><summary><b>{i + 1}. {e(n_)}</b>{' ← 현재' if i == ci else ''}</summary><p>{e(d)}</p></details>" for i, (n_, d) in enumerate(CYCLE))
    why = (f"<details open><summary><b>위치 판단 근거</b> <span class=meta>({e(cur['date'])})</span></summary><p>{e(cur['reason'])}</p></details>") if cur else "<p class=meta>아직 위치 판단 기록이 없습니다.</p>"
    return f"<section class=card><h3>🧭 매크로 주기와 현재 위치</h3><p class=meta>곡선은 경기 순환을 단순화한 모형입니다. ●는 오늘 판단한 위치, ○는 최근 판단(마우스를 올리면 날짜).</p>{svg}{why}{det}</section>"

def _vlink(c):
    d = c["processed_date"]
    return f"<a href='{d}.html#v-{e(c['video_id'])}'>{e((c['title'] or '')[:46])}</a>" if d else e((c["title"] or "")[:46])

LIGHT = {"confirmed": ("🟢", "예상 적중"), "partial": ("🟡", "부분 적중"), "refuted": ("🔴", "예상 빗나감"),
         "unknown": ("⚪", "판단 불가")}
LEGEND = "<p class=meta>신호등: 🟢 예상 적중 · 🟡 부분 적중 · 🔴 예상 빗나감 · ⚪ 판단 불가 · 🟠 확인 시점 지남(미확인) · ⏳ 아직 때가 아님</p>"

def _light(c):
    if c["status"] in LIGHT: return LIGHT[c["status"]]
    return ("🟠", "확인 필요") if c["check_date"] <= D.today() else ("⏳", "대기")

def _rows(rows, done=None):
    """확인 항목 표 — 대기/완료 모두 같은 열: 신호등, 확인일, 대상, 예상, 출처 영상, 확인한 날·결과·의견."""
    h = "<table><tr><th>신호<th>📅 확인일<th>🎯 대상<th>🔎 확인할 것 / 영상의 예상<th>🎬 출처 영상<th>✅ 확인한 날 · 결과 · 의견</tr>"
    for c in rows:
        ic, tx = _light(c)
        if c["checked_at"]:
            res = f"<b>{e(c['checked_at'][:10])}</b><br>{e(c['result'] or '')}<br><i>{e(c['opinion'] or '')}</i> <span class=meta>{e(c['reason'] or '')}</span>"
        else: res = "<span class=meta>아직 확인 전</span>" + (f"<br><span class=meta>{e(c['reason'])}</span>" if c["reason"] else "")
        h += f"<tr><td style='text-align:center;font-size:20px' title='{tx}'>{ic}<br><span class=meta style='font-size:11px'>{tx}</span><td>{e(c['check_date'])}<td>{KIND_ICON.get(c['kind'], '')} {e(c['target'])}<td>{e(c['what_to_check'])}<br><span class=meta>예상: {e(c['expectation'])}</span><td>{_vlink(c)}<td>{res}</tr>"
    return h + "</table>"

SEL = "SELECT c.*, v.title, v.processed_date FROM checks c JOIN videos v ON v.id=c.video_id"

def build_checks(con):
    today = D.today()
    pend = con.execute(SEL + " WHERE c.status='pending' ORDER BY c.check_date, c.id").fetchall()
    due = [c for c in pend if c["check_date"] <= today]
    body = f"<h1>⏳ 앞으로 확인할 것</h1><p class=meta>시간순(확인일 빠른 순) · 미확인 {len(pend)}개 · <a href='index.html'>목록</a> · <a href='checks_done.html'>확인한 것 ›</a> · <a href='indicators.html'>지표 ›</a></p>" + LEGEND
    if due: body += f"<section class='card due'><h3>⏰ 지금 확인할 시점이 된 것 ({len(due)})</h3>{_rows(due)}</section>"
    body += f"<section class=card><h3>🗓️ 전체 (시간순)</h3>{_rows(pend)}</section>"
    (OUT / "checks_pending.html").write_text(page("앞으로 확인할 것", body), encoding="utf-8")
    dn = con.execute(SEL + " WHERE c.status!='pending' ORDER BY c.checked_at DESC, c.id").fetchall()
    tdy = [c for c in dn if (c["checked_at"] or "").startswith(today)]
    body = f"<h1>✅ 확인한 것</h1><p class=meta>확인 {len(dn)}개 · 오늘 확인한 것이 맨 앞, 그 아래에 오늘 것을 포함한 전체를 시간순으로 · <a href='index.html'>목록</a> · <a href='checks_pending.html'>‹ 앞으로 확인할 것</a></p>" + LEGEND
    body += f"<section class='card'><h3>🆕 오늘({today}) 확인한 것 ({len(tdy)})</h3>{_rows(tdy) if tdy else '<p class=meta>오늘 확인한 항목이 없습니다. <code>uv run check.py set ID --status ...</code> 로 기록합니다.</p>'}</section>"
    body += f"<section class=card><h3>🗓️ 전체 (확인한 순서, 오래된 것부터)</h3>{_rows(sorted(dn, key=lambda c: (c['checked_at'] or '', c['id']))) if dn else '<p class=meta>아직 없습니다.</p>'}</section>"
    (OUT / "checks_done.html").write_text(page("확인한 것", body), encoding="utf-8")

def _fmt(v): return "-" if v is None else (f"{v:,.2f}".rstrip("0").rstrip("."))

IND_LEGEND = ("<p class=meta><b>범례</b> · ⭐ 핵심 지표(거시 판단에 중요해 먼저 보는 지표, 설명 단계에서 Claude가 지정) · "
              "🚨 경고(전 거래일 대비 ±5% 이상 급변) · ⚠️ 임계값(경고 기준선을 넘거나 되돌아옴) · 🔄 방향 전환(상승↔하락 추세가 바뀜) · "
              "▲▼▬ 최근 1주 추세(월간 지표는 직전 발표 대비) · 🕰️ 기준일이 90일 넘은 오래된 값</p>")

def _stale(vd):
    import datetime
    try: return (datetime.date.today() - datetime.date.fromisoformat((vd or "")[:10])).days > 90
    except Exception: return False

def _ind_card(i, v, srcs):
    sig = f"{SIG_ICON.get(v['signal'], '')} <b>{SIG_TXT.get(v['signal'], '')}</b> {e(v['signal_reason'] or '')}" if v["signal"] else ""
    arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(v["direction"], "·")
    chg = f" ({v['change_pct']:+.2f}%)" if v["change_pct"] is not None else ""
    h = f"<tr><td><b>{e(i['name'])}</b><br><span class=meta>{e(i['category'] or '')}{' · ⭐' if i['importance'] == 'high' else ''}</span>"
    h += f"<td>{arrow} {e(v['value_text'] or _fmt(v['value']))}{e(chg)}<br><span class=meta>{'🕰️ 오래된 값 · ' if _stale(v['value_date']) else ''}기준일 {e(v['value_date'] or '-')}; 직전 {_fmt(v['prev_value'])}</span>"
    h += f"<td>{sig or '<span class=meta>변화 없음</span>'}<br>{e(v['meaning'] or '')}"
    h += f"<td><details><summary>설명·해석·기준값</summary><p>{e(i['description'] or '')}</p><p><b>해석</b> {e(i['interpretation'] or '')}</p><p><b>기준(평균/균형)</b> {e(i['baseline'] or '')}</p>"
    h += "<p class=meta>출처 영상: " + ", ".join(f"<a href='{e(s['processed_date'])}.html#v-{e(s['video_id'])}'>{e((s['title'] or '')[:24])}</a>" for s in srcs[:5]) + "</p></details></tr>"
    return h

def build_indicators(con):
    last = con.execute("SELECT max(date) FROM indicator_values").fetchone()[0]
    body = "<h1>📊 지표 대시보드</h1><p class=meta><a href='index.html'>목록</a> · <a href='checks_pending.html'>앞으로 확인할 것</a> · <a href='checks_done.html'>확인한 것</a></p>" + IND_LEGEND + macro_block(con)
    if not last:
        body += "<p class=meta>아직 수집된 지표 값이 없습니다(일일 실행에서 수집).</p>"
        (OUT / "indicators.html").write_text(page("지표", body), encoding="utf-8"); return
    rows = con.execute("""SELECT i.*, v.value, v.value_text, v.value_date, v.prev_value, v.change_pct, v.direction, v.signal, v.signal_reason, v.meaning
                          FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id WHERE v.date=? ORDER BY i.importance DESC, i.category, i.name""", (last,)).fetchall()
    srcs = lambda iid: con.execute("SELECT s.video_id, vd.title, vd.processed_date FROM indicator_sources s JOIN videos vd ON vd.id=s.video_id WHERE s.indicator_id=?", (iid,)).fetchall()
    head = "<table><tr><th>지표<th>값 / 전일 대비 · 1주 추세<th>신호 · 의미<th>설명</tr>"
    changed = sorted([r for r in rows if r["signal"]], key=lambda r: ["warning", "threshold", "direction"].index(r["signal"]))
    body += f"<section class='card due'><h3>🚨 {e(last)} 변화·경고 ({len(changed)})</h3><p class=meta>값이 조금 바뀐 것이 아니라 방향이 바뀌었거나 임계값을 넘거나 경고인 것만</p>"
    body += (head + "".join(_ind_card(r, r, srcs(r["id"])) for r in changed) + "</table>") if changed else "<p class=meta>오늘은 해당 항목이 없습니다.</p>"
    body += "</section>"
    body += f"<section class=card><h3>📋 전체 지표·종목 ({len(rows)}) — 위 항목 포함</h3>{head}{''.join(_ind_card(r, r, srcs(r['id'])) for r in rows)}</table></section>"
    pend = con.execute("SELECT count(*) FROM indicators WHERE active=1").fetchone()[0]
    body += f"<p class=meta>등록된 지표 {pend}개 · 값을 구하지 못한 지표는 그날 건너뜁니다 · 값은 모델이 아는 최근 값이며 실시간이 아닙니다(🕰️ 표시는 기준일이 90일 넘게 오래된 값 — 경고도 참고용으로만 볼 것).</p>"
    (OUT / "indicators.html").write_text(page("지표 대시보드", body), encoding="utf-8")

def build(con):
    build_checks(con); build_indicators(con)
