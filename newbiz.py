"""New Business 페이지: 사업 아이템 조사 글 모음 (reports/newbiz.html 목록 + reports/newbiz_<slug>.html 본문).

글을 추가하려면 newbiz_<slug>.py 를 만들고(META 사전과 body() 함수) 아래 ARTICLES 에 모듈 이름을 넣는다. 글은 DB 를 쓰지 않는다.
  uv run newbiz.py     # newbiz 페이지만 다시 만들기 (report.build_all 도 호출)
"""
import importlib
from html import escape as e

ARTICLES = ["newbiz_solar"]

# 그래프 색: 검증한 순서(파랑·주황·청록·노랑). 밝은/어두운 화면에서 각각 다른 단계를 쓴다.
CSS = """<style>
:root{--s1:#257de0;--s2:#f47230;--s3:#00b894;--s4:#f2a600;--grid:#e3e2dc}
@media(prefers-color-scheme:dark){:root{--s1:#338ced;--s2:#e76624;--s3:#00a888;--s4:#d28e05;--grid:#33332f}}
.nb h2{font-size:19px;color:var(--fg);margin:34px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--ac)}.nb h3{font-size:15.5px;margin:18px 0 4px}
.nb .wide{overflow-x:auto}.nb td.r,.nb th.r{text-align:right;white-space:nowrap}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:12px 0}.kpi{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px 12px}
.kpi b{display:block;font-size:22px;line-height:1.25}.kpi small{color:var(--mu)}
figure{margin:14px 0;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px}figcaption{font-weight:700;font-size:14px;margin-bottom:6px}
figure svg{width:100%;height:auto;display:block}figure svg text{fill:var(--mu);font-size:12px}figure svg text.v{fill:var(--fg)}
.lg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12.5px;margin-bottom:4px}.lg i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.toc a{display:inline-block;margin:0 10px 4px 0}.warn{border-left:4px solid #d9822b}
.calc{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}.calc label{font-size:12.5px;color:var(--mu);display:block}
.calc input{width:100%;box-sizing:border-box;font:inherit;padding:4px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);color:var(--fg)}
.src li{margin:0 0 10px}
</style>"""


def _nice(hi):
    import math
    step = 10 ** math.floor(math.log10(hi / 4 or 1))
    for m in (1, 2, 2.5, 5, 10):
        if hi / (step * m) <= 5: return step * m
    return step * 10


def _frame(w, h, lo, hi, step, unit, pad):
    left, top, right, bottom = pad
    y = lambda v: top + (hi - v) / (hi - lo) * (h - top - bottom)
    g, v = "", lo
    while v <= hi + 1e-9:
        g += f"<line x1={left} x2={w - right} y1={y(v):.1f} y2={y(v):.1f} stroke='var(--grid)'/><text x={left - 6} y={y(v) + 4:.1f} text-anchor=end>{v:,.0f}</text>"
        v += step
    return y, g + f"<text x=2 y=11>{e(unit)}</text>"


