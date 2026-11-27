"""추가 리포트: 매크로 주기 그림, 확인 항목(해야 할 것/한 것) 페이지, 지표 페이지."""
import math
from html import escape as e
import db as D
from indicators import CYCLE
from report import page, OUT, ST_ICON, KIND_ICON, CAT_ICON, CAT_ORDER

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
    svg += f"<line x1=30 y1=100 x2=490 y2=100 stroke=currentColor stroke-dasharray='4 4' opacity=.35 /><text x=492 y=104 font-size=10 fill=currentColor opacity=.6>평균</text>"
    svg += "<text x=30 y=22 font-size=10 fill=currentColor opacity=.6>▲ 과열·정점</text><text x=30 y=198 font-size=10 fill=currentColor opacity=.6>▼ 침체·저점</text>"
    for i, (name, _) in enumerate(CYCLE):
        pts = " ".join("%.1f,%.1f" % _wave_xy((i + k / 16) / n) for k in range(17))
        svg += f"<polyline points='{pts}' fill=none stroke='{COLORS[i]}' stroke-width={9 if i == ci else 5} stroke-linecap='round' opacity={1 if i == ci else .6} />"
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
    why = (f"<details open><summary><b>위치 판단 근거</b> <span class=meta>({e(cur['date'])} · 🤖 {e(cur['llm'] or '-')})</span></summary><p>{e(cur['reason'])}</p></details>") if cur else "<p class=meta>아직 위치 판단 기록이 없습니다.</p>"
    return f"<section class=card><h3>🧭 매크로 주기와 현재 위치</h3><p class=meta>곡선은 경기 순환을 단순화한 모형입니다. ●는 오늘 판단한 위치, ○는 최근 판단(마우스를 올리면 날짜).</p>{svg}{why}{det}</section>"

def _vlink(c):
    if not c["video_id"]: return "✍️ 직접 등록"
    d = c["processed_date"]
    return f"<a href='{d}.html#v-{e(c['video_id'])}'>{e((c['title'] or '')[:46])}</a>" if d else e((c["title"] or "")[:46])

LIGHT = {"confirmed": ("🟢", "예상 적중"), "partial": ("🟡", "부분 적중"), "refuted": ("🔴", "예상 빗나감"),
         "unknown": ("⚪", "판단 불가")}
LEGEND = "<p class=meta>신호등: 🟢 예상 적중 · 🟡 부분 적중 · 🔴 예상 빗나감 · ⚪ 판단 불가 · 🟠 확인 시점 지남(미확인) · ⏳ 아직 때가 아님</p>"

def _light(c):
    if c["status"] in LIGHT: return LIGHT[c["status"]]
    return ("🟠", "확인 필요") if c["check_date"] <= D.today() else ("⏳", "대기")

def _rows(rows, done=None, filt=False):
    """확인 항목 표 — 대기/완료 모두 같은 열: 신호등, 확인일, 대상, 예상, 출처 영상, 확인한 날·결과·의견."""
    h = f"<table class=num{' id=ck' if filt else ''}><tr><th>신호<th>📅 확인일<th>🎯 대상<th>🔎 확인할 것 / 영상의 예상<th>🎬 출처 영상<th>✅ 확인한 날 · 결과 · 의견</tr>"
    for c in rows:
        ic, tx = _light(c)
        if c["checked_at"]:
            res = f"<b>{e(c['checked_at'][:10])}</b><br>{e(c['result'] or '')}{('<br><span class=meta>📈 업로드→확인일 변화: ' + e(c['since_upload']) + '</span>') if c['since_upload'] else ''}<br><i>{e(c['opinion'] or '')}</i> <span class=meta>{e(c['reason'] or '')}</span>"
        else: res = "<span class=meta>아직 확인 전</span>" + (f"<br><span class=meta>{e(c['reason'])}</span>" if c["reason"] else "")
        at = (f" hidden data-st='{e(c['status'])}' data-d='{e((c['checked_at'] or '')[:10])}' data-c='{e(c['category'] or '기타')}' data-s='{e((c['category'] or '기타') + '/' + (c['subtag'] or '기타'))}'") if filt else ""
        h += f"<tr{at}><td style='text-align:center;font-size:20px' title='{tx}'>{ic}<br><span class=meta style='font-size:11px'>{tx}</span><td>{e(c['check_date'])}<td>{KIND_ICON.get(c['kind'], '')} {e(c['target'])}<td>{e(c['what_to_check'])}<br><span class=meta>예상: {e(c['expectation'])}</span>{('<br><span class=meta>근거: ' + e(c['rationale']) + '</span>') if c['rationale'] else ''}{('<br><span class=meta>🟢 예상이 맞을 때: ' + e(c['if_right']) + '</span>') if c['if_right'] else ''}{('<br><span class=meta>🔴 예상이 틀릴 때: ' + e(c['if_wrong']) + '</span>') if c['if_wrong'] else ''}<td>{_vlink(c)}<td>{res}</tr>"
    return h + "</table>"

