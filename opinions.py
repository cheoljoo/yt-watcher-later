"""나의 의견 + AI 의견: DB 함수, 영상 카드용 입력 칸(HTML/JS), '나와 AI 의견' 페이지(reports/opinions.html).
- 나의 의견은 리포트의 저장 버튼 -> opinion_server.py -> opinions 표.   AI 의견은 cron(work.py 'opinion' 단계)이 채운다.
- AI 의견이 달린 항목은 더 이상 편집하지 않는다."""
import json
from html import escape as e
import db as D

MAX_LEN = 5000

def get(con, vid):
    return con.execute("SELECT * FROM opinions WHERE video_id=?", (vid,)).fetchone()

def save_mine(con, vid, text):
    """저장 버튼. 반환 (ok, 메시지). AI 의견이 이미 있으면 거부, 빈 글이면 삭제(AI 의견 없을 때만)."""
    text = (text or "").strip()
    if len(text) > MAX_LEN: return False, f"{MAX_LEN}자까지 저장할 수 있습니다"
    if not con.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone(): return False, "알 수 없는 영상입니다"
    cur = get(con, vid)
    if cur and cur["ai_reply"]: return False, "AI 의견이 이미 달려 더 이상 수정할 수 없습니다"
    if not text:
        con.execute("DELETE FROM opinions WHERE video_id=?", (vid,)); con.commit(); return True, "삭제했습니다"
    con.execute("INSERT INTO opinions(video_id,my_opinion,my_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET my_opinion=excluded.my_opinion, my_at=excluded.my_at",
                (vid, text, D.now()))
    con.commit()
    return True, "저장했습니다. AI 의견은 다음 새벽 실행에서 달립니다"

def pending(con):
    """내 의견은 있고 AI 의견이 없는 영상."""
    return con.execute("""SELECT o.video_id, o.my_opinion, v.title, v.one_liner, v.summary, v.lessons, v.channel FROM opinions o JOIN videos v ON v.id=o.video_id
                          WHERE o.my_opinion IS NOT NULL AND o.my_opinion<>'' AND (o.ai_reply IS NULL OR o.ai_reply='') ORDER BY o.my_at""").fetchall()

def apply_ai(con, items):
    n = 0
    for it in items:
        cur = con.execute("UPDATE opinions SET ai_reply=?, ai_llm=?, ai_at=? WHERE video_id=? AND (ai_reply IS NULL OR ai_reply='')", (it["reply"], D.llm_tag(), D.now(), it["id"]))
        n += cur.rowcount
    con.commit()
    return n

def all_json(con):
    return {r["video_id"]: {"my": r["my_opinion"] or "", "ai": r["ai_reply"] or "", "llm": r["ai_llm"] or ""} for r in con.execute("SELECT * FROM opinions")}

def task_line(r):
    pts = ""
    try: pts = " / ".join(json.loads(r["summary"] or "[]"))[:900]
    except Exception: pass
    return f"id={r['video_id']} | 영상: {r['title']} ({r['channel'] or ''}) | 한줄: {r['one_liner'] or ''} | 요약: {pts} | 나의 의견: {r['my_opinion']}"

PROMPT = ("각 항목은 시청자가 영상을 보고 남긴 '나의 의견'입니다. 영상 요약을 참고해 그 의견에 답하세요. "
          "동의할 부분과 보완·반박할 부분을 구분하고, 놓친 관점이나 확인해볼 점을 한두 가지 덧붙이세요. 4~8문장, 한국어. "
          "영상 요약에 없는 사실은 지어내지 말고, 확실하지 않으면 그렇다고 밝히세요. id는 입력 그대로.")
SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "reply"], "properties": {"id": {"type": "string"}, "reply": {"type": "string"}}}}}}

