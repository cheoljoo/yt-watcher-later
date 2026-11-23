"""선행지수 정리 페이지 (reports/leading.html).

영상에서 나온 '무엇이 무엇에 몇 개월 선행하는가'를 정리하고, 같은 쌍을 DB 의 장기 시계열(leading_series)로 그려
선행 시차를 슬라이더로 직접 맞춰 볼 수 있게 한다. 웹 호출은 leading_fetch.py 에서만 한다.

  uv run leading_fetch.py     # 시계열 새로 받기 (월 1회쯤이면 충분)
  uv run leading.py           # reports/leading.html 만들기 (report.build_all 도 호출)
"""
import datetime, json, math, statistics, sys
from html import escape as e
import db as D
import leading_fetch as F
import leading_data as S

START = "2000-01-01"          # 그래프·상관 계산 시작
LAGS = list(range(-12, 13))   # 선행 시차(개월). +k = 앞 지표를 k개월 뒤로 밀어 맞춤


def months_between(a, b): return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])
def add_m(m, k):
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return f"{t // 12}-{t % 12 + 1:02d}-01"


def corr(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def xcorr(A, B, start=START, minn=30):
    """앞 지표 A 를 k개월 뒤로 밀어(A[t-k]) 따라가는 지표 B[t] 와 비교한 상관. {k: r}"""
    out = {}
    for k in LAGS:
        xs, ys = [], []
        for t, v in B.items():
            if t < start: continue
            s = add_m(t, -k)
            if s in A: xs.append(A[s]); ys.append(v)
        r = corr(xs, ys) if len(xs) >= minn else None
        out[k] = None if r is None else round(r, 3)
    return out


def zigzag(series, thr):
    """thr 이상 되돌린 정점(P)·저점(T) 목록 [(종류, 월, 값)] 과 아직 확정 안 된 마지막 극값."""
    ks = sorted(series); out = []
    hi = lo = (ks[0], series[ks[0]]); d = 0; ext = hi
    for m in ks[1:]:
        v = series[m]
        if d == 0:
            if v > hi[1]: hi = (m, v)
            if v < lo[1]: lo = (m, v)
            if hi[1] - v >= thr: out.append(("P",) + hi); d = -1; ext = (m, v)
            elif v - lo[1] >= thr: out.append(("T",) + lo); d = 1; ext = (m, v)
        elif d == 1:
            if v >= ext[1]: ext = (m, v)
            elif ext[1] - v >= thr: out.append(("P",) + ext); d = -1; ext = (m, v)
        else:
            if v <= ext[1]: ext = (m, v)
            elif v - ext[1] >= thr: out.append(("T",) + ext); d = 1; ext = (m, v)
    return out, ext, d



SIG_DDL = """CREATE TABLE IF NOT EXISTS leading_signal(sid TEXT, asof TEXT, name TEXT, last_month TEXT, value REAL, d1 REAL, d3 REAL, d6 REAL, d12 REAL,
  state TEXT, state_label TEXT, grp TEXT, score REAL, peak_month TEXT, PRIMARY KEY(sid, asof));
CREATE TABLE IF NOT EXISTS leading_regime(asof TEXT PRIMARY KEY, score REAL, regime TEXT, detail_json TEXT);"""
LOGSIDS = {"kospi", "spx", "dubai", "kr_exp_ma3"}      # 가격·금액 계열은 로그 변화(%)로 방향을 본다


def classify(sid, d):
    """월별 값 d 로 방향 상태를 판정한다. 기준은 '최근 15년 월간 변화의 중앙값(noise)' — 지표마다 단위가 달라도 같은 잣대가 된다.
    3개월 변화가 noise 이상이면 오르는 중/내려오는 중, 그 안이면 6개월 변화로 정점권·바닥권·방향 없음을 가른다."""
    ks = sorted(d); m = ks[-1]
    w = {k: (100 * math.log(d[k]) if sid in LOGSIDS and d[k] > 0 else d[k]) for k in ks}
    at = lambda k: w.get(add_m(m, -k))
    diffs = [abs(w[a] - w[add_m(a, -1)]) for a in ks[-180:] if add_m(a, -1) in w]
    noise = max(statistics.median(diffs) if diffs else 0, 1e-9)
    ch = lambda k: None if at(k) is None else w[m] - at(k)
    d1, d3, d6, d12 = ch(1), ch(3), ch(6), ch(12)
    prev3 = None if at(3) is None or at(6) is None else at(3) - at(6)
    win = [k for k in ks if k >= add_m(m, -12)]
    idx = lambda k: int(k[:4]) * 12 + int(k[5:7])
    pk = max(win, key=lambda k: (round(w[k], 9), idx(k))); tr = min(win, key=lambda k: (round(w[k], 9), -idx(k)))      # 같은 값이면 더 최근 달
    ago_pk, ago_tr = months_between(pk, m), months_between(tr, m)
    rise_pk = w[pk] - w.get(add_m(pk, -6), w[pk]); fall_tr = w.get(add_m(tr, -6), w[tr]) - w[tr]
    if d3 is None: state = "flat"
    elif 1 <= ago_pk <= 4 and w[pk] - w[m] <= noise and rise_pk >= 2 * noise and d1 is not None and d1 <= 0: state = "topping"     # 오름이 멈추고 최고점 근처에서 버티는 중
    elif d3 <= -noise: state = "peak_down" if ago_pk <= 9 and rise_pk >= noise else "down"
    elif d3 >= noise:
        if ago_tr <= 6 and fall_tr >= noise: state = "trough_up"
        elif prev3 and prev3 > 0 and d3 < 0.5 * prev3: state = "slowing"
        else: state = "up"
    else:
        state = "topping" if (d6 or 0) >= noise else "bottoming" if (d6 or 0) <= -noise else "flat"
    return {"sid": sid, "month": m, "value": d[m], "state": state, "d1": d1, "d3": d3, "d6": d6, "d12": d12, "noise": noise,
            "peak": pk, "ago_peak": ago_pk, "trough": tr, "ago_trough": ago_tr}


def regime_of(score):
    for lo, name, icon, stock, acts, vids in S.REGIMES:
        if score >= lo: return name, icon, stock, acts, vids
    return S.REGIMES[-1][1:]


def turning_lags(lead, fol, thr):
    """같은 종류의 전환점끼리 짝지어 (따라가는 쪽 월 − 앞서는 쪽 월) = 앞선 개월 수."""
    zl, _, _ = zigzag(lead, thr); zf, _, _ = zigzag(fol, thr); rows = []
    for t, m, v in zf:
        if m < "1995-01-01": continue
        c = [(abs(months_between(m2, m)), m2) for t2, m2, _ in zl if t2 == t and abs(months_between(m2, m)) <= 12]
        if c:
            m2 = min(c)[1]; rows.append((t, m2, m, months_between(m2, m)))
    return rows


def verdict(claim, best, rbest, sign):
    """영상 주장 시차와 데이터상 최적 시차를 비교해 한 줄 판정 (class, 문구)."""
    if rbest is None: return ("na", "계산할 값이 부족")
    if sign * rbest < 0.3: return ("weak", "상관이 약해 확인하기 어려움")
    if best < 0 and claim >= 0: return ("rev", f"오히려 따라가는 쪽이 {-best}개월 먼저")
    d = abs(best - claim)
    if claim == 0: return ("ok", "같은 방향으로 움직임") if abs(best) <= 1 else ("part", f"최적은 {best:+d}개월 어긋남")
    if d <= 1: return ("ok", "영상 주장과 일치")
    if d <= 3: return ("part", "대체로 일치 (시차는 조금 다름)")
    return ("diff", "시차가 다르게 나옴")
def fcls(g):
    """방향 상태의 색 클래스: 경기·위험선호에 우호면 up(초록), 비우호면 down(빨강), 중립이면 flat."""
    return "up" if g["fav"] > 0.1 else "down" if g["fav"] < -0.1 else "flat"
VCLS = {"ok": "🟢", "part": "🟡", "weak": "⚪", "rev": "🔴", "diff": "🔴", "na": "⚪"}


def yt(i):
    v = S.VIDEOS.get(i)
    return f"<a href='https://www.youtube.com/watch?v={e(i)}' target=_blank title='{e(v[2]) if v else ''}'>{e(v[0]) if v else i} {e(v[1][2:]) if v else ''}</a>" if v else ""


# ───────────────────────── 도식 (SVG) ─────────────────────────
def lead_lag_svg():
    """선행(파랑)·동행(주황)이 같은 모양에서 3개월 어긋난 것을 보여 주는 설명 그림."""
    W, H, sh = 560, 150, 38
    def pts(off, col):
        p = " ".join(f"{20 + x:.0f},{75 - 48 * math.sin((x - off) / 520 * 2 * math.pi * 1.5):.1f}" for x in range(0, 521, 8))
        return f"<polyline points='{p}' fill=none stroke='var(--{col})' stroke-width=2.5 />"
    pk = 520 / 1.5 / 4     # 첫 정점 x
    return (f"<svg viewBox='0 0 {W} {H}' class=ll role=img aria-label='선행 지표가 정점과 저점을 먼저 찍고 동행 지표가 뒤따르는 그림'>"
            f"<line x1=20 x2=540 y1=75 y2=75 stroke='var(--bd)' />"
            f"{pts(0, 'c1')}{pts(sh, 'c2')}"
            f"<line x1={20 + pk:.0f} x2={20 + pk + sh:.0f} y1=22 y2=22 stroke='var(--fg)' marker-end='url(#ar)' /><text x={20 + pk + sh / 2:.0f} y=16 text-anchor=middle class=t>시차</text>"
            f"<text x=24 y=142 class=t fill='var(--c1)' style='fill:var(--c1)'>— 선행 지표 (먼저 꺾이고 먼저 오른다)</text>"
            f"<text x=300 y=142 class=t style='fill:var(--c2)'>— 동행·후행 지표 (뒤따른다)</text>"
            f"<defs><marker id=ar markerWidth=8 markerHeight=8 refX=7 refY=4 orient=auto><path d='M0,0 L8,4 L0,8 z' fill='var(--fg)'/></marker></defs></svg>")


def chain_svg(badges=None):
    badges = badges or {}
    W, NW, NH = 900, 168, 52
    cx = [44, 262, 482, 722]
    colname = ["① 먼저 움직이는 신호", "② 선행지수", "③ 실물·이익(동행)", "④ 뒤늦게 확인되는 결과(후행)"]
    ry = {"news": 0, "curve": 1, "credit": 2, "oil": 3, "stock": 4, "kcli": 0.5, "ucli": 1.7, "real": 0.9, "eps": 3.9, "cpi": 2.8, "apt": 1.9, "analyst": 4}
    pos = {}
    for nid, label, col, row, _ in S.NODES:
        pos[nid] = (cx[col], 36 + ry[nid] * 80)
    H = 36 + 4 * 80 + NH + 14
    nodes = {n[0]: n for n in S.NODES}
    out = [f"<svg viewBox='0 0 {W} {H}' class=chain role=img aria-label='선행 지표가 어디에 영향을 주는지 보여 주는 도식'>",
           "<defs><marker id=ah markerWidth=9 markerHeight=9 refX=8 refY=4.5 orient=auto><path d='M0,0 L9,4.5 L0,9 z' fill='var(--mu)'/></marker></defs>"]
    for i, n in enumerate(colname):
        out.append(f"<text x={cx[i] + NW / 2} y=18 text-anchor=middle class=ch>{n}</text>")
    labels = []
    for a, b, lab, vids, style in S.EDGES:
        xa, ya = pos[a]; xb, yb = pos[b]
        if xa == xb:      # 같은 열 안의 관계는 왼쪽으로 돌아 나가서 잇는다
            x1 = x2 = xa; y1, y2 = ya + NH / 2, yb + NH / 2
            out.append(f"<path d='M{x1},{y1} C{x1 - 46},{y1} {x2 - 46},{y2} {x2},{y2}' fill=none stroke='var(--mu)' stroke-width=1.6 {'stroke-dasharray=5,4' if style == 'dash' else ''} marker-end='url(#ah)' opacity=.85 />")
            labels.append((x1 - 34, (y1 + y2) / 2, lab)); continue
        x1, y1, x2, y2 = xa + NW, ya + NH / 2, xb, yb + NH / 2
        dx = max(40, (x2 - x1) * 0.5)
        out.append(f"<path d='M{x1},{y1} C{x1 + dx},{y1} {x2 - dx},{y2} {x2},{y2}' fill=none stroke='var(--mu)' stroke-width=1.6 {'stroke-dasharray=5,4' if style == 'dash' else ''} marker-end='url(#ah)' opacity=.85 />")
        t = {("oil", "real"): 0.66}.get((a, b), 0.5); bx = (1 - t) ** 3 * x1 + 3 * (1 - t) ** 2 * t * (x1 + dx) + 3 * (1 - t) * t ** 2 * (x2 - dx) + t ** 3 * x2
        by = (1 - t) ** 3 * y1 + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y2
        labels.append((bx, by, lab))
    for nid, (x, y) in pos.items():
        _, label, col, row, desc = nodes[nid]
        cls = ["n0", "n1", "n2", "n3"][col]
        out.append(f"<g><title>{e(desc)}</title><rect x={x} y={y} width={NW} height={NH} rx=9 class='nd {cls}' />")
        lines = label.split("\n"); ty = y + NH / 2 + 5 - (len(lines) - 1) * 8
        for j, ln in enumerate(lines):
            out.append(f"<text x={x + NW / 2} y={ty + j * 16} text-anchor=middle class=nt>{e(ln)}</text>")
        bd = badges.get(nid)
        if bd:
            arrow, cls, tip = bd
            out.append(f"<g class='bd {cls}'><title>{e(tip)}</title><circle cx={x + NW - 4} cy={y + 4} r=13 /><text x={x + NW - 4} y={y + 9} text-anchor=middle>{arrow}</text></g>")
        out.append("</g>")
    for bx, by, lab in labels:
        w = 14 + len(lab) * 7.2
        out.append(f"<rect x={bx - w / 2:.0f} y={by - 10:.0f} width={w:.0f} height=19 rx=9 class=lb /><text x={bx:.0f} y={by + 4:.0f} text-anchor=middle class=lt>{e(lab)}</text>")
    out.append("</svg>")
    return "".join(out)


# ───────────────────────── 본문 ─────────────────────────
JS = r"""
(function(){
const D=JSON.parse(document.getElementById('ldata').textContent), S=D.series, N=D.n, M0=D.m0, REC=D.rec;
const NS='http://www.w3.org/2000/svg', W=820, H=300, PL=54, PR=54, PT=14, PB=26;
const lab=i=>{const t=M0+i;return Math.floor(t/12)+'-'+String((t%12)+1).padStart(2,'0')};
const fmt=v=>v==null?'-':(Math.abs(v)>=1000?v.toLocaleString('en-US',{maximumFractionDigits:0}):Math.abs(v)>=100?v.toFixed(1):v.toFixed(2));
function ticks(a,b){const n=4,st=(b-a)/n;return Array.from({length:n+1},(_,i)=>a+st*i)}
function pad(a,b){if(a==null){a=0;b=1}if(a===b){a-=1;b+=1}const p=(b-a)*.06;return [a-p,b+p]}
function path(f,i0,i1,x,y,from,to){let d='',pen=false;for(let i=from;i<=to;i++){const v=f(i);if(v==null){pen=false;continue}d+=(pen?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1);pen=true}return d}
function el(t,a,txt){const n=document.createElementNS(NS,t);for(const k in a)n.setAttribute(k,a[k]);if(txt!=null)n.textContent=txt;return n}
document.querySelectorAll('.pc').forEach(root=>{
  const P=D.pairs.find(p=>p.id===root.dataset.pair); let st={opt:0,k:P.options[0].claim,from:0};
  const svg=root.querySelector('.cv'), bars=root.querySelector('.bars'), info=root.querySelector('.info'), tip=root.querySelector('.tip'), sl=root.querySelector('input[type=range]'), kv=root.querySelector('.kv');
  const sel=root.querySelector('select'); if(sel)sel.onchange=()=>{st.opt=+sel.value;st.k=P.options[st.opt].claim;draw()};
  sl.oninput=()=>{st.k=+sl.value;draw()};
  root.querySelectorAll('[data-win]').forEach(b=>b.onclick=()=>{const y=+b.dataset.win;st.from=y?Math.max(0,N-1-y*12):0;root.querySelectorAll('[data-win]').forEach(x=>x.classList.toggle('on',x===b));draw()});
  root.querySelector('[data-jump=claim]').onclick=()=>{st.k=P.options[st.opt].claim;draw()};
  root.querySelector('[data-jump=best]').onclick=()=>{st.k=P.options[st.opt].best;draw()};
  function draw(){
    const o=P.options[st.opt], L=S[o.leader], Fo=S[o.follower], k=st.k; sl.value=k;
    const lv=i=>{const j=i-k;return j>=0&&j<N?L.v[j]:null}, fv=i=>i>=0&&i<N?Fo.v[i]:null;
    let lastF=-1;for(let i=0;i<N;i++)if(Fo.v[i]!=null)lastF=i;
    let first=N;for(let i=0;i<N;i++){if(Fo.v[i]!=null||L.v[i]!=null){first=i;break}}
    const i0=Math.max(st.from,first), i1=N-1+Math.max(k,0);
    let a1=null,b1=null,a2=null,b2=null;
    for(let i=i0;i<=i1;i++){const x=lv(i),y=fv(i);if(x!=null){a1=a1==null?x:Math.min(a1,x);b1=b1==null?x:Math.max(b1,x)}if(y!=null){a2=a2==null?y:Math.min(a2,y);b2=b2==null?y:Math.max(b2,y)}}
    [a1,b1]=pad(a1,b1);[a2,b2]=pad(a2,b2);
    const x=i=>PL+(i-i0)/(i1-i0)*(W-PL-PR), y1=v=>PT+(1-(v-a1)/(b1-a1))*(H-PT-PB), y2=v=>PT+(1-(v-a2)/(b2-a2))*(H-PT-PB);
    svg.replaceChildren();
    REC.forEach(([s,e_])=>{const s2=Math.max(s,i0),e2=Math.min(e_,i1);if(e2>=s2)svg.append(el('rect',{x:x(s2),y:PT,width:Math.max(1,x(e2+1)-x(s2)),height:H-PT-PB,class:'rec'}))});
    ticks(a1,b1).forEach(v=>{svg.append(el('line',{x1:PL,x2:W-PR,y1:y1(v),y2:y1(v),class:'gr'}));svg.append(el('text',{x:PL-6,y:y1(v)+4,'text-anchor':'end',class:'ax a1'},fmt(v)))});
    ticks(a2,b2).forEach(v=>svg.append(el('text',{x:W-PR+6,y:y2(v)+4,class:'ax a2'},fmt(v))));
    const y0=Math.ceil((M0+i0)/12/5)*5; for(let yr=y0;yr<=(M0+i1)/12;yr+=((i1-i0)>200?5:(i1-i0)>90?2:1)){const i=yr*12-M0;if(i>=i0&&i<=i1)svg.append(el('text',{x:x(i),y:H-8,'text-anchor':'middle',class:'ax'},yr))}
    if(k>0&&i1>lastF){svg.append(el('rect',{x:x(lastF+1),y:PT,width:x(i1)-x(lastF+1),height:H-PT-PB,class:'fc'}));svg.append(el('text',{x:x(i1)-4,y:PT+12,'text-anchor':'end',class:'ax'},'← 선행 시차만큼 앞서 보이는 구간'))}
    const cut=Math.min(i1,lastF+(k>0?0:0));
    svg.append(el('path',{d:path(lv,i0,i1,x,y1,i0,Math.min(i1,lastF)),class:'l1'}));
    if(i1>lastF)svg.append(el('path',{d:path(lv,i0,i1,x,y1,Math.max(i0,lastF),i1),class:'l1 dash'}));
    svg.append(el('path',{d:path(fv,i0,i1,x,y2,i0,i1),class:'l2'}));
    const cur=el('line',{y1:PT,y2:H-PB,class:'cur',visibility:'hidden'});svg.append(cur);
    const hit=el('rect',{x:PL,y:PT,width:W-PL-PR,height:H-PT-PB,fill:'transparent'});svg.append(hit);
    hit.onmousemove=ev=>{const r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)/r.width*W,i=Math.round(i0+(px-PL)/(W-PL-PR)*(i1-i0));if(i<i0||i>i1)return;
      cur.setAttribute('x1',x(i));cur.setAttribute('x2',x(i));cur.setAttribute('visibility','visible');
      tip.innerHTML='<b>'+lab(i)+'</b> · '+(lv(i)!=null?'<span class=k1>'+L.name+' '+fmt(lv(i))+(k?' <small>('+lab(i-k)+' 값)</small>':''):'')+' · '+(fv(i)!=null?'<span class=k2>'+Fo.name+' '+fmt(fv(i))+'</span>':'');};
    hit.onmouseleave=()=>{cur.setAttribute('visibility','hidden');tip.textContent=' '};
    root.querySelector('.lg1').textContent=L.name+(k?' ('+(k>0?k+'개월 뒤로 밀어서 표시':(-k)+'개월 앞으로 당겨서 표시')+')':'')+(o.invert?'  [높을수록 위험]':'');
    root.querySelector('.lg2').textContent=Fo.name;
    kv.textContent=(k>0?'+':'')+k+'개월';
    // r(k) 막대
    bars.replaceChildren(); const BW=820,BH=120,bx=PL, bw=(BW-PL-PR)/25, zero=BH/2;
    bars.append(el('line',{x1:bx,x2:BW-PR,y1:zero,y2:zero,class:'gr'}));
    o.r.forEach((r,idx)=>{const kk=idx-12; if(r==null)return; const v=o.invert?-r:r, h=Math.abs(v)*(BH/2-8), up=v>=0;
      const g=el('rect',{x:bx+idx*bw+2,y:up?zero-h:zero,width:bw-4,height:Math.max(1,h),class:'bar'+(kk===k?' sel':'')+(kk===o.best?' best':'')});g.onclick=()=>{st.k=kk;draw()};
      const t=el('title',{},'시차 '+kk+'개월: 상관 r='+r);g.append(t);bars.append(g);
      if(kk%3===0)bars.append(el('text',{x:bx+idx*bw+bw/2,y:BH-1,'text-anchor':'middle',class:'ax'},(kk>0?'+':'')+kk))});
    bars.append(el('text',{x:PL,y:10,class:'ax'},'시차별 상관 (막대를 누르면 그 시차로 이동 · 위로 길수록 같은 방향으로 잘 맞음)'));
    const rk=o.r[k+12], rb=o.r[o.best+12], rc=o.r[o.claim+12];
    const ls=o.ls; let dirTxt='';
    if(ls){const rk0=o.r[k+12]; const ym=t=>lab(t);
      if(ls.dir===0) dirTxt='<br>📍 앞 지표의 지금 방향: <b>'+ls.arrow+' '+ls.label+'</b> — 뚜렷한 방향이 없어 뒤 지표에 줄 신호도 약합니다.';
      else if(k<=0) dirTxt='<br>📍 앞 지표의 지금 방향: <b>'+ls.arrow+' '+ls.label+'</b> — 이 시차(≤0)에서는 뒤 지표가 앞서거나 동시에 움직이므로 예고 효과를 기대하기 어렵습니다.';
      else if(rk0==null) dirTxt='';
      else {const same=(rk0>=0)?ls.dir:-ls.dir, a=same>0?'▲ 오름':'▼ 내림'; let lastL=-1;for(let i=0;i<N;i++)if(L.v[i]!=null)lastL=i;
        dirTxt='<br>📍 앞 지표의 지금 방향: <b>'+ls.arrow+' '+ls.label+'</b> → 상관이 '+(rk0>=0?'양(+)':'음(−)')+'이므로 뒤 지표는 약 <b>'+k+'개월 뒤('+ym(lastL+k)+'경)</b>까지 <b>'+a+'</b> 쪽 압력을 받을 수 있습니다. <small>(과거 평균적 관계일 뿐 확정이 아닙니다)</small>';}
    }
    info.innerHTML='지금 시차 <b>'+(k>0?'+':'')+k+'개월</b>의 상관 <b>'+(rk==null?'-':rk.toFixed(2))+'</b> · 영상 주장 <b>'+(o.claim>0?'+':'')+o.claim+'개월</b>일 때 '+(rc==null?'-':rc.toFixed(2))+' · 데이터상 최적 <b>'+(o.best>0?'+':'')+o.best+'개월</b>일 때 '+(rb==null?'-':rb.toFixed(2))+' <small>('+o.start.slice(0,7)+' 이후 '+o.n+'개월 비교)</small>'+dirTxt;
  }
  draw();
});
})();
"""

CSS_X = """
:root{--c1:#2b5fd9;--c2:#d9822b;--rec:rgba(120,120,120,.16)}
@media(prefers-color-scheme:dark){:root{--c1:#7ea2f5;--c2:#f0a35a;--rec:rgba(200,200,200,.12)}}
svg text{font-family:system-ui,'Noto Sans KR',sans-serif}
.ll{width:100%;max-width:560px;height:auto}.ll .t{font-size:12px;fill:var(--mu)}
.chain{width:100%;height:auto;min-width:640px}.chain .ch{font-size:13px;font-weight:700;fill:var(--mu)}
.chain .nd{stroke:var(--bd);stroke-width:1.4}.chain .n0{fill:#eaf1ff}.chain .n1{fill:#ffeccf}.chain .n2{fill:#e7f6ea}.chain .n3{fill:#f0eaf8}
@media(prefers-color-scheme:dark){.chain .n0{fill:#22304f}.chain .n1{fill:#4a3820}.chain .n2{fill:#1f3a27}.chain .n3{fill:#33284a}}
.chain .nt{font-size:13.5px;font-weight:600;fill:var(--fg)}.chain .lb{fill:var(--card);stroke:var(--bd)}.chain .lt{font-size:12px;font-weight:700;fill:var(--ac)}
.pc svg.cv{width:100%;height:auto;display:block;background:var(--card);border:1px solid var(--bd);border-radius:8px}
.pc .rec{fill:var(--rec)}.pc .fc{fill:var(--c1);opacity:.07}.pc .gr{stroke:var(--bd);stroke-width:1}.pc .ax{font-size:11px;fill:var(--mu)}.pc .a1{fill:var(--c1)}.pc .a2{fill:var(--c2)}
.pc .l1{fill:none;stroke:var(--c1);stroke-width:2.2}.pc .l1.dash{stroke-dasharray:5,4}.pc .l2{fill:none;stroke:var(--c2);stroke-width:2.2}.pc .cur{stroke:var(--mu);stroke-dasharray:3,3}
.pc .bar{fill:var(--mu);opacity:.55;cursor:pointer}.pc .bar.sel{fill:var(--c1);opacity:1}.pc .bar.best{stroke:var(--c2);stroke-width:2}.pc .bars{width:100%;height:auto;display:block}
.pc .tip{font-size:13px;min-height:20px;margin:4px 0}.pc .k1{color:var(--c1)}.pc .k2{color:var(--c2)}
.pc .ctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}.pc input[type=range]{flex:1;min-width:180px}
.pc button,.pc select{font:inherit;font-size:13px;background:var(--chip);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:2px 9px;cursor:pointer}.pc button.on{background:var(--ac);color:#fff}
.pc .lgd{font-size:13px}.pc .lgd .s1{color:var(--c1);font-weight:700}.pc .lgd .s2{color:var(--c2);font-weight:700}
.pc .claim{background:var(--chip);border-radius:8px;padding:8px 12px;margin:8px 0;font-size:14px}.pc .kv{font-weight:700;min-width:64px;display:inline-block}
.vtab td:nth-child(n+3):nth-child(-n+5){white-space:nowrap}.legend-box{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;margin:6px 0}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}.grid3 .card{margin:0}
.up{color:#1a8a4a;font-weight:700}.down{color:#c0392b;font-weight:700}.flat{color:var(--mu);font-weight:700}
.dc{margin:0}.dc.f-up{border-left:5px solid #1a8a4a}.dc.f-down{border-left:5px solid #c0392b}.dc.f-flat{border-left:5px solid var(--mu)}
.dh{display:flex;gap:10px;align-items:center;margin-bottom:4px}.arrow{font-size:30px;line-height:1;width:38px;text-align:center}.arrow.up,.st.up{color:#1a8a4a}.arrow.down,.st.down{color:#c0392b}.arrow.flat,.st.flat{color:var(--mu)}.st{font-weight:700;font-size:14px}
.op{font-size:14px;margin:8px 0 4px;background:var(--chip);border-radius:8px;padding:8px 10px}
.regime{border-width:2px}.regime.f-up{border-color:#1a8a4a}.regime.f-down{border-color:#c0392b}.regime.f-flat{border-color:#d9a82b}.rh{display:flex;gap:14px;align-items:center}.ricon{font-size:40px}
.gauge{margin:10px 0 4px}.gz{position:relative;height:12px;border-radius:6px;background:linear-gradient(90deg,#c0392b,#d9a82b 50%,#1a8a4a)}.gz span{position:absolute;top:-5px;width:6px;height:22px;background:var(--fg);border-radius:3px;transform:translateX(-3px)}
.gl{display:flex;justify-content:space-between;font-size:11.5px;color:var(--mu)}ul.acts li{margin:4px 0;font-size:14.5px}
.chain .bd circle{stroke:var(--card);stroke-width:2}.chain .bd text{font-size:15px;font-weight:700;fill:#fff}.chain .bd.up circle{fill:#1a8a4a}.chain .bd.down circle{fill:#c0392b}.chain .bd.flat circle{fill:#7a7a74}
.lg{width:100%;min-width:700px;height:auto;display:block;background:var(--card);border:1px solid var(--bd);border-radius:8px}.lg .t{font-size:13px;fill:var(--fg)}.lg .m{font-size:11.5px;fill:var(--mu)}.lg .bl{font-size:12px;font-weight:700;fill:#fff}
.lg .gr{stroke:var(--bd);stroke-width:1}.lg .wt{fill:var(--c2)}.lg .ok{fill:#1a8a4a}.lg .blind{fill:var(--mu);opacity:.38}.lgx{font-size:14.5px;margin:8px 0 16px}
.tag{font-size:11.5px;background:var(--chip);border-radius:6px;padding:1px 6px;color:var(--mu)}
"""


def eun(w):
    """단어 뒤에 붙일 은/는 (받침 있으면 은). 마지막이 한글이 아니면 '는'."""
    c = w.rstrip(")] ")[-1:] if w else ""
    return "은" if c and "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 else "는"


def _month_end(m):
    y, mo = int(m[:4]), int(m[5:7]); nx = datetime.date(y + (mo == 12), mo % 12 + 1, 1)
    return nx - datetime.timedelta(days=1)


def lag_charts(get, meta, bests, today):
    """발표 지연 그래프 2개와 각 그래프 바로 아래 설명. get(sid) -> {월: 값}. 반환: HTML 문자열."""
    td = datetime.date.fromisoformat(today)
    # ── 그래프 1: 선행 시차 = 발표 대기 + 쓸 수 있는 시간 ──
    rows = S.LAG_ROWS; W, LX, PW, RH, TOP = 820, 210, 470, 40, 44; MAXM = 3.5; px = PW / MAXM
    H = TOP + RH * len(rows) + 30
    o = [f"<svg viewBox='0 0 {W} {H}' class=lg role=img aria-label='지표별 선행 시차가 발표 대기와 쓸 수 있는 시간으로 나뉘는 그래프'>"]
    for k in range(4):
        x = LX + k * px
        o.append(f"<line x1={x:.0f} x2={x:.0f} y1={TOP - 8} y2={H - 26} class=gr stroke-dasharray='3,3' /><text x={x:.0f} y={H - 10} text-anchor=middle class=m>{k}개월</text>")
    o.append(f"<rect x={LX} y=10 width=14 height=14 class=wt /><text x={LX + 20} y=22 class=m>발표를 기다리는 시간</text>"
             f"<rect x={LX + 170} y=10 width=14 height=14 class=ok /><text x={LX + 190} y=22 class=m>발표 후 쓸 수 있는 시간</text>")
    rem = {}
    for i, (sid, name, lead, src, lag_d, how, _pair) in enumerate(rows):
        y = TOP + i * RH; lag_m = lag_d / 30.0; use = max(lead - lag_m, 0); rem[sid] = use
        o.append(f"<text x={LX - 10} y={y + 15} text-anchor=end class=t>{e(name)}</text><text x={LX - 10} y={y + 31} text-anchor=end class=m>선행 {lead}개월 · 발표 약 {lag_d}일 뒤</text>")
        w1 = lag_m * px; w2 = use * px
        o.append(f"<rect x={LX} y={y + 6} width={max(w1, 1.5):.1f} height=26 class=wt />"
                 f"<rect x={LX + w1:.1f} y={y + 6} width={w2:.1f} height=26 class=ok />")
        if w1 >= 70: o.append(f"<text x={LX + w1 / 2:.0f} y={y + 24} text-anchor=middle class=bl>{lag_m:.1f}개월</text>")
        o.append(f"<text x={LX + w1 + w2 + 8:.0f} y={y + 24} class=t style='font-weight:700'>남는 {use:.1f}개월</text>")
    o.append("</svg>")
    g1 = "".join(o)
    slow = [(n, lead, lag_d, rem[sid]) for sid, n, lead, _s, lag_d, _h, _p in rows if lag_d >= 20]
    fast = [(n, lead, lag_d, rem[sid]) for sid, n, lead, _s, lag_d, _h, _p in rows if lag_d < 20]
    ex1 = (f"<p class=lgx><b>읽는 법</b> 막대 전체 길이가 '이 지표가 경기를 앞선다고 하는 개월 수'다. 주황은 값이 <b>발표될 때까지 기다리는 시간</b>이라 쓸 수 없고, 초록만 <b>실제로 대응할 수 있는 시간</b>이다. "
           f"{' · '.join(f'{e(n)} {lag_d}일 지연 → 남는 {r:.1f}개월' for n, _l, lag_d, r in slow)}. "
           f"반면 {', '.join(e(n) for n, *_ in fast)}는 매일 값이 나와 선행 시차가 거의 그대로 남는다. "
           f"그래서 <b>선행지수는 '방향이 바뀌었는지 확인하는 용도'</b>, <b>일별 지표는 '발표 전에 미리 가늠하는 용도'</b>로 나눠 쓰는 것이 맞다. "
           f"<span class=meta>선행 시차는 영상 주장(OECD·통계청은 통상 3개월), 발표 지연은 알려진 발표 관행에서 잡은 대략의 값이다.</span></p>")
    # ── 그래프 2: 지금 DB 의 마지막 값이 얼마나 묵었나 ──
    fr = []
    for sid in S.FRESH_SIDS:
        d = get(sid)
        if not d: continue
        lm = max(d)
        dt = td if lm[:7] == today[:7] else _month_end(lm)
        fr.append((sid, (meta[sid]["name"] if sid in meta else sid), lm, dt, (td - dt).days))
    fr.sort(key=lambda r: -r[4])
    start = td - datetime.timedelta(days=120); span = 120.0; PW2 = 470; RH2 = 32; TOP2 = 34
    H2 = TOP2 + RH2 * len(fr) + 30
    o = [f"<svg viewBox='0 0 {W} {H2}' class=lg role=img aria-label='지표별 마지막 값이 오늘보다 얼마나 이전 것인지 보여 주는 그래프'>"]
    m = datetime.date(start.year, start.month, 1)
    while m <= td:
        if m >= start:
            x = LX + (m - start).days / span * PW2
            o.append(f"<line x1={x:.0f} x2={x:.0f} y1={TOP2 - 8} y2={H2 - 26} class=gr stroke-dasharray='3,3' /><text x={x:.0f} y={H2 - 10} text-anchor=middle class=m>{m.month}월 1일</text>")
        m = datetime.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    xt = LX + PW2
    o.append(f"<line x1={xt} x2={xt} y1={TOP2 - 8} y2={H2 - 26} stroke='var(--fg)' /><text x={xt} y={H2 - 10} text-anchor=middle class=m style='font-weight:700'>오늘 {td.month}/{td.day}</text>"
             f"<rect x={LX} y=8 width=14 height=14 class=blind /><text x={LX + 20} y=20 class=m>마지막 값 이후 아직 반영 안 된 기간</text>")
    for i, (sid, name, lm, dt, days) in enumerate(fr):
        y = TOP2 + i * RH2; xs = LX + max((dt - start).days, 0) / span * PW2
        o.append(f"<text x={LX - 10} y={y + 19} text-anchor=end class=t>{e(name)}</text>"
                 f"<rect x={xs:.1f} y={y + 7} width={max(xt - xs, 1.5):.1f} height=16 class=blind />"
                 f"<circle cx={xs:.1f} cy={y + 15} r=5 class=ok />"
                 f"<text x={xt + 8} y={y + 19} class=t>{'오늘까지' if days <= 3 else f'{days}일 전 값'}<tspan class=m> ({lm[:7]})</tspan></text>")
    o.append("</svg>")
    g2 = "".join(o)
    old = [r for r in fr if r[4] > 20]; new = [r for r in fr if r[4] <= 20]
    ex2 = (f"<p class=lgx><b>읽는 법</b> 초록 점이 DB에 있는 그 지표의 마지막 값이고, 점에서 오른쪽 '오늘' 선까지 회색 막대가 <b>아직 모르는 기간</b>이다. "
           f"오늘({td.month}/{td.day}) 기준으로 {', '.join(f'{e(n)}{eun(n)} {d}일 전({lm[:7]}) 값' for _s, n, lm, _dt, d in old[:4])}{' 등' if len(old) > 4 else ''}까지만 알고 있다"
           f"{'(다음 발표는 보통 이달 말~다음 달 초)' if old else ''}. "
           f"{', '.join(e(n) for _s, n, *_ in new)} 모두 오늘 값까지 들어와 있다. "
           f"<b>회색이 긴 지표로 확정하고 회색이 짧은 지표로 현재를 가늠한다</b>고 보면 된다. 선행지수가 지난 방향을 알려 주는 동안 일별 지표가 이미 방향을 바꿨다면 그것이 먼저 보내는 신호다. <span class=meta>한국 장단기 금리차는 이 페이지가 한국은행 월 자료(월평균)를 쓰기 때문에 한 달 늦게 보일 뿐, 일별 국고채 금리는 지표 페이지에서 매일 갱신된다.</span></p>")
    # 표
    trs = ""
    for sid, name, lead, src, lag_d, how, pair in rows:
        b = bests.get(pair) if pair else None
        trs += (f"<tr><td>{e(name)}<td>{lead}개월 <span class=meta>({e(src)})</span><td>{lag_d}일 <span class=meta>({e(how)})</span>"
                f"<td><b>{rem[sid]:.1f}개월</b><td>{'-' if b is None else f'{b:+d}개월'}</tr>")
    tab = (f"<details><summary>숫자로 보기</summary><div style='overflow-x:auto'><table><tr><th>지표<th>선행 시차<th>발표 지연(추정)<th>남는 시간<th>데이터상 최적 시차</tr>{trs}</table></div>"
           f"<p class=meta>데이터상 최적 시차는 아래 4️⃣ 표와 같은 계산이며, 비교 대상(뒤 지표)이 지표마다 달라 서로 직접 비교하기는 어렵다. '-'는 해당 쌍을 계산하지 않은 것이고, 마이너스는 뒤 지표가 먼저 움직였다는 뜻이다.</p></details>")
    return (f"<h2 class=cat-h>⏱️ 신호가 늦게 나오면 선행은 얼마나 남나</h2>"
            f"<p class=meta>선행지수가 3개월 앞선다 해도 발표가 늦으면 그만큼 줄어든다. 두 그래프로 한눈에 본다.</p>"
            f"<h3 class=sub-h>① 선행 시차 중 실제로 쓸 수 있는 시간</h3><div style='overflow-x:auto'>{g1}</div>{ex1}"
            f"<h3 class=sub-h>② 지금 지표별 마지막 값은 얼마나 묵었나</h3><div style='overflow-x:auto'>{g2}</div>{ex2}{tab}")


def fmtv(v, unit=""):
    if v is None: return "-"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.1f}" if abs(v) >= 100 else f"{v:,.2f}"