SEL = "SELECT c.*, v.title, v.category, v.subtag, COALESCE(v.run_id, v.processed_date) AS processed_date FROM checks c LEFT JOIN videos v ON v.id=c.video_id"

def _count_table(con, only_pending):
    """확인 항목 상태별 개수 표 (⏳ 대기 페이지는 대기·전체, ✅ 확인한 것 페이지는 판정별 개수)."""
    n = dict(con.execute("SELECT status, count(*) FROM checks GROUP BY status").fetchall())
    total = sum(n.values())
    names = {"pending": "대기 중", "confirmed": "확인됨(예상대로)", "refuted": "틀림", "partial": "일부만 맞음", "unknown": "판단 불가"}
    keys = ["pending"] if only_pending else [k for k in names if k != "pending" and n.get(k)]
    rows = "".join(f"<tr><td>{ST_ICON.get(k, '')} {names[k]}<td align=right>{n.get(k, 0):,}개</tr>" for k in keys)
    rows += f"<tr><td><b>전체 확인 항목</b><td align=right><b>{total:,}개</b></tr>"
    if not only_pending: rows += f"<tr><td>확인한 것 합계<td align=right>{total - n.get('pending', 0):,}개</tr>"
    return f"<section class=card><h3>🔢 개수</h3><table>{rows}</table></section>"

def _done_filter(dn):
    """확인한 것 페이지의 선택 칸(주제·신호·기간). 옵션 글자 뒤의 '(개수)-오늘 확인된 개수' 는 JS 가 붙인다."""
    cats, subs = {}, {}
    for r in dn:
        c, sb = r["category"] or "기타", r["subtag"] or "기타"
        cats[c] = cats.get(c, 0) + 1; subs.setdefault(c, {})[sb] = subs.setdefault(c, {}).get(sb, 0) + 1
    order = sorted(cats, key=lambda c: CAT_ORDER.index(c) if c in CAT_ORDER else len(CAT_ORDER))
    opt = lambda v, label: f"<option value='{e(str(v))}' data-l='{e(label)}'>{e(label)}</option>"
    topic = opt("all", "모두")
    for c in order:
        topic += opt(f"c:{c}", f"{CAT_ICON.get(c, '📌')} {c}")
        for sb in sorted(subs[c], key=lambda k: (-subs[c][k], k)): topic += opt(f"s:{c}/{sb}", f"\u00a0\u00a0└ {sb}")
    sig = opt("all", "모두") + "".join(opt(k, f"{ic} {tx}") for k, (ic, tx) in LIGHT.items())
    rec = opt("all", "모두") + "".join(opt(d, t) for d, t in ((0, "오늘"), (7, "최근 1주일"), (30, "최근 1개월"), (90, "최근 3개월"), (180, "최근 6개월"), (365, "최근 1년")))
    return (f"<div class=bar><label>🏷️ 주제 <select class=fk data-k=t id=f-topic>{topic}</select></label><label>🚦 신호 <select class=fk data-k=s id=f-sig>{sig}</select></label>"
            f"<label>📅 기간(확인한 날) <select class=fk data-k=r id=f-recent>{rec}</select></label></div>")

_DONE_JS = """<script>(function(){
var rows=[].slice.call(document.querySelectorAll('#ck tr[data-st]')),sels=[].slice.call(document.querySelectorAll('select.fk')),info=document.getElementById('ck-info');
function ymd(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
var td=ymd(new Date());
function co(v){var d=new Date();d.setDate(d.getDate()-(+v));return ymd(d)}
function match(x,k,v){if(v==='all')return true;
 if(k==='t'){var p=v.slice(0,2),q=v.slice(2);return p==='c:'?x.dataset.c===q:x.dataset.s===q}
 if(k==='s')return x.dataset.st===v;
 return x.dataset.d>=co(v)}
sels.forEach(function(s){var k=s.dataset.k;[].forEach.call(s.options,function(o){var n=0,m=0;rows.forEach(function(x){if(match(x,k,o.value)){n++;if(x.dataset.d===td)m++}});o.textContent=o.dataset.l+' ('+n+')-'+m})});
function apply(){var n=0;rows.forEach(function(x){var ok=sels.every(function(s){return match(x,s.dataset.k,s.value)});x.hidden=!ok;if(ok)n++});
 info.textContent='조건에 맞는 항목 '+n+'개 / 전체 '+rows.length+'개'}
sels.forEach(function(s){s.onchange=apply});apply()})();
</script>"""