# ── 영상 카드용 칸 ────────────────────────────────────────────────
OP_JS = """<script>(function(){
var API='api/',TK='ytwl_token';
function tok(){try{return localStorage.getItem(TK)||''}catch(x){return ''}}
function lock(box,d){box.innerHTML='';var a=document.createElement('div');a.className='op-my';a.textContent=d.my;box.appendChild(a);
 if(d.ai){var b=document.createElement('div');b.className='op-ai';var s=document.createElement('b');s.textContent='🤖 AI 의견 ';var m=document.createElement('span');m.className='meta';m.textContent='('+(d.llm||'-')+')';
  var t=document.createElement('div');t.style.whiteSpace='pre-wrap';t.textContent=d.ai;b.appendChild(s);b.appendChild(m);b.appendChild(t);box.appendChild(b);}}
document.querySelectorAll('.op').forEach(function(box){
 var vid=box.getAttribute('data-vid'),ta=box.querySelector('textarea'),btn=box.querySelector('.op-save'),msg=box.querySelector('.op-msg');
 if(!btn)return;
 btn.addEventListener('click',function(){var t=tok();if(!t){t=prompt('저장용 비밀 토큰을 입력하세요 (한 번만 입력하면 이 브라우저에 기억됩니다)')||'';if(!t)return;try{localStorage.setItem(TK,t)}catch(x){}}
  msg.textContent='저장 중…';
  fetch(API+'save',{method:'POST',headers:{'Content-Type':'application/json','X-Token':t},body:JSON.stringify({id:vid,text:ta.value})})
   .then(function(r){return r.json().then(function(j){return[r.status,j]})}).then(function(p){
    if(p[0]==401){try{localStorage.removeItem(TK)}catch(x){}msg.textContent='❌ 토큰이 맞지 않습니다. 다시 눌러 입력하세요';return}
    msg.textContent=(p[1].ok?'✅ ':'❌ ')+p[1].message}).catch(function(){msg.textContent='❌ 저장 서버에 연결하지 못했습니다'});});
});
fetch(API+'opinions').then(function(r){return r.json()}).then(function(all){   // 저장 후 새로 고쳐도 최신 내용이 보이게
 document.querySelectorAll('.op').forEach(function(box){var d=all[box.getAttribute('data-vid')];if(!d)return;
  if(d.ai){lock(box,d)}else{var ta=box.querySelector('textarea');if(ta&&document.activeElement!==ta&&!ta.dataset.dirty)ta.value=d.my}});}).catch(function(){});
document.querySelectorAll('.op textarea').forEach(function(t){t.addEventListener('input',function(){t.dataset.dirty=1})});
})();</script>"""

OP_CSS = "<style>.op{margin-top:14px;padding-top:10px;border-top:1px dashed var(--bd)}.op textarea{width:100%;min-height:70px;box-sizing:border-box;font:inherit;padding:8px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:inherit}.op button{margin-top:6px;padding:6px 14px;border-radius:8px;border:1px solid var(--ac);background:var(--ac);color:#fff;cursor:pointer}.op-my{white-space:pre-wrap;background:var(--chip);border-radius:8px;padding:8px 10px}.op-ai{margin-top:8px;border-left:4px solid var(--ac);padding:6px 10px}</style>"

def box(con, vid):
    """영상 카드 맨 아래: 나의 의견(AI 의견 전까지는 항상 편집 가능) + 있으면 AI 의견."""
    o = get(con, vid)
    my = (o["my_opinion"] if o else "") or ""
    h = f"<div class=op data-vid='{e(vid)}'><b>💬 나의 의견</b>"
    if o and o["ai_reply"]:
        h += f"<div class=op-my>{e(my)}</div><div class=op-ai><b>🤖 AI 의견</b> <span class=meta>({e(o['ai_llm'] or '-')} · {e((o['ai_at'] or '')[:10])})</span><div style='white-space:pre-wrap'>{e(o['ai_reply'])}</div></div>"
    else:
        h += f"<textarea placeholder='이 영상에 대한 내 생각을 적고 저장을 누르세요 (AI 의견은 다음 새벽에 달립니다)'>{e(my)}</textarea><button type=button class=op-save>저장</button> <span class='op-msg meta'></span>"
        if my: h += "<div class=meta>AI 의견 대기 중 — 다음 새벽 실행에서 달립니다. 그 전까지는 수정할 수 있습니다.</div>"
    return h + "</div>"

LIST_CSS = """<style>
.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--bd);padding:10px 0;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
.bar label{font-size:13px;color:var(--mu)}.bar select{font:inherit;margin-left:4px;padding:4px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
.pager{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}.pager button{font:inherit;padding:3px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button.on{background:var(--ac);color:#fff;border-color:var(--ac)}.pager button:disabled{opacity:.4;cursor:default}
details.oi{border:1px solid var(--bd);border-radius:12px;padding:8px 12px;margin:10px 0;background:var(--card)}
details.oi>summary{cursor:pointer;list-style:none}details.oi>summary::-webkit-details-marker{display:none}
details.oi>summary b.t{font-size:15px}.cl{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-wrap;font-size:13.5px;margin-top:3px}
.cl.ai{color:var(--mu)}details.oi[open]>summary .cl{display:none}
.bd{display:inline-block;font-size:12px;border-radius:99px;padding:0 9px;margin-left:6px;background:var(--chip)}.bd.ok{background:var(--ac);color:#fff}
</style>"""

