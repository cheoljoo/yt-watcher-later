"""날짜·주제별 보기 페이지 (reports/browse.html).

DB 의 분석 완료 영상을 YouTube 업로드일 최신순으로 모두 담고(1일 리포트와 같은 카드),
브라우저에서 주제 / 기간 / 한 페이지 개수를 골라 걸러 본다.

  uv run browse.py     # reports/browse.html 만 다시 만들기 (report.build_all 도 호출)
"""
from html import escape as e
import db as D

CSS = """<style>
.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--bd);padding:10px 0;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
.bar label{font-size:13px;color:var(--mu)}.bar select{font:inherit;margin-left:4px;padding:4px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
.pager{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}.pager button{font:inherit;padding:3px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button.on{background:var(--ac);color:#fff;border-color:var(--ac)}.pager button:disabled{opacity:.4;cursor:default}
.day-h{font-size:19px;margin:30px 0 0;padding-bottom:4px;border-bottom:2px solid var(--ac)}
</style>"""

JS = """<script>(function(){
var items=[].slice.call(document.querySelectorAll('.bi')),box=document.getElementById('bi-list'),
 fT=document.getElementById('f-topic'),fR=document.getElementById('f-recent'),fP=document.getElementById('f-per'),
 info=document.getElementById('bi-info'),pg=[document.getElementById('pg-top'),document.getElementById('pg-bot')],page=1,view=[];
function cutoff(days){var d=new Date();d.setDate(d.getDate()-days);return d.toISOString().slice(0,10)}
function apply(){var t=fT.value,r=fR.value,co=r==='all'?'':cutoff(+r);
 view=items.filter(function(x){if(t!=='all'){var k=t.slice(0,2),v=t.slice(2);if(k==='c:'&&x.dataset.c!==v)return false;if(k==='s:'&&x.dataset.s!==v)return false}
  return !co||x.dataset.d>=co});render()}
function render(){var per=+fP.value,n=view.length,pages=Math.max(1,Math.ceil(n/per));if(page>pages)page=pages;
 var a=(page-1)*per,b=Math.min(n,a+per),show=new Set(view.slice(a,b));
 box.querySelectorAll('.day-h').forEach(function(h){h.remove()});var last='';
 items.forEach(function(x){x.hidden=!show.has(x)});
 view.slice(a,b).forEach(function(x){if(x.dataset.d!==last){last=x.dataset.d;var h=document.createElement('h2');h.className='day-h';
  var c=view.filter(function(y){return y.dataset.d===last}).length;h.innerHTML='📅 '+last+' <span class=meta>('+c+')</span>';box.insertBefore(h,x)}});
 info.textContent=n?('조건에 맞는 영상 '+n+'개 중 '+(a+1)+'–'+b+'번째 · '+page+'/'+pages+' 쪽'):'조건에 맞는 영상이 없습니다';
 pg.forEach(function(p){p.innerHTML='';function btn(l,pn,dis,on){var q=document.createElement('button');q.textContent=l;q.disabled=dis;if(on)q.className='on';q.onclick=function(){page=pn;render();window.scrollTo(0,p===pg[1]?document.getElementById('bi-top').offsetTop:window.scrollY)};p.appendChild(q)}
  btn('‹ 이전',page-1,page<=1);var lo=Math.max(1,page-3),hi=Math.min(pages,page+3);if(lo>1)btn('1',1,false,page===1);if(lo>2)p.appendChild(document.createTextNode('…'));
  for(var i=lo;i<=hi;i++)btn(String(i),i,false,i===page);if(hi<pages-1)p.appendChild(document.createTextNode('…'));if(hi<pages)btn(String(pages),pages,false,page===pages);btn('다음 ›',page+1,page>=pages)})}
[fT,fR].forEach(function(s){s.onchange=function(){page=1;apply()}});fP.onchange=function(){page=1;render()};apply()})();
</script>"""


def build(con=None):
    import report as R
    import opinions
    con = con or D.connect(); R.OUT.mkdir(exist_ok=True)
    vs = con.execute("SELECT * FROM videos WHERE status='done' ORDER BY COALESCE(upload_date,'') DESC, COALESCE(processed_at,'') DESC").fetchall()
    cats, subs = {}, {}
    for v in vs:
        c, s = v["category"] or "기타", v["subtag"] or "기타"
        cats[c] = cats.get(c, 0) + 1
        subs.setdefault(c, {})[s] = subs.setdefault(c, {}).get(s, 0) + 1
    order = sorted(cats, key=lambda c: R.CAT_ORDER.index(c) if c in R.CAT_ORDER else len(R.CAT_ORDER))
    topic = "<option value=all>모두</option>"
    for c in order:
        topic += f"<option value='c:{e(c)}'>{R.CAT_ICON.get(c, '📌')} {e(c)} ({cats[c]})</option>"
        for s, n in sorted(subs[c].items(), key=lambda kv: (-kv[1], kv[0])):
            topic += f"<option value='s:{e(c)}/{e(s)}'>&nbsp;&nbsp;└ {e(s)} ({n})</option>"
    recent = "<option value=all>모두</option>" + "".join(f"<option value={d}>{t}</option>" for d, t in
             ((7, "최근 1주일"), (30, "최근 1개월"), (90, "최근 3개월"), (180, "최근 6개월"), (365, "최근 1년"), (730, "최근 2년")))
    per = "".join(f"<option value={n}>{n}개</option>" for n in (20, 50, 100))
    cards = "".join(
        f"<div class=bi data-d='{e(v['upload_date'] or '0000-00-00')}' data-c='{e(v['category'] or '기타')}' data-s='{e((v['category'] or '기타') + '/' + (v['subtag'] or '기타'))}' hidden>{R.card(con, v)}</div>"
        for v in vs)
    body = (f"<h1>🗂️ 날짜·주제별 보기</h1><p class=meta>분석한 영상 {len(vs)}개 · YouTube 업로드일 최신순 · 같은 날 영상끼리 묶어 1일 리포트 형식으로 보여 줍니다 · <a href='index.html'>🏠 홈</a></p>"
            f"<div class=bar id=bi-top><label>🏷️ 주제 <select id=f-topic>{topic}</select></label>"
            f"<label>📅 기간 <select id=f-recent>{recent}</select></label>"
            f"<label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
            f"<p class=meta id=bi-info></p><div class=pager id=pg-top></div><div id=bi-list>{cards}</div><div class=pager id=pg-bot></div>")
    (R.OUT / "browse.html").write_text(R.page("날짜·주제별 보기", CSS + opinions.OP_CSS + body + opinions.OP_JS + JS, "🗂️"), encoding="utf-8")


if __name__ == "__main__":
    build(); print("reports/browse.html 생성")