def build_checks(con):
    today = D.today()
    pend = con.execute(SEL + " WHERE c.status='pending' ORDER BY c.check_date, c.id").fetchall()
    due = [c for c in pend if c["check_date"] <= today]
    body = f"<h1>⏳ 앞으로 확인할 것</h1><p class=meta>시간순(확인일 빠른 순) · 미확인 {len(pend)}개 · <a href='index.html'>🏠 홈</a> · <a href='checks_done.html'>확인한 것 ›</a> · <a href='indicators.html'>지표 ›</a></p>" + LEGEND
    if due: body += f"<section class='card due'><h3>⏰ 지금 확인할 시점이 된 것 ({len(due)})</h3>{_rows(due)}</section>"
    body += f"<section class=card><h3>🗓️ 전체 (시간순)</h3>{_rows(pend)}</section>"
    body += _count_table(con, True)
    (OUT / "checks_pending.html").write_text(page("앞으로 확인할 것", body, "⏳"), encoding="utf-8")
    dn = con.execute(SEL + " WHERE c.status!='pending' ORDER BY c.checked_at DESC, c.id").fetchall()
    body = f"<h1>✅ 확인한 것</h1><p class=meta>확인 {len(dn)}개 · 확인한 날짜 최신순 · 선택 칸 옆 숫자는 (해당 개수)-오늘 확인된 개수 · <a href='index.html'>🏠 홈</a> · <a href='checks_pending.html'>‹ 앞으로 확인할 것</a></p>" + LEGEND
    body += _done_filter(dn)
    body += f"<p class=meta id=ck-info></p><section class=card>{_rows(dn, filt=True) if dn else '<p class=meta>아직 없습니다.</p>'}</section>"
    body += _count_table(con, False)
    import opinions as OPN
    (OUT / "checks_done.html").write_text(page("확인한 것", OPN.LIST_CSS + body + _DONE_JS, "✅"), encoding="utf-8")

def _fmt(v): return "-" if v is None else (f"{v:,.2f}".rstrip("0").rstrip("."))

IND_LEGEND = ("<p class=meta><b>범례</b> · ⭐ 핵심 지표(거시 판단에 중요해 먼저 보는 지표, 설명 단계에서 Claude가 지정) · "
              "🚨 경고(전 거래일 대비 ±5% 이상 급변) · ⚠️ 임계값(경고 기준선을 넘거나 되돌아옴) · 🔄 방향 전환(상승↔하락 추세가 바뀜) · "
              "▲▼▬ 최근 1주 추세(월간 지표는 직전 발표 대비) · 🕰️ 기준일이 90일 넘은 오래된 값</p>")

def _stale(vd):
    import datetime
    try: return (datetime.date.today() - datetime.date.fromisoformat((vd or "")[:10])).days > 90
    except Exception: return False

def _ind_card(i, v, srcs, count=True):
    sig = f"{SIG_ICON.get(v['signal'], '')} <b>{SIG_TXT.get(v['signal'], '')}</b> {e(v['signal_reason'] or '')}" if v["signal"] else ""
    arrow = {"up": "▲", "down": "▼", "flat": "▬"}.get(v["direction"], "·")
    chg = f" ({v['change_pct']:+.2f}%)" if v["change_pct"] is not None else ""
    import indfilter as F
    h = f"<tr {F.attrs(i, count)}><td><b>{e(i['name'])}</b><br><span class=meta>{e(i['category'] or '')}{' · ⭐' if i['importance'] == 'high' else ''}</span>"
    h += f"<td>{arrow} {e(v['value_text'] or _fmt(v['value']))}{e(chg)}<br><span class=meta>{'🕰️ 오래된 값 · ' if _stale(v['value_date']) else ''}기준일 {e(v['value_date'] or '-')}; 직전 {_fmt(v['prev_value'])}</span>"
    h += f"<td>{sig or '<span class=meta>변화 없음</span>'}<br>{e(v['meaning'] or '')}{(" <span class=meta>🤖 " + e(v['llm']) + "</span>") if v['llm'] and v['meaning'] else ''}"
    h += f"<td><details><summary>설명·해석·기준값 <span class=meta>🤖 {e(i['enrich_llm'] or '-')}</span></summary><p>{e(i['description'] or '')}</p><p><b>해석</b> {e(i['interpretation'] or '')}</p><p><b>기준(평균/균형)</b> {e(i['baseline'] or '')}</p>"
    h += f"<p class=meta>시세 출처 매핑: 🤖 {e(i['map_llm'] or '-')}</p><p class=meta>출처 영상: " + ", ".join(f"<a href='{e(s['processed_date'])}.html#v-{e(s['video_id'])}'>{e((s['title'] or '')[:24])}</a>" for s in srcs[:5]) + "</p></details></tr>"
    return h