LIST_JS = """<script>(function(){
var items=[].slice.call(document.querySelectorAll('.oi')),box=document.getElementById('oi-list'),
 fA=document.getElementById('f-ai'),fT=document.getElementById('f-topic'),fR=document.getElementById('f-recent'),fP=document.getElementById('f-per'),
 info=document.getElementById('oi-info'),pg=[document.getElementById('pg-top'),document.getElementById('pg-bot')],page=1,view=[];
function cutoff(days){var d=new Date();d.setDate(d.getDate()-days);return d.toISOString().slice(0,10)}
function apply(){var a=fA.value,t=fT.value,r=fR.value,co=r==='all'?'':cutoff(+r);
 view=items.filter(function(x){if(a==='yes'&&x.dataset.ai!=='1')return false;if(a==='no'&&x.dataset.ai==='1')return false;
  if(t!=='all'){var k=t.slice(0,2),v=t.slice(2);if(k==='c:'&&x.dataset.c!==v)return false;if(k==='s:'&&x.dataset.s!==v)return false}
  return !co||x.dataset.d>=co});render()}
function render(){var per=+fP.value,n=view.length,pages=Math.max(1,Math.ceil(n/per));if(page>pages)page=pages;
 var a=(page-1)*per,b=Math.min(n,a+per),show=new Set(view.slice(a,b));
 items.forEach(function(x){x.hidden=!show.has(x)});
 view.slice(a,b).forEach(function(x,i){x.querySelector('.no').textContent='#'+(a+i+1)+' ';box.appendChild(x)});
 info.textContent=n?('조건에 맞는 의견 '+n+'개 중 '+(a+1)+'–'+b+'번째 · '+page+'/'+pages+' 쪽'):'조건에 맞는 의견이 없습니다';
 pg.forEach(function(p){p.innerHTML='';function btn(l,pn,dis,on){var q=document.createElement('button');q.textContent=l;q.disabled=dis;if(on)q.className='on';q.onclick=function(){page=pn;render();window.scrollTo(0,0)};p.appendChild(q)}
  btn('‹ 이전',page-1,page<=1);var lo=Math.max(1,page-3),hi=Math.min(pages,page+3);if(lo>1)btn('1',1,false,page===1);if(lo>2)p.appendChild(document.createTextNode('…'));
  for(var i=lo;i<=hi;i++)btn(String(i),i,false,i===page);if(hi<pages-1)p.appendChild(document.createTextNode('…'));if(hi<pages)btn(String(pages),pages,false,page===pages);btn('다음 ›',page+1,page>=pages)})}
[fA,fT,fR].forEach(function(s){s.onchange=function(){page=1;apply()}});fP.onchange=function(){page=1;render()};apply()})();
</script>"""

def _head(text, n=110):
    """summary 용: 처음 부분(공백 정리 후 n자)."""
    t = " ".join((text or "").split())
    return t[:n] + ("…" if len(t) > n else "")

