"""날짜·주제별 보기 페이지 (reports/browse.html).

DB 의 분석 완료 영상을 YouTube 업로드일 최신순으로 모두 담고(1일 리포트와 같은 카드),
브라우저에서 주제 / 기간 / 정렬 / Action·별표·Script 유무 / 한 페이지 개수를 골라 걸러 본다.

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
 fT=document.getElementById('f-topic'),fR=document.getElementById('f-recent'),fO=document.getElementById('f-sort'),fA=document.getElementById('f-act'),fS=document.getElementById('f-star'),fT2=document.getElementById('f-script'),fP=document.getElementById('f-per'),
 info=document.getElementById('bi-info'),pg=[document.getElementById('pg-top'),document.getElementById('pg-bot')],page=1,view=[];
function cutoff(days){var d=new Date();d.setDate(d.getDate()-days);return d.toISOString().slice(0,10)}
function has(x,sel){return !!x.querySelector(sel)}
function sortKey(x,m){return m[0]==='u'?x.dataset.d:x.dataset.p}
function apply(){var t=fT.value,r=fR.value,co=r==='all'?'':cutoff(+r),a=fA.value,st=fS.value,sc=fT2.value;
 view=items.filter(function(x){if(t!=='all'){var k=t.slice(0,2),v=t.slice(2);if(k==='c:'&&x.dataset.c!==v)return false;if(k==='s:'&&x.dataset.s!==v)return false}
  if(a==='yes'&&!has(x,'.act-btn.on'))return false;if(a==='no'&&has(x,'.act-btn.on'))return false;
  if(st==='yes'&&!has(x,'.star-btn.on'))return false;if(st==='no'&&has(x,'.star-btn.on'))return false;
  if(sc!=='all'&&x.dataset.t!==sc)return false;
  return !co||x.dataset.d>=co});
 var m=fO.value,sg=m.slice(-3)==='asc'?1:-1;   // 정렬: u=업로드, p=처리 / desc=최근, asc=오래된
 view.sort(function(x,y){var kx=sortKey(x,m),ky=sortKey(y,m);return kx<ky?-sg:kx>ky?sg:(+x.dataset.i)-(+y.dataset.i)});render()}
function render(){var per=+fP.value,n=view.length,pages=Math.max(1,Math.ceil(n/per));if(page>pages)page=pages;
 var a=(page-1)*per,b=Math.min(n,a+per),show=new Set(view.slice(a,b));
 box.querySelectorAll('.day-h').forEach(function(h){h.remove()});var last=null,m=fO.value,byP=m[0]==='p',gk=function(x){return byP?(x.dataset.p||'').slice(0,10):x.dataset.d};
 items.forEach(function(x){x.hidden=!show.has(x)});
 view.slice(a,b).forEach(function(x){var g=gk(x);if(g!==last){last=g;var h=document.createElement('h2');h.className='day-h';
  var c=view.filter(function(y){return gk(y)===g}).length;h.innerHTML='📅 '+(byP?'처리 ':'업로드 ')+(g||'-')+' <span class=meta>('+c+')</span>';box.appendChild(h)}box.appendChild(x)});   // 정렬 순서대로 DOM 재배치
 info.textContent=n?('조건에 맞는 영상 '+n+'개 중 '+(a+1)+'–'+b+'번째 · '+page+'/'+pages+' 쪽'):'조건에 맞는 영상이 없습니다';
 pg.forEach(function(p){p.innerHTML='';function btn(l,pn,dis,on){var q=document.createElement('button');q.textContent=l;q.disabled=dis;if(on)q.className='on';q.onclick=function(){page=pn;render();window.scrollTo(0,p===pg[1]?document.getElementById('bi-top').offsetTop:window.scrollY)};p.appendChild(q)}
  btn('‹ 이전',page-1,page<=1);var lo=Math.max(1,page-3),hi=Math.min(pages,page+3);if(lo>1)btn('1',1,false,page===1);if(lo>2)p.appendChild(document.createTextNode('…'));
  for(var i=lo;i<=hi;i++)btn(String(i),i,false,i===page);if(hi<pages-1)p.appendChild(document.createTextNode('…'));if(hi<pages)btn(String(pages),pages,false,page===pages);btn('다음 ›',page+1,page>=pages)})}
[fT,fR,fO,fA,fS,fT2].forEach(function(s){s.onchange=function(){page=1;apply()}});fP.onchange=function(){page=1;render()};apply();
// 서버의 최신 액션·별표 상태를 받아 버튼 상태가 낡은 페이지에서도 필터가 맞게 한 번 더 적용
Promise.all([fetch('api/actions').then(function(r){return r.json()}),fetch('api/stars').then(function(r){return r.json()})]).then(function(z){
 items.forEach(function(x){var id=x.querySelector('.act-btn')&&x.querySelector('.act-btn').getAttribute('data-vid');if(!id)return;
  var ab=x.querySelector('.act-btn'),sb=x.querySelector('.star-btn');if(ab)ab.classList.toggle('on',!!(z[0][id]&&z[0][id].on));if(sb)sb.classList.toggle('on',!!z[1][id])});
 if(fA.value!=='all'||fS.value!=='all'){apply()}}).catch(function(){})})();
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
    sort = "".join(f"<option value={v}>{t}</option>" for v, t in (("u-desc", "업로드 (최근)"), ("u-asc", "업로드 (오래된)"), ("p-desc", "처리날짜 (최근)"), ("p-asc", "처리날짜 (오래된)")))
    act = "<option value=all>모두</option><option value=yes>Action 있는 것</option><option value=no>Action 없는 것</option>"
    star = "<option value=all>모두</option><option value=yes>별표 있는 것</option><option value=no>별표 없는 것</option>"
    script = "<option value=all>모두</option><option value=ok>Script 추출 성공</option><option value=fail>Script 추출 실패</option>"   # 실패 = 자막 없음/429(meta_only)/포기/재시도 대기
    per = "".join(f"<option value={n}>{n}개</option>" for n in (20, 50, 100))
    cards = "".join(
        f"<div class=bi data-i={i} data-t='{'ok' if v['transcript_status'] == 'ok' or (v['transcript_status'] is None and v['transcript']) else 'fail'}' data-p='{e(v['processed_at'] or v['processed_date'] or '')}' data-d='{e(v['upload_date'] or '0000-00-00')}' data-c='{e(v['category'] or '기타')}' data-s='{e((v['category'] or '기타') + '/' + (v['subtag'] or '기타'))}' hidden>{R.card(con, v)}</div>"
        for i, v in enumerate(vs))
    body = (f"<h1>🗂️ 날짜·주제별 보기</h1><p class=meta>분석한 영상 {len(vs)}개 · YouTube 정렬 기준(업로드/처리날짜)별로 같은 날 영상끼리 묶어 1일 리포트 형식으로 보여 줍니다 · <a href='index.html'>🏠 홈</a></p>"
            f"<div class=bar id=bi-top><label>🏷️ 주제 <select id=f-topic>{topic}</select></label>"
            f"<label>📅 기간 <select id=f-recent>{recent}</select></label>"
            f"<label>↕️ 정렬 <select id=f-sort>{sort}</select></label>"
            f"<label>🎯 Action <select id=f-act>{act}</select></label>"
            f"<label>⭐ 인상 깊은 영상 <select id=f-star>{star}</select></label>"
            f"<label>📜 Script <select id=f-script>{script}</select></label>"
            f"<label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
            f"<p class=meta id=bi-info></p><div class=pager id=pg-top></div><div id=bi-list>{cards}</div><div class=pager id=pg-bot></div>")
    (R.OUT / "browse.html").write_text(R.page("날짜·주제별 보기", CSS + opinions.OP_CSS + body + opinions.OP_JS + JS, "🗂️"), encoding="utf-8")


if __name__ == "__main__":
    build(); print("reports/browse.html 생성")