def _latest(con, name):
    return con.execute("SELECT v.value, v.value_text, v.value_date FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id WHERE i.name=? AND v.value IS NOT NULL ORDER BY v.date DESC LIMIT 1", (name,)).fetchone()

def pbr_block(con):
    """한국·미국 증시의 현재 PBR 과 선행 PBR 을 나란히(DB 의 최신 값). 값이 없으면 '수집 미연결'로 표시한다."""
    def cell(name):
        x = _latest(con, name)
        return (f"<b>{x['value']:.2f}배</b><br><span class=meta>기준일 {e(x['value_date'] or '-')}</span>" if x else "<span class=meta>값 없음 (수집 미연결)</span>"), (x["value"] if x else None)
    rows = ""
    for mk, cur, fwd in (("🇰🇷 한국 (코스피)", "한국 코스피 현재 PBR", "한국 코스피 선행 PBR"), ("🇺🇸 미국 (S&P 500)", "미국 S&P500 현재 PBR", "미국 S&P500 선행 PBR")):
        (c, cv), (f, fv) = cell(cur), cell(fwd)
        gap = f"{(fv - cv) / cv * 100:+.1f}%" if cv and fv else "<span class=meta>-</span>"
        rows += f"<tr><td>{mk}<td>{c}<td>{f}<td>{gap}</tr>"
    return ("<section class=card><h3>📐 PBR 비교 — 현재 vs 선행</h3><table><tr><th>시장<th>현재 PBR<th>선행 PBR<th>선행 ÷ 현재 − 1</tr>" + rows +
            "</table><p class=meta>선행 PBR 은 향후 12개월 예상 순자산 기준이라 애널리스트 컨센서스(유료·로그인 자료)가 필요합니다. 연결되기 전까지는 현재 PBR 만 기록됩니다.</p></section>")

def seed_pending_block(con):
    """기본 지표(indicator_seed) 중 자동 수집이 아직 연결되지 않아 값이 없는 것."""
    import indicator_seed as S
    names = [s["name"] for s in S.SEED if s["source"] == "none"]
    if not names: return ""
    import indfilter as F
    items = "".join(f"<li {F.attrs({'name': r['name'], 'category': r['category'], 'source': 'none', 'symbol': ''}, False)}><b>{e(r['name'])}</b> <span class=meta>{e(r['category'] or '')}</span></li>" for r in con.execute(f"SELECT name,category FROM indicators WHERE name IN ({','.join('?' * len(names))}) ORDER BY category,name", names))
    return f"<section class=card><h3>📭 값이 아직 없는 기본 지표 ({len(names)})</h3><p class=meta>공식 OpenAPI 인증키(한국부동산원 R-ONE·한국은행 ECOS·국토교통부)나 유료 컨센서스가 있어야 자동 수집할 수 있어 아직 연결되지 않았습니다. 지표 정의는 DB에 등록돼 있습니다.</p><ul>{items}</ul></section>"

def pinned_block(con, head, srcs):
    """config.toml pinned_indicators: 꼭 챙겨 볼 지표 묶음. 각 지표의 가장 최근 값을 보여 준다(그날 값이 없어도)."""
    import tomllib, pathlib, indicators as I
    try: groups = tomllib.loads((pathlib.Path(__file__).resolve().parent / "config.toml").read_text(encoding="utf-8")).get("pinned_indicators") or []
    except Exception: return ""
    out = ""
    for g in groups:
        cards, missing = "", []
        for name in g.get("indicators", []):
            row = con.execute("SELECT id FROM indicators WHERE name=?", (name,)).fetchone()
            r = row and con.execute("""SELECT i.*, v.value, v.value_text, v.value_date, v.prev_value, v.change_pct, v.direction, v.signal, v.signal_reason, v.meaning, v.llm
                                       FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id WHERE i.id=? ORDER BY v.date DESC LIMIT 1""", (I.root_id(con, row["id"]),)).fetchone()
            if r: cards += _ind_card(r, r, srcs(r["id"]), False)
            else: missing.append(name)
        out += f"<h4>{e(g.get('title', ''))}</h4><p class=meta>{e(g.get('why', ''))}</p>" + (head + cards + "</table>" if cards else "")
        if missing: out += f"<p class=meta>값이 아직 없음: {e(', '.join(missing))}</p>"
    return f"<section class=card id=sec-pin><h3>🎯 핵심 확인 지표</h3>{out}</section>" if out else ""