def build(con):
    """'나와 AI 의견' 페이지. 날짜·주제별 보기와 같은 선택(주제·기간·한 페이지 수) + AI 의견 있음/없음. 항목은 접힌 상태(summary=처음 부분)."""
    import report as R
    rows = con.execute("""SELECT o.*, v.title, v.channel, v.category, v.subtag, COALESCE(v.run_id, v.processed_date) AS page FROM opinions o JOIN videos v ON v.id=o.video_id
                          WHERE o.my_opinion IS NOT NULL AND o.my_opinion<>'' ORDER BY o.my_at DESC""").fetchall()
    n_ai = sum(1 for r in rows if r["ai_reply"])
    cats, subs = {}, {}
    for r in rows:
        c, s = r["category"] or "기타", r["subtag"] or "기타"
        cats[c] = cats.get(c, 0) + 1; subs.setdefault(c, {})[s] = subs.setdefault(c, {}).get(s, 0) + 1
    order = sorted(cats, key=lambda c: R.CAT_ORDER.index(c) if c in R.CAT_ORDER else len(R.CAT_ORDER))
    topic = "<option value=all>모두</option>"
    for c in order:
        topic += f"<option value='c:{e(c)}'>{R.CAT_ICON.get(c, '📌')} {e(c)} ({cats[c]})</option>"
        for s, n in sorted(subs[c].items(), key=lambda kv: (-kv[1], kv[0])): topic += f"<option value='s:{e(c)}/{e(s)}'>&nbsp;&nbsp;└ {e(s)} ({n})</option>"
    recent = "<option value=all>모두</option>" + "".join(f"<option value={d}>{t}</option>" for d, t in ((7, "최근 1주일"), (30, "최근 1개월"), (90, "최근 3개월"), (180, "최근 6개월"), (365, "최근 1년"), (730, "최근 2년")))
    per = "".join(f"<option value={n}>{n}개</option>" for n in (20, 50, 100))
    ai = f"<option value=all>모두 ({len(rows)})</option><option value=yes>AI 의견 있는 것 ({n_ai})</option><option value=no>AI 의견 없는 것 ({len(rows) - n_ai})</option>"
    items = ""
    for r in rows:
        has = bool(r["ai_reply"])
        items += (f"<details class=oi hidden data-ai={1 if has else 0} data-d='{e((r['my_at'] or '0000')[:10])}' data-c='{e(r['category'] or '기타')}' data-s='{e((r['category'] or '기타') + '/' + (r['subtag'] or '기타'))}'>"
                  f"<summary><b class=t><span class=no></span>{e(r['title'])}</b><span class='bd{' ok' if has else ''}'>{'🤖 AI 의견 있음' if has else '⏳ AI 의견 대기'}</span> <span class=meta>{e((r['my_at'] or '')[:10])}</span>"
                  f"<div class=cl>💬 {e(_head(r['my_opinion']))}</div>" + (f"<div class='cl ai'>🤖 {e(_head(r['ai_reply']))}</div>" if has else "") + "</summary>"
                  f"<div class=meta style='margin-top:8px'>📺 {e(r['channel'] or '')} · {e(r['category'] or '')}/{e(r['subtag'] or '')} · 내 의견 {e((r['my_at'] or '').replace('T', ' '))} · <a href='{e(r['page'])}.html#v-{e(r['video_id'])}'>영상 카드로 가기 ›</a></div>"
                  f"<p><b>💬 나의 의견</b></p><div class=op-my style='white-space:pre-wrap'>{e(r['my_opinion'])}</div>"
                  + (f"<p><b>🤖 AI 의견</b> <span class=meta>({e(r['ai_llm'] or '-')} · {e((r['ai_at'] or '')[:10])})</span></p><div class=op-ai style='white-space:pre-wrap'>{e(r['ai_reply'])}</div>"
                     if has else "<p class=meta>🤖 AI 의견은 다음 새벽 실행에서 달립니다.</p>") + "</details>")
    body = (f"<h1>💬 나와 AI 의견</h1><p class=meta>내가 남긴 의견 {len(rows)}개 · AI 의견 달림 {n_ai}개 · 대기 {len(rows) - n_ai}개 · 내가 저장한 날짜 최신순 · 항목을 누르면 펼쳐집니다 · <a href='index.html'>🏠 홈</a> · 의견은 각 날짜 리포트나 <a href='browse.html'>🗂️ 날짜·주제별 보기</a>의 영상 카드 맨 아래에서 씁니다</p>")
    if not rows: body += "<p class=meta>아직 남긴 의견이 없습니다. 영상 카드 맨 아래 칸에 의견을 적고 저장하면 여기에 나타납니다.</p>"
    body += (f"<div class=bar><label>🤖 AI 의견 <select id=f-ai>{ai}</select></label><label>🏷️ 주제 <select id=f-topic>{topic}</select></label>"
             f"<label>📅 기간 <select id=f-recent>{recent}</select></label><label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
             f"<p class=meta id=oi-info></p><div class=pager id=pg-top></div><div id=oi-list>{items}</div><div class=pager id=pg-bot></div>")
    (R.OUT / "opinions.html").write_text(R.page("나와 AI 의견", OP_CSS + LIST_CSS + body + LIST_JS, "💬"), encoding="utf-8")
