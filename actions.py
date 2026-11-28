"""액션 페이지 (reports/actions.html): 해봐야 할 것을 모아 보고, 해본 메모를 적고, 'Action Done'(처리완료)을 표시한다.
액션은 두 종류 — 🎬 동영상('🎯 직접 해보기', 표 actions) / 💬 나의 의견('의견 action', 표 opinion_actions). 주제·종류·처리 여부·페이지당 개수를 골라 본다.
저장은 opinion_server.py -> 각 표 (경로: 동영상 /action*, 의견 /opinion_action*)."""
from html import escape as e
import db as D
import opinions as O

CSS = """<style>
.ac{border:1px solid var(--bd);border-left:4px solid #e8590c;border-radius:12px;padding:10px 14px;margin:12px 0;background:var(--card)}
.ac.k-opinion{border-left-color:#7048e8}.ac.done{opacity:.7}
.ty{display:inline-block;font-size:12px;border-radius:99px;padding:0 9px;margin-right:6px;color:#fff;background:#e8590c}.k-opinion .ty{background:#7048e8}
.ac textarea{width:100%;min-height:90px;box-sizing:border-box;font:inherit;padding:8px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:inherit}
.ac button{font:inherit;margin:6px 6px 0 0;padding:6px 14px;border-radius:8px;border:1px solid var(--bd);background:transparent;color:inherit;cursor:pointer}
.ac button.ac-save{background:var(--ac);border-color:var(--ac);color:#fff}
.ac button.ac-mark.on{background:#e8590c;border-color:#e8590c;color:#fff}.k-opinion button.ac-mark.on{background:#7048e8;border-color:#7048e8}
.ac button.ac-done.on{background:#1a8a4a;border-color:#1a8a4a;color:#fff;font-weight:600}
.ac .op-my{white-space:pre-wrap;background:var(--chip);border-radius:8px;padding:8px 10px;margin:6px 0}.ac .op-ai{white-space:pre-wrap;border-left:4px solid var(--ac);padding:6px 10px;margin:6px 0}
</style>"""