def build_indicators(con):
    last = con.execute("SELECT max(date) FROM indicator_values").fetchone()[0]
    body = "<h1>📊 지표 대시보드</h1><p class=meta><a href='index.html'>🏠 홈</a> · <a href='checks_pending.html'>앞으로 확인할 것</a> · <a href='checks_done.html'>확인한 것</a> · <a href='indicator_trends.html'>📉 지표 추이(그래프·상황 설명)</a> · <a href='linkage.html'>🔗 지표 연결(이어진 지표를 묶어 분석)</a></p>" + IND_LEGEND + macro_block(con)
    if not last:
        body += "<p class=meta>아직 수집된 지표 값이 없습니다(일일 실행에서 수집).</p>"
        (OUT / "indicators.html").write_text(page("지표", body, "📊"), encoding="utf-8"); return
    rows = con.execute("""SELECT i.*, v.value, v.value_text, v.value_date, v.prev_value, v.change_pct, v.direction, v.signal, v.signal_reason, v.meaning, v.llm
                          FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id WHERE v.date=? ORDER BY i.importance DESC, i.category, i.name""", (last,)).fetchall()
    srcs = lambda iid: con.execute("SELECT s.video_id, vd.title, COALESCE(vd.run_id, vd.processed_date) AS processed_date FROM indicator_sources s JOIN videos vd ON vd.id=s.video_id WHERE s.indicator_id=?", (iid,)).fetchall()
    body += pbr_block(con)
    head = "<table class=num><tr><th>지표<th>값 / 전일 대비 · 1주 추세<th>신호 · 의미<th>설명</tr>"
    changed = sorted([r for r in rows if r["signal"]], key=lambda r: ["warning", "threshold", "direction"].index(r["signal"]))
    import indfilter as F
    from report import CAT_ICON as CI
    body += F.BAR
    body += pinned_block(con, head, srcs)
    body += f"<section class='card due' id=sec-chg><h3>🚨 {e(last)} 변화·경고 (<span data-count-of=sec-chg>{len(changed)}</span>)</h3><p class=meta>값이 조금 바뀐 것이 아니라 방향이 바뀌었거나 임계값을 넘거나 경고인 것만 · 위의 국가·분류 선택이 여기에도 적용됩니다</p>"
    body += (head + "".join(_ind_card(r, r, srcs(r["id"]), False) for r in changed) + "</table>") if changed else "<p class=meta>오늘은 해당 항목이 없습니다.</p>"
    body += "</section>"
    rows = sorted(rows, key=lambda r: F.sort_key(r) + (r["importance"] != "high", r["name"]))
    ck, ckc, tr_ = {}, {}, ""
    for r in rows:
        k, c = F.country_of(r), r["category"] or "기타"
        ck[k] = ck.get(k, 0) + 1; ckc[(k, c)] = ckc.get((k, c), 0) + 1
    cur = None
    for r in rows:
        k, c = F.country_of(r), r["category"] or "기타"
        if cur is None or cur[0] != k: tr_ += F.row_head(k, f"{F.CNAME[k]} ({ck[k]})")
        if cur != (k, c): tr_ += F.row_head(f"{k}|{e(c)}", f"&nbsp;&nbsp;{CI.get(c, '📌')} {e(c)} ({ckc[(k, c)]})")
        cur = (k, c); tr_ += _ind_card(r, r, srcs(r["id"]))
    body += f"<section class=card id=sec-all><h3>📋 전체 지표·종목 (<span data-count-of=sec-all>{len(rows)}</span>) — 위 항목 포함</h3>{head}{tr_}</table></section>"
    body += seed_pending_block(con)
    pend = con.execute("SELECT count(*) FROM indicators WHERE active=1").fetchone()[0]
    body += f"<p class=meta>등록된 지표 {pend}개 · 값을 구하지 못한 지표는 그날 건너뜁니다 · 값은 모델이 아는 최근 값이며 실시간이 아닙니다(🕰️ 표시는 기준일이 90일 넘게 오래된 값 — 경고도 참고용으로만 볼 것).</p>"
    import indfilter as F
    body += F.js()
    (OUT / "indicators.html").write_text(page("지표 대시보드", body, "📊"), encoding="utf-8")

def build(con):
    build_checks(con); build_indicators(con)