def _table(head, rows):
    return ("<details><summary class=meta>값 표로 보기</summary><div class=wide><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in rows) + "</table></div></details>")


def bar_chart(title, data, unit, fmt="{:,.0f}", note=""):
    """data = [(라벨, 값)]. 0 에서 시작하는 한 계열 막대(값을 직접 표시)."""
    w, h, pad = 700, 250, (56, 22, 10, 26)
    step = _nice(max(v for _, v in data) * 1.1)
    hi = (int(max(v for _, v in data) * 1.1 / step) + 1) * step
    y, g = _frame(w, h, 0, hi, step, unit, pad)
    slot = (w - pad[0] - pad[2]) / len(data); bw = min(44, slot * 0.62)
    for i, (label, v) in enumerate(data):
        x = pad[0] + slot * i + (slot - bw) / 2; top, base = y(v), y(0); r = min(4, bw / 2, base - top)
        g += (f"<path fill='var(--s1)' d='M{x:.1f},{base:.1f}V{top + r:.1f}Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f}H{x + bw - r:.1f}Q{x + bw:.1f},{top:.1f} {x + bw:.1f},{top + r:.1f}V{base:.1f}Z'>"
              f"<title>{e(label)}: {fmt.format(v)} {e(unit)}</title></path>"
              f"<text class=v x={x + bw / 2:.1f} y={top - 5:.1f} text-anchor=middle>{fmt.format(v)}</text><text x={x + bw / 2:.1f} y={h - 8} text-anchor=middle>{e(label)}</text>")
    return (f"<figure><figcaption>{e(title)}</figcaption><svg viewBox='0 0 {w} {h}' role=img aria-label='{e(title)}'>{g}</svg>"
            + (f"<div class=meta>{note}</div>" if note else "") + _table(["구분", unit], [(a, fmt.format(b)) for a, b in data]) + "</figure>")


def line_chart(title, labels, series, unit, zero=True, every=1, note="", fmt="{:,.0f}"):
    """series = [(이름, [값])] 최대 4개. 마우스를 올리면 값이 보이고, 계열이 둘 이상이면 범례를 둔다."""
    w, h, pad = 700, 260, (62, 22, 18, 26)
    vals = [v for _, vs in series for v in vs]
    lo, hi = (min(0, min(vals)) if zero else min(vals) * 0.9), max(vals) * 1.05
    step = _nice(hi - lo)
    lo, hi = int(lo // step) * step, (int(hi // step) + 1) * step
    y, g = _frame(w, h, lo, hi, step, unit, pad)
    x = lambda i: pad[0] + (w - pad[0] - pad[2]) * i / max(1, len(labels) - 1)
    if lo < 0: g += f"<line x1={pad[0]} x2={w - pad[2]} y1={y(0):.1f} y2={y(0):.1f} stroke='var(--mu)'/>"
    for i, label in enumerate(labels):
        if i % every == 0 or i == len(labels) - 1 and (len(labels) - 1) % every > every // 2:
            g += f"<text x={x(i):.1f} y={h - 8} text-anchor=middle>{e(label)}</text>"
    for n, (name, vs) in enumerate(series):
        col = f"var(--s{n + 1})"
        g += f"<polyline fill=none stroke='{col}' stroke-width=2 stroke-linejoin=round points='{' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(vs))}'/>"
        for i, v in enumerate(vs):
            g += f"<circle cx={x(i):.1f} cy={y(v):.1f} r=7 fill=transparent><title>{e(name)} · {e(labels[i])}: {fmt.format(v)} {e(unit)}</title></circle>"
        g += f"<circle cx={x(len(vs) - 1):.1f} cy={y(vs[-1]):.1f} r=4 fill='{col}' stroke='var(--card)' stroke-width=2 />"
    legend = "<div class=lg>" + "".join(f"<span><i style='background:var(--s{n + 1})'></i>{e(s[0])}</span>" for n, s in enumerate(series)) + "</div>" if len(series) > 1 else ""
    table = _table(["시점"] + [s[0] for s in series], [[l] + [fmt.format(s[1][i]) for s in series] for i, l in enumerate(labels)])
    return (f"<figure><figcaption>{e(title)}</figcaption>{legend}<svg viewBox='0 0 {w} {h}' role=img aria-label='{e(title)}'>{g}</svg>"
            + (f"<div class=meta>{note}</div>" if note else "") + table + "</figure>")


def build():
    import report as R
    R.OUT.mkdir(exist_ok=True)
    mods = sorted((importlib.import_module(m) for m in ARTICLES), key=lambda m: m.META["date"], reverse=True)
    nav = "<a href='index.html'>🏠 홈</a>"
    cards = ""
    for m in mods:
        meta, url = m.META, f"newbiz_{m.META['slug']}.html"
        cards += (f"<section class=card><h3><a href='{url}'>{e(meta['title'])}</a></h3><div class=meta>{e(meta['date'])} 조사 · {''.join(f'<span class=chip>{e(t)}</span>' for t in meta['tags'])}</div>"
                  f"<p>{e(meta['summary'])}</p><ul>{''.join(f'<li>{e(p)}</li>' for p in meta['points'])}</ul></section>")
        page = f"<div class=nb><p class=meta><a href='newbiz.html'>💡 New Business 목록</a> · {nav}</p>{m.body()}</div>"
        (R.OUT / url).write_text(R.page(meta["title"], CSS + page, "💡"), encoding="utf-8")
    table = "".join(f"<tr><td><a href='newbiz_{m.META['slug']}.html'>{e(m.META['title'])}</a></td><td>{e(m.META['verdict'])}</td><td>{e(m.META['date'])}</td></tr>" for m in mods)
    body = (f"<div class=nb><h1>💡 New Business</h1><p class=meta>사업 아이템 조사 모음 · {len(mods)}건 · {nav}</p>"
            f"<div class=wide><table><tr><th>아이템</th><th>한 줄 판단</th><th>조사일</th></tr>{table}</table></div>{cards}</div>")
    (R.OUT / "newbiz.html").write_text(R.page("New Business", CSS + body, "💡"), encoding="utf-8")


if __name__ == "__main__":
    build(); print("reports/newbiz.html 생성")