JS = """<script>(function(){
var API='api/',TK='ytwl_token';
function tok(){try{return localStorage.getItem(TK)||''}catch(x){return ''}}
function post(path,body,msg,cb){var t=tok();if(!t){t=prompt('저장용 비밀 토큰을 입력하세요 (한 번만 입력하면 이 브라우저에 기억됩니다)')||'';if(!t)return;try{localStorage.setItem(TK,t)}catch(x){}}
 msg.textContent='저장 중…';
 fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-Token':t},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(j){return[r.status,j]})}).then(function(p){
  if(p[0]==401){try{localStorage.removeItem(TK)}catch(x){}msg.textContent='❌ 토큰이 맞지 않습니다. 다시 눌러 입력하세요';return}
  msg.textContent=(p[1].ok?'✅ ':'❌ ')+p[1].message;if(p[1].ok&&cb)cb()}).catch(function(){msg.textContent='❌ 저장 서버에 연결하지 못했습니다'})}
var items=[].slice.call(document.querySelectorAll('.ac')),
 fT=document.getElementById('f-topic'),fK=document.getElementById('f-type'),fD=document.getElementById('f-done'),fP=document.getElementById('f-per'),
 info=document.getElementById('ac-info'),pg=[document.getElementById('pg-top'),document.getElementById('pg-bot')],page=1,view=[];
function apply(){var t=fT.value,k=fK.value,d=fD.value;
 view=items.filter(function(x){if(k!=='all'&&x.dataset.k!==k)return false;if(d!=='all'&&x.dataset.done!==d)return false;
  if(t!=='all'){var a=t.slice(0,2),v=t.slice(2);if(a==='c:'&&x.dataset.c!==v)return false;if(a==='s:'&&x.dataset.s!==v)return false}return true});render()}
function render(){var per=+fP.value,n=view.length,pages=Math.max(1,Math.ceil(n/per));if(page>pages)page=pages;
 var a=(page-1)*per,b=Math.min(n,a+per),show=new Set(view.slice(a,b));
 items.forEach(function(x){x.hidden=!show.has(x)});
 view.slice(a,b).forEach(function(x,i){x.querySelector('.no').textContent='#'+(a+i+1)+' '});
 info.textContent=n?('조건에 맞는 액션 '+n+'개 중 '+(a+1)+'–'+b+'번째 · '+page+'/'+pages+' 쪽'):'조건에 맞는 액션이 없습니다';
 pg.forEach(function(p){p.innerHTML='';if(pages<2)return;function btn(l,pn,dis,on){var q=document.createElement('button');q.textContent=l;q.disabled=dis;if(on)q.className='on';q.onclick=function(){page=pn;render();window.scrollTo(0,0)};p.appendChild(q)}
  btn('‹ 이전',page-1,page<=1);var lo=Math.max(1,page-3),hi=Math.min(pages,page+3);if(lo>1)btn('1',1,false,page===1);if(lo>2)p.appendChild(document.createTextNode('…'));
  for(var i=lo;i<=hi;i++)btn(String(i),i,false,i===page);if(hi<pages-1)p.appendChild(document.createTextNode('…'));if(hi<pages)btn(String(pages),pages,false,page===pages);btn('다음 ›',page+1,page>=pages)})}
function paintMark(x,on){var b=x.querySelector('.ac-mark'),o=x.dataset.k==='opinion';b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false');
 b.textContent=(o?'💬 의견 action':'🎯 직접 해볼 것')+(on?' (표시됨)':' (해제됨)');x.style.opacity=on?'':'.4'}
function paintDone(x,done){var b=x.querySelector('.ac-done');b.classList.toggle('on',done);b.setAttribute('aria-pressed',done?'true':'false');b.textContent=done?'✅ Action Done (처리완료)':'Action Done';
 x.classList.toggle('done',done);x.dataset.done=done?'yes':'no'}
items.forEach(function(x){var vid=x.getAttribute('data-vid'),pre=x.dataset.k==='opinion'?'opinion_':'',ta=x.querySelector('textarea'),m=x.querySelector('.ac-msg');
 x.querySelector('.ac-save').onclick=function(){post(pre+'action_comment',{id:vid,text:ta.value},m)};
 x.querySelector('.ac-mark').onclick=function(){var on=!this.classList.contains('on');if(!on&&!confirm('액션 표시를 해제할까요? (메모는 보관됩니다)'))return;post(pre+'action',{id:vid,on:on},m,function(){paintMark(x,on)})};
 x.querySelector('.ac-done').onclick=function(){var d=!this.classList.contains('on');post(pre+'action_done',{id:vid,on:d},m,function(){paintDone(x,d)})};
 ta.addEventListener('input',function(){ta.dataset.dirty=1})});
[fT,fK,fD].forEach(function(s){s.onchange=function(){page=1;apply()}});fP.onchange=function(){page=1;render()};apply();
// 페이지가 낡았을 수 있으니 서버의 최신 상태를 받아 맞춘다
['video','opinion'].forEach(function(k){fetch(API+(k==='opinion'?'opinion_actions':'actions')).then(function(r){return r.ok?r.json():null}).then(function(all){if(!all)return;
 items.forEach(function(x){var d=x.dataset.k===k&&all[x.getAttribute('data-vid')];if(!d)return;paintMark(x,d.on);paintDone(x,d.done);var ta=x.querySelector('textarea');if(!ta.dataset.dirty)ta.value=d.comment});apply()}).catch(function(){})});
})();</script>"""

def rows(con):
    """표시가 켜진 액션 전부(두 종류), 표시한 최신순. 의견 액션은 의견이 남아 있는 것만."""
    out = [dict(r, kind="video") for r in con.execute("""SELECT a.*, v.title, v.channel, v.category, v.subtag, v.one_liner, COALESCE(v.run_id, v.processed_date) AS page
              FROM actions a JOIN videos v ON v.id=a.video_id WHERE a.on_flag=1""")]
    ops = {r["video_id"]: r for r in con.execute(O.OP_ROWS + "WHERE my_opinion IS NOT NULL AND my_opinion<>''")}
    for a in con.execute("SELECT * FROM opinion_actions WHERE on_flag=1"):
        o = ops.get(a["video_id"])
        if o: out.append(dict(a, kind="opinion", title=o["title"], channel=o["channel"], category=o["category"], subtag=o["subtag"], page=o["page"],
                              my_opinion=o["my_opinion"], ai_reply=o["ai_reply"], ai_llm=o["ai_llm"]))
    return sorted(out, key=lambda r: r["on_at"] or "", reverse=True)