def build(con=None):
    import report as R
    con = con or D.connect()
    con.executescript(F.DDL)
    sids = {o[k] for p in S.PAIRS for o in p["options"] for k in ("leader", "follower")} | {s[0] for s in S.STATUS} | {"usrec", "kr_cli", "oecd_kr_cli", "oecd_us_cli", "t10y3m", "kr_curve"} | {x[0] for x in S.DIRS}
    ser = {s: F.load(con, s) for s in sorted(sids)}
    meta = {r["sid"]: r for r in con.execute("SELECT * FROM leading_meta")}
    missing = [s for s in sids if not ser[s]]
    if missing:
        print("시계열 없음 — uv run leading_fetch.py 를 먼저 실행:", missing)
        if len(missing) > len(sids) // 2: return
    last = max(max(v) for v in ser.values() if v)
    con.executescript(SIG_DDL)
    sig = {x[0]: classify(x[0], ser[x[0]]) for x in S.DIRS if ser.get(x[0])}
    dmeta = {x[0]: x for x in S.DIRS}
    num = den = 0.0; contrib = []
    for sid, g in sig.items():
        _, name, wt, sg, _ = dmeta[sid]; st = S.STATES[g["state"]]
        g.update(label=st[0], arrow=st[1], grp=st[3], score=st[2], fav=st[2] * sg if sg else 0.0)
        if wt > 0: num += wt * g["fav"]; den += wt; contrib.append((name, st[0], st[1], wt, g["fav"]))
    score = num / den if den else 0.0
    regime, ricon, rstock, ract, rvids = regime_of(score)
    today = D.today()
    for sid, g in sig.items():
        con.execute("INSERT OR REPLACE INTO leading_signal VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, today, dmeta[sid][1], g["month"], g["value"], g["d1"], g["d3"], g["d6"], g["d12"], g["state"], g["label"], g["grp"], g["score"], g["peak"]))
    con.execute("INSERT OR REPLACE INTO leading_regime VALUES(?,?,?,?)", (today, score, regime, json.dumps({"stock": rstock, "contrib": contrib}, ensure_ascii=False)))
    con.commit()
    m0 = START[:7]; N = months_between(START, last) + 1
    cols = [add_m(START, i) for i in range(N)]

    # 쌍별 통계
    pairs_js, vrows = [], ""
    for p in S.PAIRS:
        popts = []
        for o in p["options"]:
            A, B = ser[o["leader"]], ser[o["follower"]]; start = o.get("start", START)
            r = xcorr(A, B, start, minn=30)
            sign = -1 if o.get("invert") else 1
            vals = {k: v for k, v in r.items() if v is not None}
            best = max(vals, key=lambda k: sign * vals[k]) if vals else 0
            n = sum(1 for t in B if t >= start and add_m(t, -best) in A)
            v = verdict(o["claim"], best, vals.get(best), sign)
            o.update(r_list=[r[k] for k in LAGS], best=best, rbest=vals.get(best), r0=vals.get(0), n=n, start_=start, verdict=v)
            popts.append({"leader": o["leader"], "follower": o["follower"], "label": o["label"], "claim": o["claim"], "invert": bool(o.get("invert")),
                          "r": o["r_list"], "best": best, "n": n, "start": start,
                          "ls": ({"arrow": sig[o["leader"]]["arrow"], "label": sig[o["leader"]]["label"],
                                  "dir": 1 if sig[o["leader"]]["state"] in ("up", "trough_up", "slowing") else -1 if sig[o["leader"]]["state"] in ("down", "peak_down") else 0}
                                 if o["leader"] in sig else None)})
            vrows += (f"<tr><td><a href='#p-{p['id']}'>{e(o['label'])}</a><td>{('+' if o['claim'] > 0 else '') + str(o['claim'])}개월"
                      f"<td>{best:+d}개월 <span class=meta>(r={'-' if vals.get(best) is None else format(vals[best], '.2f')})</span>"
                      f"<td>{'-' if vals.get(o['claim']) is None else format(vals[o['claim']], '.2f')}<td>{VCLS[v[0]]} {e(v[1])}</tr>")
        pairs_js.append({"id": p["id"], "options": popts})

    bests = {(o["leader"], o["follower"]): o["best"] for p in S.PAIRS for o in p["options"]}
    lagsec = lag_charts(lambda x: ser[x] if x in ser else F.load(con, x), meta, bests, today)

    # 데이터(JSON): 개월 단위 정렬
    used = {o[k] for p in S.PAIRS for o in p["options"] for k in ("leader", "follower")}
    series_js = {}
    for s in sorted(used):
        series_js[s] = {"name": meta[s]["name"] if s in meta else s, "unit": meta[s]["unit"] if s in meta else "",
                        "v": [None if c not in ser[s] else round(ser[s][c], 3) for c in cols]}
    rec, ur, start_i = [], ser["usrec"], None
    for i, c in enumerate(cols):
        if ur.get(c) == 1 and start_i is None: start_i = i
        if ur.get(c) != 1 and start_i is not None: rec.append([start_i, i - 1]); start_i = None
    if start_i is not None: rec.append([start_i, N - 1])
    data = {"m0": int(m0[:4]) * 12 + int(m0[5:7]) - 1, "n": N, "series": series_js, "pairs": pairs_js, "rec": rec}


    # ── 지금의 방향과 투자 의견 ──
    out_edges = {}
    nodename = {n[0]: n[1].replace("\\n", " ") for n in S.NODES}
    for a_, b_, lab_, v_, st__ in S.EDGES: out_edges.setdefault(a_, []).append(f"{nodename[b_]} ({lab_})")
    def chg_txt(sid, g):
        if sid in LOGSIDS:
            f = lambda k: None if ser[sid].get(add_m(g["month"], -k)) is None else (g["value"] / ser[sid][add_m(g["month"], -k)] - 1) * 100
            a3, a6 = f(3), f(6); u = "%"
        else:
            a3, a6, u = g["d3"], g["d6"], ""
        t = lambda x: "-" if x is None else f"{x:+.2f}{u}"
        return f"3개월 {t(a3)} · 6개월 {t(a6)}"
    cards_dir = ""
    order = sorted(sig, key=lambda x: (-dmeta[x][2], list(dmeta).index(x)))
    for sid in order:
        g = sig[sid]; _, name, wt, sg, node = dmeta[sid]
        txt, vids_ = S.OPINION.get(sid, {}).get(g["grp"], (S.FLAT_TEXT, []))
        if g["grp"] == "flat" or sid not in S.OPINION: txt, vids_ = (S.FLAT_TEXT, [])
        fav = fcls(g); aff = out_edges.get(node, [])
        pk = (f"<br><span class=meta>최근 12개월 최고 {g['peak'][:7]} · {'이번 달' if g['ago_peak'] == 0 else str(g['ago_peak']) + '개월 전'}</span>" if g["state"] in ("peak_down", "down", "topping", "slowing") else
              f"<br><span class=meta>최근 12개월 최저 {g['trough'][:7]} · {'이번 달' if g['ago_trough'] == 0 else str(g['ago_trough']) + '개월 전'}</span>" if g["state"] in ("trough_up", "bottoming") else "")
        cards_dir += (f"<div class='card dc f-{fav}'><div class=dh><span class='arrow {fav}'>{g['arrow']}</span><div><b>{e(name)}</b>"
                      f"{'' if wt <= 0 else '<span class=tag style=margin-left:6px>종합 가중 ' + format(wt, 'g') + '</span>'}<br><span class='st {fav}'>{e(g['label'])}</span></div></div>"
                      f"<div class=meta>{fmtv(g['value'])} <span class=meta>({g['month'][:7]})</span> · {chg_txt(sid, g)}{pk}</div>"
                      f"{('<div class=meta>→ 이 지표가 앞서는 곳: ' + e(' · '.join(aff)) + '</div>') if aff else ''}"
                      f"<p class=op>💡 {e(txt)}</p>{('<div class=meta>근거: ' + ' · '.join(yt(i) for i in vids_) + '</div>') if vids_ else ''}</div>")
    pos_ = max(0, min(100, (score + 1) / 2 * 100))
    crows = "".join(f"<tr><td>{e(n)}<td>{ar} {e(lb)}<td>{wt:g}<td class={'up' if fv > 0.1 else 'down' if fv < -0.1 else 'flat'}>{fv:+.2f}<td>{wt * fv:+.2f}</tr>" for n, lb, ar, wt, fv in contrib)
    acts = "".join(f"<li>{e(a_)}</li>" for a_ in ract)
    regime_cls = "up" if score >= 0.5 else "down" if score < -0.4 else "flat"
    dirsec = (f"<h2 class=cat-h>📍 지금의 방향과 투자 의견</h2>"
              f"<section class='card regime f-{regime_cls}'><div class=rh><span class=ricon>{ricon}</span><div><div class=meta>DB에 저장된 선행지표 {len(contrib)}개의 방향을 종합한 판정 · {e(today)}</div>"
              f"<h3 style='font-size:22px;margin:2px 0'>{e(regime)} <span class=meta style='font-size:14px'>종합 점수 {score:+.2f} (−1 수축 ~ +1 확장)</span></h3></div></div>"
              f"<div class=gauge><div class=gz><span style='left:{pos_:.1f}%'></span></div><div class=gl><span>수축 −1</span><span>0</span><span>확장 +1</span></div></div>"
              f"<p><b>주식 비중 가이드:</b> {e(rstock)}</p><ul class=acts>{acts}</ul>"
              f"<div class=meta>근거: {' · '.join(yt(i) for i in rvids)}</div>"
              f"<details><summary>점수는 어떻게 계산했나</summary><div style='overflow-x:auto'><table><tr><th>지표<th>방향<th>가중치<th>점수<th>기여</tr>{crows}</table></div>"
              f"<p class=meta>점수 = 가중 평균. 방향별 점수: 상승·바닥 후 반등 +1, 상승 둔화·바닥 다지기 +0.25, 정점 부근 −0.25, 하락·정점 후 하락 −1 (스프레드처럼 오르면 위험한 지표는 부호 반전). "
              f"방향은 최근 15년 월간 변화의 중앙값을 '잡음'으로 보고, 3개월 변화가 그보다 크면 오르는 중/내려오는 중, 작으면 6개월 변화로 정점권·바닥권을 가른다. "
              f"가중치는 교수가 방향 기준으로 삼는 한국 선행지수에 가장 크게 뒀다. 판정 기준: +0.5 이상 확장 · −0.4 미만 수축 · 그 사이 전환(혼조). 매 실행마다 DB(leading_signal·leading_regime)에 날짜별로 저장된다.</p></details>"
              f"<p class=meta style='margin-top:8px'>⚠️ {e(S.DISCLAIMER)}</p></section>"
              f"<h3 class=sub-h>지표별 방향과 그 방향일 때 영상 속 의견</h3>"
              f"<p class=meta>화살표 색: 초록 = 경기·위험선호에 우호적인 방향, 빨강 = 비우호적, 회색 = 중립·확인용. 하이일드 스프레드·유가처럼 오르면 부담인 지표는 오름이 빨강이다.</p>"
              f"<div class=grid3>{cards_dir}</div>")
    badges = {dmeta[sid][4]: (g["arrow"], fcls(g), f"{dmeta[sid][1]}: {g['label']}") for sid, g in sig.items() if dmeta[sid][4]}

    # ── 지금 상태 ──
    PCT = {"kospi", "spx", "dubai", "kr_exp_ma3"}
    srow = ""
    for sid, name, how, good in S.STATUS:
        d = ser.get(sid) or {}
        if not d: continue
        ks = sorted(d); lm = ks[-1]; lv = d[lm]
        def chg(k):
            p = d.get(add_m(lm, -k))
            if p is None: return None
            return (lv / p - 1) * 100 if sid in PCT else lv - p
        c3, c12 = chg(3), chg(12)
        unit = "%" if sid in PCT else ""
        def cell(c):
            if c is None: return "-"
            flat = abs(c) < (1.0 if sid in PCT else 0.05)
            cls = "flat" if flat else ("up" if c > 0 else "down")
            return f"<span class={cls}>{'▲' if c > 0 and not flat else '▼' if c < 0 and not flat else '■'} {c:+.2f}{unit}</span>"
        g = sig.get(sid)
        sigtxt = (f"<span class={fcls(g)}>{g['arrow']} {e(g['label'])}</span>") if g else "⚪"
        peak = ""
        if g and g["state"] in ("peak_down", "down", "topping", "slowing"):
            ago_txt = "이번 달이 최고" if g["ago_peak"] == 0 else f"{g['ago_peak']}개월 전"
            peak = f"<br><span class=meta>12개월 내 최고 {g['peak'][:7]} ({d[g['peak']]:.2f}) · {ago_txt}</span>"
        srow += (f"<tr><td><b>{e(name)}</b><br><span class=meta>{e(how)}</span><td>{fmtv(lv)}<br><span class=meta>{lm[:7]}</span>{peak}<td>{cell(c3)}<td>{cell(c12)}<td>{sigtxt}</tr>")
    status = ("<div style='overflow-x:auto'><table><tr><th>지표<th>최근값<th>3개월 변화<th>12개월 변화<th>방향</tr>" + srow + "</table></div>"
              "<p class=meta>방향은 DB의 월별 값으로 계산한 상태다(위 '지금의 방향' 카드와 같은 값). 지표마다 발표 시점이 달라 마지막 월이 서로 다르다.</p>")

    # 한국 선행지수 하락 에피소드
    kc = ser["kr_cli"]; zz, ext, dr = zigzag(kc, 1.5)
    eps = [(a, b, months_between(a[1], b[1]), a[2] - b[2]) for a, b in zip(zz, zz[1:]) if a[0] == "P" and b[0] == "T" and a[1] >= "1995-01-01"]
    durs = [x[2] for x in eps]
    med, avg = statistics.median(durs), sum(durs) / len(durs)
    erow = "".join(f"<tr><td>{a[1][:7]}<td>{b[1][:7]}<td>{n}개월<td>{dp:.1f}pt</tr>" for a, b, n, dp in eps)
    kl = max((m for m in kc if m >= add_m(max(kc), -17)), key=lambda m: (round(kc[m], 2), m)); kl_ago = months_between(kl, max(kc))
    ep_html = (f"<div style='overflow-x:auto'><table><tr><th>정점<th>저점<th>하락 기간<th>하락 폭</tr>{erow}</table></div>"
               f"<p>통계청 한국 선행지수 순환변동치가 1.5pt 이상 내려왔다 올라간 하락 구간은 1995년 이후 {len(durs)}번, "
               f"기간은 <b>중앙값 {med:.0f}개월 · 평균 {avg:.0f}개월</b>(최소 {min(durs)} ~ 최대 {max(durs)}개월)이다. "
               f"교수가 말하는 '통상 20개월'은 이 평균과 비슷하지만, 구간마다 편차가 크다. "
               f"최근 정점 후보는 {kl[:7]}({kc[kl]:.1f}), 현재 {kl_ago}개월째 내려오는 중이라 아직 하락 구간으로 확정된 것은 아니다(1.5pt 되돌림 기준). "
               f"정점 {kl[:7]}에 중앙값·평균을 더하면 하락 종료 시점은 대략 <b>{add_m(kl, int(med))[:7]} ~ {add_m(kl, round(avg))[:7]}</b>이지만, 이는 과거 평균을 단순히 얹은 것일 뿐 예측이 아니다.</p>")

    # 한국→미국 전환점 비교
    kt = turning_lags(ser["oecd_kr_cli"], ser["oecd_us_cli"], 1.2)
    if kt:
        lags = [x[3] for x in kt]
        trows = "".join(f"<tr><td>{'정점' if t == 'P' else '저점'}<td>{m1[:7]}<td>{m2[:7]}<td>{l:+d}개월</tr>" for t, m1, m2, l in kt)
        tp_html = (f"<details><summary>전환점으로 본 한국→미국 시차 ({len(kt)}건, 중앙값 {statistics.median(lags):+.0f}개월)</summary>"
                   f"<div style='overflow-x:auto'><table><tr><th>종류<th>한국 OECD 선행지수<th>미국 OECD 선행지수<th>한국이 앞선 개월</tr>{trows}</table></div>"
                   f"<p class=meta>1.2pt 이상 되돌린 전환점을 같은 종류끼리 ±12개월 안에서 짝지었다. 양수는 한국이 먼저, 음수는 미국이 먼저. 건수가 적고 편차가 크다는 점에 주의.</p></details>")
    else:
        tp_html = ""

    # 미국 금리차 역전 → 침체
    t3 = ser["t10y3m"]; recs = [cols[a] for a, b in rec if cols[a] >= "1995"]; irows = ""
    for rs in recs:
        run_start = None; run = None
        for m in sorted(t3):
            if m >= rs: break
            if t3[m] < 0:
                if run is None: run = m
            else:
                if run is not None: run_start = run; run = None
        run_start = run_start or run
        irows += (f"<tr><td>{rs[:7]}<td>{run_start[:7] if run_start else '-'}<td>{months_between(run_start, rs) if run_start else '-'}개월</tr>")
    inv_html = (f"<div style='overflow-x:auto'><table><tr><th>침체 시작(NBER)<th>직전 금리차 역전 시작<th>역전 → 침체</tr>{irows}</table></div>"
                f"<p class=meta>미국 10년−3개월 월평균이 0 아래로 내려간 마지막 구간의 첫 달을 기준으로 했다. 역전은 침체의 '예고'일 뿐 시점을 정확히 맞추지는 못한다.</p>") if irows else ""

    # ── 조립 ──
    esc = e
    concept = "".join(f"<div class=card><h3>{esc(a)} 지표</h3><p><b>{esc(b)}</b></p><p class=meta style='font-size:14px'>{esc(c)}</p></div>" for a, b, c in S.CONCEPT)
    why = "".join(f"<li>{esc(w)}</li>" for w in S.WHY)
    off = S.OFFICIAL
    official = (f"<div style='overflow-x:auto'><table><tr><th>구분<th>통계청 경기종합지수 구성 항목(예)</tr>"
                f"<tr><td><b>선행</b><td>{esc(off['lead'])}<tr><td><b>동행</b><td>{esc(off['coin'])}<tr><td><b>후행</b><td>{esc(off['lag'])}</table></div>"
                f"<p class=meta><span class=tag>영상 밖 일반 지식</span> {esc(off['note'])}</p>")
    effects = "".join(f"<div class=card><h3>{x['icon']} {esc(x['title'])}</h3><p class=meta>시작점: {esc(x['from'])}</p><p style='font-size:14px'>{esc(x['body'])}</p><div class=meta>근거: {' · '.join(yt(i) for i in x['src'])}</div></div>" for x in S.EFFECTS)
    erows = "".join(f"<tr><td><b>{esc(dict((n[0], n[1]) for n in S.NODES)[a].replace(chr(10), ' '))}</b> → <b>{esc(dict((n[0], n[1]) for n in S.NODES)[b].replace(chr(10), ' '))}</b><td>{esc(lab)}<td>{' · '.join(yt(i) for i in v)}</tr>" for a, b, lab, v, st_ in S.EDGES)
    nrows = "".join(f"<tr><td><b>{esc(n[1].replace(chr(10), ' '))}</b><td>{esc(n[4])}</tr>" for n in S.NODES)

    cards = ""
    for p in S.PAIRS:
        opts = p["options"]
        sel = ("<select>" + "".join(f"<option value={i}>{esc(o['label'])}</option>" for i, o in enumerate(opts)) + "</select>") if len(opts) > 1 else f"<b>{esc(opts[0]['label'])}</b>"
        extra = tp_html if p["id"] == "korea_us" else ""
        if p["id"] == "curve": extra = inv_html
        cards += (f"<section class='card pc' id='p-{p['id']}' data-pair='{p['id']}'><h3>{esc(p['title'])}</h3>"
                  f"<div class=claim>🎬 <b>영상의 주장</b> — {esc(p['claim_text'])}<br><span class=meta>근거: {' · '.join(yt(i) for i in p['src'])}</span></div>"
                  f"<p style='font-size:14px;margin:6px 0'><b>왜 선행하나?</b> {esc(p['why'])}</p>"
                  f"<p class=meta style='margin:4px 0'><b>읽는 법:</b> {esc(p['read'])}</p>"
                  f"<div class=ctl>{sel}<span class=meta>기간</span><button data-win=0 class=on>전체</button><button data-win=15>15년</button><button data-win=8>8년</button><button data-win=3>3년</button></div>"
                  f"<div class=lgd><span class=s1>━</span> <span class=lg1></span> &nbsp; <span class=s2>━</span> <span class=lg2></span> &nbsp; <span class=meta>회색 띠 = 미국 경기침체(NBER)</span></div>"
                  f"<svg class=cv viewBox='0 0 820 300' role=img aria-label='{esc(p['title'])} 그래프'></svg>"
                  f"<div class=tip> </div>"
                  f"<div class=ctl><span class=meta>선행 시차</span><span class=kv></span><input type=range min=-12 max=12 step=1 value=0><button data-jump=claim>영상 주장</button><button data-jump=best>데이터 최적</button></div>"
                  f"<svg class=bars viewBox='0 0 820 120'></svg><div class=info style='font-size:13.5px'></div>{extra}</section>")

    vtab = (f"<div style='overflow-x:auto'><table class=vtab><tr><th>쌍 (앞 → 뒤)<th>영상 주장<th>데이터상 최적 시차<th>주장 시차의 상관<th>판정</tr>{vrows}</table></div>"
            f"<p class=meta>시차 +k = 앞 지표를 k개월 뒤로 밀었을 때 뒤 지표와 가장 잘 맞는다는 뜻. 상관은 {START[:4]}년 이후 월별 값 기준(신용스프레드는 2023-12 이후). "
            f"🟢 일치(±1개월) · 🟡 대체로 일치(±3개월) · ⚪ 상관 0.3 미만 · 🔴 다르거나 반대 방향. 주가는 선행지수의 구성 항목이라 주가가 앞서는 결과는 어느 정도 당연하다.</p>")

    vids = "".join(f"<tr><td>{esc(v[1])}<td><a href='https://www.youtube.com/watch?v={esc(i)}' target=_blank>{esc(v[2])}</a><br><span class=meta>{esc(v[0])}</span></tr>" for i, v in sorted(S.VIDEOS.items(), key=lambda kv: kv[1][1], reverse=True))
    srcrows = "".join(f"<tr><td>{esc(m['name'])}<td>{esc(m['source'])}<td><span class=meta>{esc(m['symbol'])}</span><td>{m['first'][:7]} ~ {m['last'][:7]}</tr>" for s, m in sorted(meta.items(), key=lambda kv: kv[1]['name']) if m["source"] != "derived")
    fetched = max((m["fetched_at"] for m in meta.values()), default="")[:16]

    body = (f"<h1>🧭 선행지수 정리 — 무엇이 무엇을 앞서는가</h1>"
            f"<p class=meta>지금까지 모인 유튜브 영상(주로 김영익 교수)에서 나온 선행 관계를 모으고, 같은 쌍을 공개 시계열로 다시 그렸다 · 시계열 수집 {esc(fetched)} · <a href='kimyoungik.html'>🎓 김영익 교수 페이지</a> · <a href='indicators.html'>📊 지표</a> · <a href='index.html'>🏠 홈</a></p>"
            f"<section class=card><h3>한 줄 요약</h3><p>{esc(S.SUMMARY)}</p></section>"
            f"{dirsec}"
            f"{lagsec}"
            f"<h2 class=cat-h>1️⃣ 선행이란 무엇인가</h2><div class=grid3>{concept}</div>"
            f"<div class=card><h3>왜 어떤 지표는 먼저 움직일까</h3><ul>{why}</ul>{lead_lag_svg()}<p class=meta style='margin-top:8px'>{esc(S.CIRCULAR)}</p></div>{official}"
            f"<h2 class=cat-h>2️⃣ 선행의 사슬 — 누가 누구에게 영향을 주나</h2>"
            f"<p class=meta>왼쪽일수록 먼저 움직인다. 상자 모서리의 동그라미 화살표가 지금의 방향(▲오름 ▼내림 ▶정점·바닥권)이고 색은 우호(초록)·비우호(빨강)·중립(회색)이다. 실선은 영상에서 비교적 분명히 말한 관계, 점선은 간접적이거나 한 영상에서만 언급된 관계. 상자에 마우스를 올리면 설명이 나온다.</p>"
            f"<div style='overflow-x:auto'>{chain_svg(badges)}</div>"
            f"<details><summary>관계와 근거 영상 표로 보기</summary><div style='overflow-x:auto'><table><tr><th>관계<th>시차<th>근거</tr>{erows}</table></div><div style='overflow-x:auto'><table><tr><th>항목<th>설명</tr>{nrows}</table></div></details>"
            f"<h2 class=cat-h>3️⃣ 어디에 영향을 주나 — 투자·생활로 이어지는 길</h2><div class=grid3>{effects}</div>"
            f"<h2 class=cat-h>4️⃣ 영상의 주장, 데이터로 맞나?</h2>{vtab}"
            f"<h2 class=cat-h>5️⃣ 선행 지표와 따라가는 지표를 같이 보기</h2>"
            f"<p class=meta>파란 선(앞 지표)을 슬라이더로 오른쪽으로 밀어 주황 선(뒤 지표)과 맞춰 보세요. 파란 점선은 앞 지표가 알려 주는 '앞으로의 방향'입니다. 그래프 위에 마우스를 올리면 값이 보입니다.</p>{cards}"
            f"<h2 class=cat-h>6️⃣ 지금은 어디쯤?</h2>{status}"
            f"<h3 class=sub-h>한국 선행지수 하락 구간의 길이 (교수의 '약 20개월')</h3>{ep_html}"
            f"<h2 class=cat-h>7️⃣ 읽을 때 조심할 점</h2><ul>{''.join(f'<li>{esc(c)}</li>' for c in S.CAUTIONS)}</ul>"
            f"<h2 class=cat-h>🎬 근거 영상</h2><details><summary>{len(S.VIDEOS)}개</summary><div style='overflow-x:auto'><table><tr><th>업로드<th>제목</tr>{vids}</table></div></details>"
            f"<h2 class=cat-h>🗂️ 그래프 데이터 출처</h2><details><summary>{len(meta)}개 계열</summary><div style='overflow-x:auto'><table><tr><th>계열<th>출처<th>코드<th>기간</tr>{srcrows}</table></div>"
            f"<p class=meta>일별 값은 월평균, 주가·환율은 월 마지막 값. 수출은 한국은행 ECOS 통관 수출금액(월합계)이라 교수가 쓰는 '조업일수 감안 일평균'과는 다르다. 새로 받기: <code>{esc(S.REFRESH)}</code></p></details>"
            f"<script id=ldata type='application/json'>{json.dumps(data, ensure_ascii=False, separators=(',', ':'))}</script><script>{JS}</script>")
    (R.OUT / "leading.html").write_text(R.page("선행지수 정리", f"<style>{CSS_X}</style>" + body, "🧭"), encoding="utf-8")


if __name__ == "__main__":
    build()
    print("reports/leading.html 생성")
