"""서준식 교수(숭실대 경제학과) 투자 방식 정리 페이지 (reports/seojunsik.html).

조사 내용은 DB research 표(slug=seojunsik), '지금 상태'는 indicator_values 표에서 읽어 만든다(웹 호출 없음).
근거는 기사·블로그·영상 요약 글이다(영상 자막은 YouTube IP 차단으로 읽지 못함) — seojunsik_data.py 머리말 참고.

  uv run seojunsik.py import    # seojunsik_data.py 의 조사 내용을 DB 에 저장
  uv run seojunsik.py build     # reports/seojunsik.html 만들기 (report.build_all 도 호출)
"""
import json, sys
from html import escape as e
import db as D

SLUG = "seojunsik"
DDL = """CREATE TABLE IF NOT EXISTS research(slug TEXT PRIMARY KEY, title TEXT, data_json TEXT, updated_at TEXT);"""
KEYS = ("CHANNEL", "PERSON", "SUMMARY", "RULES", "CALC_DEFAULT", "STATUS", "HOWTO", "CAUTIONS", "ARTICLES", "VIDEOS")


def con_():
    con = D.connect(); con.executescript(DDL); return con


def do_import(con):
    import seojunsik_data as S
    data = {k: getattr(S, k) for k in KEYS}
    con.execute("INSERT OR REPLACE INTO research VALUES(?,?,?,?)", (SLUG, "서준식 교수 투자 방식", json.dumps(data, ensure_ascii=False), D.now()))
    con.commit(); print("research 저장:", {k: len(v) for k, v in data.items() if hasattr(v, "__len__")})


def latest(con, sym):
    r = con.execute("SELECT v.date, v.value FROM indicator_values v JOIN indicators i ON i.id=v.indicator_id "
                    "WHERE i.source=? AND i.symbol=? AND i.active=1 ORDER BY v.date DESC LIMIT 1", tuple(sym)).fetchone()
    return (r[0], r[1]) if r else None


CALC = """<section class=card><h3>🧮 매수 가능 주가 계산기 (채권형 주식 4단계)</h3>
<p class=meta>2019년 기사(뉴스토마토)의 계산법: 매수 가능 주가 = 순자산(BPS) × (1+ROE)^N ÷ (1+목표수익률)^N. 아래 값을 바꿔 보세요. 투자 권유가 아니라 계산 예시입니다.</p>
<div class=calc>
<label>순자산가치(BPS, 원) <input id=c-bps type=number value="{bps}" step=1000></label>
<label>향후 평균 ROE(%) <input id=c-roe type=number value="{roe}" step=0.5></label>
<label>목표수익률(%/년) <input id=c-tgt type=number value="{target}" step=0.5></label>
<label>기간(년) <input id=c-n type=number value="{years}" step=1 min=1></label>
</div>
<p id=c-out style="font-size:16px;margin:10px 0 0"></p>
<p class=meta>기사 예시: BPS 3만원·ROE 8%·목표 15%·10년 → 10년 뒤 순자산 약 6만4,800원 → 매수 가능 주가 약 1만6,000원.</p>
<script>
(function(){{
  var $=function(i){{return document.getElementById(i)}};
  function calc(){{
    var b=+$('c-bps').value, r=+$('c-roe').value/100, t=+$('c-tgt').value/100, n=+$('c-n').value;
    if(!(b>0&&n>0&&t>-1)){{ $('c-out').textContent='값을 확인하세요'; return }}
    var fut=b*Math.pow(1+r,n), buy=fut/Math.pow(1+t,n);
    $('c-out').innerHTML='<b>'+n+'년 뒤 예상 순자산 '+Math.round(fut).toLocaleString()+'원</b> → <b style="color:var(--ac)">매수 가능 주가 '+Math.round(buy).toLocaleString()+'원</b> <span class=meta>(현재 BPS 대비 '+(buy/b*100).toFixed(0)+'% = PBR '+(buy/b).toFixed(2)+'배 이하)</span>';
  }}
  ['c-bps','c-roe','c-tgt','c-n'].forEach(function(i){{$(i).addEventListener('input',calc)}}); calc();
}})();
</script></section>"""