def _item(r):
    vid, op, done = r["video_id"], r["kind"] == "opinion", bool(r["done"])
    cat, sub = r["category"] or "기타", r["subtag"] or "기타"
    if vid.startswith("rich:"): link = f"<a href='rich.html#r-{e(vid[5:])}'>부자들 항목으로 가기 ›</a>"
    else: link = f"<a href='{e(r['page'])}.html#v-{e(vid)}'>영상 카드로 가기 ›</a>"
    if op:
        content = (f"<div class=op-my><b>💬 나의 의견</b><br>{e(r['my_opinion'])}</div>"
                   + (f"<div class=op-ai><b>🤖 AI 의견</b> <span class=meta>({e(r['ai_llm'] or '-')})</span><br>{e(r['ai_reply'])}</div>" if r["ai_reply"]
                      else "<div class=meta>🤖 AI 의견은 다음 새벽 실행에서 달립니다.</div>"))
    else: content = f"<div style='margin:6px 0'>{e(r['one_liner'] or '')}</div>"
    return (f"<div class='ac k-{r['kind']}{' done' if done else ''}' hidden data-vid='{e(vid)}' data-k={r['kind']} data-done={'yes' if done else 'no'} data-c='{e(cat)}' data-s='{e(cat + '/' + sub)}'>"
            f"<span class=ty>{'💬 나의 의견' if op else '🎬 동영상'}</span><b><span class=no></span>{e(r['title'])}</b>"
            f"<div class=meta>📺 {e(r['channel'] or '')} · {e(cat)}/{e(sub)} · 표시 {e((r['on_at'] or '').replace('T', ' '))}"
            + (f" · 처리완료 {e((r['done_at'] or '')[:10])}" if done else "") + f" · {link}</div>{content}"
            f"<textarea placeholder='직접 해보고 느낀 점·결과를 적고 저장을 누르세요'>{e(r['comment'] or '')}</textarea>"
            f"<button type=button class=ac-save>저장</button>"
            f"<button type=button class='ac-mark on' aria-pressed=true>{'💬 의견 action' if op else '🎯 직접 해볼 것'} (표시됨)</button>"
            f"<button type=button class='ac-done{' on' if done else ''}' aria-pressed={'true' if done else 'false'}>{'✅ Action Done (처리완료)' if done else 'Action Done'}</button>"
            f" <span class='ac-msg meta'></span></div>")

def _options(con, items):
    import report as R
    cats, subs = {}, {}
    for r in items:
        c, s = r["category"] or "기타", r["subtag"] or "기타"
        cats[c] = cats.get(c, 0) + 1
        subs.setdefault(c, {})[s] = subs.setdefault(c, {}).get(s, 0) + 1
    topic = "<option value=all>모두</option>"
    for c in sorted(cats, key=lambda c: R.CAT_ORDER.index(c) if c in R.CAT_ORDER else len(R.CAT_ORDER)):
        topic += f"<option value='c:{e(c)}'>{R.CAT_ICON.get(c, '📌')} {e(c)} ({cats[c]})</option>"
        for s, n in sorted(subs[c].items(), key=lambda kv: (-kv[1], kv[0])):
            topic += f"<option value='s:{e(c)}/{e(s)}'>&nbsp;&nbsp;└ {e(s)} ({n})</option>"
    return topic

def build(con):
    import report as R
    R.OUT.mkdir(exist_ok=True)
    items = rows(con)
    nv = sum(1 for r in items if r["kind"] == "video"); nd = sum(1 for r in items if r["done"])
    per = "".join(f"<option value={n}{' selected' if n == 20 else ''}>{n}개</option>" for n in (10, 20, 50, 100))
    body = (f"<h1>🎯 액션 — 직접 해봐야 할 것</h1><p class=meta>액션 {len(items)}개 (동영상 {nv} · 나의 의견 {len(items) - nv}) · 처리완료 {nd}개 · 표시한 최신순 · <a href='index.html'>🏠 홈</a> · "
            "동영상 액션은 영상 카드의 🎯 직접 해보기, 의견 액션은 '나의 의견' 아래 💬 의견 action 버튼으로 표시합니다</p>")
    if items:
        body += (f"<div class=bar><label>🏷️ 주제 <select id=f-topic>{_options(con, items)}</select></label>"
                 f"<label>🧩 Action Type <select id=f-type><option value=all>모두 ({len(items)})</option><option value=video>🎬 동영상 ({nv})</option><option value=opinion>💬 나의 의견 ({len(items) - nv})</option></select></label>"
                 f"<label>✅ Action Done <select id=f-done><option value=all>모두 ({len(items)})</option><option value=yes>처리완료 ({nd})</option><option value=no>처리 전 ({len(items) - nd})</option></select></label>"
                 f"<label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
                 "<p class=meta id=ac-info></p><div class=pager id=pg-top></div>" + "".join(_item(r) for r in items) + "<div class=pager id=pg-bot></div>" + JS)
    else: body += "<p class=meta>아직 표시한 액션이 없습니다. 영상 카드 맨 아래 '🎯 직접 해보기' 또는 '💬 의견 action' 버튼을 누르세요.</p>"
    (R.OUT / "actions.html").write_text(R.page("액션", O.LIST_CSS + CSS + body, "🎯"), encoding="utf-8")

if __name__ == "__main__":
    build(D.connect()); print("reports/actions.html 생성")