def build(con=None):
    import report as R
    con = con or con_()
    row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    if not row:
        do_import(con); row = con.execute("SELECT data_json, updated_at FROM research WHERE slug=?", (SLUG,)).fetchone()
    d = json.loads(row["data_json"])
    art = {a["id"]: a for a in d["ARTICLES"]}
    cite = lambda ids: " ".join(f"<a class=chip href='{e(art[i]['url'])}' target=_blank title='{e(art[i]['title'])}'>{e(art[i]['kind'])} {e(art[i]['date'][:7])}</a>" for i in ids if i in art)

    rows = ""
    for s in d["STATUS"]:
        now = latest(con, s["sym"])
        val = f"<b>{s['fmt'].format(now[1])}</b><br><span class=meta>{e(now[0])}</span>" if now else "<span class=meta>값 없음</span>"
        rows += f"<tr><td><b>{e(s['name'])}</b><td>{val}<td>{e(s['ref'])}<td>{e(s['use'])}</tr>"
    status = ("<div style='overflow-x:auto'><table><tr><th>지표<th>현재값(우리 DB)<th>서 교수의 기준·발언<th>어디에 쓰나</tr>" + rows + "</table></div>"
              "<p class=meta>⚠️ 기준 숫자는 2024년 3월 인터뷰 기준이라, 지금 값과 비교해 '서 교수가 지금 사라고 한다'는 뜻이 아니다. "
              "그때 어떤 수준을 매수 가격대로 봤는지 참고하는 용도다. 한국 시장 PER은 우리 DB에 없어 이익수익률(PER 역수)과 채권 금리 비교는 직접 해야 한다.</p>")

    rules = "".join(f"<section class=card><h3>{i}. {e(r['title'])}</h3><p>{e(r['body'])}</p><div class=meta>시점: {e(r['when'])} · 근거: {cite(r['src'])}</div></section>" for i, r in enumerate(d["RULES"], 1))
    how = "".join(f"<li><b>{e(h['step'])}</b><br>{e(h['body'])}</li>" for h in d["HOWTO"])
    cau = "".join(f"<li>{e(c)}</li>" for c in d["CAUTIONS"])
    arts = "".join(f"<tr><td>{e(a['date'])}<td>{e(a['kind'])}<td><a href='{e(a['url'])}' target=_blank>{e(a['title'])}</a></tr>" for a in sorted(d["ARTICLES"], key=lambda a: a["date"], reverse=True))
    vids = "".join(f"<tr><td>{e(v[1])}<td>{e(v[2])}<td>{e(v[3])}<td><a href='https://www.youtube.com/watch?v={e(v[0])}' target=_blank>{e(v[4])}</a></tr>" for v in sorted(d["VIDEOS"], key=lambda v: v[1], reverse=True))
    c = d["CALC_DEFAULT"]

    body = (f"<h1>🏛️ 서준식 교수 투자 방식 — 채권쟁이가 주식을 사는 법</h1>"
            f"<p class=meta>{e(d['CHANNEL']['note'])} 채널 <a href='{e(d['CHANNEL']['url'])}' target=_blank>{e(d['CHANNEL']['name'])}</a> · 조사 내용 저장 {e(row['updated_at'][:16])} · '지금 상태'는 만들 때마다 DB 값으로 갱신 · <a href='index.html'>🏠 홈</a></p>"
            f"<section class=card style='border-color:#d9822b'><b>⚠️ 근거 안내</b><br>영상 자막을 읽지 못해(서버 IP가 YouTube에 차단됨), 기사 2건·영상 요약 글 1건·블로그 메모 1건을 근거로 정리했다. 각 항목에 근거와 발언 시점을 붙였다. 영상 14개는 제목만 확인했다.</section>"
            f"<section class=card><h3>누구인가</h3><p>{e(d['PERSON'])}</p></section>"
            f"<section class=card><h3>한 줄 요약</h3><p>{e(d['SUMMARY'])}</p></section>"
            f"{CALC.format(**c)}"
            f"<h2 class=cat-h>📍 지금 상태 (서 교수의 기준 지표 + 우리 DB 값)</h2>{status}"
            f"<h2 class=cat-h>📚 투자 원칙 {len(d['RULES'])}가지</h2>{rules}"
            f"<h2 class=cat-h>🛠️ 따라 하려면</h2><ol class=how>{how}</ol>"
            f"<h2 class=cat-h>⚠️ 주의할 점</h2><ul>{cau}</ul>"
            f"<h2 class=cat-h>📰 읽은 자료</h2><div style='overflow-x:auto'><table><tr><th>날짜<th>종류<th>제목(링크)</tr>{arts}</table></div>"
            f"<h2 class=cat-h>🎬 서준식 교수 영상 (제목만 확인, 자막 미확인)</h2><details open><summary>{len(d['VIDEOS'])}개</summary><div style='overflow-x:auto'><table><tr><th>업로드<th>채널<th>길이<th>제목</tr>{vids}</table></div></details>")
    css = ("<style>ol.how li{margin:10px 0}.chip{background:var(--chip);border-radius:6px;padding:1px 7px;font-size:12px;text-decoration:none;margin-right:4px}"
           ".calc{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.calc label{font-size:13px;color:var(--mu)}"
           ".calc input{display:block;width:100%;box-sizing:border-box;margin-top:3px;padding:6px 8px;font-size:15px;border:1px solid var(--bd);border-radius:6px;background:var(--card);color:var(--fg)}</style>")
    (R.OUT / "seojunsik.html").write_text(R.page("서준식 교수 투자 방식", css + body, "🏛️"), encoding="utf-8")


if __name__ == "__main__":
    c = con_()
    do_import(c)
    if (sys.argv[1:] or ["build"])[0] != "import": build(c); print("reports/seojunsik.html 생성")
