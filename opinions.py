"""나의 의견 + AI 의견: DB 함수, 영상 카드용 입력 칸(HTML/JS), '나와 AI 의견' 페이지(reports/opinions.html).
- 나의 의견은 리포트의 저장 버튼 -> opinion_server.py -> opinions 표.   AI 의견은 cron(work.py 'opinion' 단계)이 채운다.
- AI 의견이 달린 항목은 더 이상 편집하지 않는다."""
import json
from html import escape as e
import db as D

MAX_LEN = 5000

def get(con, vid):
    return con.execute("SELECT * FROM opinions WHERE video_id=?", (vid,)).fetchone()

def exists(con, vid):
    """의견을 달 수 있는 대상: 영상 id, 또는 부자들 항목('rich:번호')."""
    if vid.startswith("rich:"): return bool(vid[5:].isdigit() and con.execute("SELECT 1 FROM rich_ideas WHERE id=?", (int(vid[5:]),)).fetchone())
    return bool(con.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone())

def save_mine(con, vid, text):
    """저장 버튼. 반환 (ok, 메시지). AI 의견이 이미 있으면 거부, 빈 글이면 삭제(AI 의견 없을 때만)."""
    text = (text or "").strip()
    if len(text) > MAX_LEN: return False, f"{MAX_LEN}자까지 저장할 수 있습니다"
    if not exists(con, vid): return False, "알 수 없는 항목입니다"
    cur = get(con, vid)
    if cur and cur["ai_reply"]: return False, "AI 의견이 이미 달려 더 이상 수정할 수 없습니다"
    if not text:
        con.execute("DELETE FROM opinions WHERE video_id=?", (vid,)); con.commit(); return True, "삭제했습니다"
    con.execute("INSERT INTO opinions(video_id,my_opinion,my_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET my_opinion=excluded.my_opinion, my_at=excluded.my_at",
                (vid, text, D.now()))
    con.commit()
    return True, "저장했습니다. AI 의견은 다음 새벽 실행에서 달립니다"

# ── 액션(직접 해볼 것) ────────────────────────────────────────────
# 두 종류: 동영상 액션(표 actions) / 의견 액션(표 opinion_actions — 나의 의견·AI 답변에 대해 해볼 것). 두 표는 모양이 같다.
TABLES = {"video": "actions", "opinion": "opinion_actions"}

def _flag(con, table, vid, on):
    con.execute(f"INSERT INTO {table}(video_id,on_flag,on_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET on_flag=excluded.on_flag, on_at=excluded.on_at",
                (vid, 1 if on else 0, D.now()))
    con.commit()
    return True, "직접 해볼 것으로 표시했습니다" if on else "표시를 해제했습니다 (남긴 메모는 그대로 보관됩니다)"

def set_action(con, vid, on):
    if not con.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone(): return False, "알 수 없는 영상입니다"
    return _flag(con, "actions", vid, on)

def set_opinion_action(con, vid, on):
    cur = get(con, vid)
    if on and not (cur and cur["my_opinion"]): return False, "먼저 나의 의견을 저장하세요"
    return _flag(con, "opinion_actions", vid, on)

def _marked(con, table, vid):
    return con.execute(f"SELECT 1 FROM {table} WHERE video_id=? AND on_flag=1", (vid,)).fetchone()

def save_action_comment(con, vid, text, kind="video"):
    text = (text or "").strip()
    if len(text) > MAX_LEN: return False, f"{MAX_LEN}자까지 저장할 수 있습니다"
    table = TABLES[kind]
    if not _marked(con, table, vid): return False, "액션으로 표시된 항목이 아닙니다"
    con.execute(f"UPDATE {table} SET comment=?, comment_at=? WHERE video_id=?", (text, D.now(), vid))
    con.commit()
    return True, "저장했습니다"

def set_done(con, vid, done, kind="video"):
    """'Action Done': 액션을 실제로 했다는 표시(다시 누르면 해제)."""
    table = TABLES[kind]
    if not _marked(con, table, vid): return False, "액션으로 표시된 항목이 아닙니다"
    con.execute(f"UPDATE {table} SET done=?, done_at=? WHERE video_id=?", (1 if done else 0, D.now() if done else None, vid))
    con.commit()
    return True, "처리완료로 표시했습니다" if done else "처리완료 표시를 해제했습니다"

def _actions_json(con, table):
    return {r["video_id"]: {"on": bool(r["on_flag"]), "comment": r["comment"] or "", "done": bool(r["done"])} for r in con.execute(f"SELECT * FROM {table}")}

def actions_json(con):
    return _actions_json(con, "actions")

def opinion_actions_json(con):
    return _actions_json(con, "opinion_actions")

# ── 별표(인상 깊은 영상) ──────────────────────────────────────────
def set_star(con, vid, on):
    if not (con.execute("SELECT 1 FROM videos WHERE id=?", (vid,)).fetchone() or con.execute("SELECT 1 FROM highlights WHERE video_id=?", (vid,)).fetchone()):
        return False, "알 수 없는 영상입니다"
    con.execute("INSERT INTO stars(video_id,on_flag,on_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET on_flag=excluded.on_flag, on_at=excluded.on_at",
                (vid, 1 if on else 0, D.now()))
    con.commit()
    return True, "별표를 달았습니다 — 인상 깊은 영상 페이지에 나옵니다" if on else "별표를 뗐습니다 (상세 분석이 있었다면 DB에 그대로 보관됩니다)"

def stars_json(con):
    return {r["video_id"]: bool(r["on_flag"]) for r in con.execute("SELECT * FROM stars")}

def pending(con):
    """내 의견은 있고 AI 의견이 없는 영상과 부자들 항목."""
    rows = [dict(r) for r in con.execute("""SELECT o.video_id, o.my_opinion, v.title, v.one_liner, v.summary, v.lessons, v.channel FROM opinions o JOIN videos v ON v.id=o.video_id
                          WHERE o.my_opinion IS NOT NULL AND o.my_opinion<>'' AND (o.ai_reply IS NULL OR o.ai_reply='') ORDER BY o.my_at""")]
    for r in con.execute("""SELECT o.video_id, o.my_opinion, r.title, r.topic, r.summary, r.source, r.who FROM opinions o JOIN rich_ideas r ON 'rich:'||r.id=o.video_id
                          WHERE o.my_opinion IS NOT NULL AND o.my_opinion<>'' AND (o.ai_reply IS NULL OR o.ai_reply='') ORDER BY o.my_at"""):
        rows.append({"video_id": r["video_id"], "my_opinion": r["my_opinion"], "title": r["title"], "one_liner": f"부자들 투자 방법({r['topic']}, {r['who'] or ''})",
                     "summary": json.dumps([r["summary"]], ensure_ascii=False), "lessons": None, "channel": r["source"]})
    return rows

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

PROMPT = ("각 항목은 시청자가 영상(또는 '부자들 투자 방법' 글 요약)을 보고 남긴 '나의 의견'입니다. 요약을 참고해 그 의견에 답하세요. "
          "동의할 부분과 보완·반박할 부분을 구분하고, 놓친 관점이나 확인해볼 점을 한두 가지 덧붙이세요. 4~8문장, 한국어. "
          "영상 요약에 없는 사실은 지어내지 말고, 확실하지 않으면 그렇다고 밝히세요. id는 입력 그대로.")
SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "reply"], "properties": {"id": {"type": "string"}, "reply": {"type": "string"}}}}}}

# ── 영상 카드용 칸 ────────────────────────────────────────────────
OP_JS = """<script>(function(){
var API='api/',TK='ytwl_token';
function tok(){try{return localStorage.getItem(TK)||''}catch(x){return ''}}
function lock(card,d){var box=card.querySelector('.op-body');box.innerHTML='';var a=document.createElement('div');a.className='op-my';a.textContent=d.my;box.appendChild(a);
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

function post(path,body,cb){var t=tok();if(!t){t=prompt('저장용 비밀 토큰을 입력하세요 (한 번만 입력하면 이 브라우저에 기억됩니다)')||'';if(!t)return;try{localStorage.setItem(TK,t)}catch(x){}}
 fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-Token':t},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(j){return[r.status,j]})}).then(function(p){
  if(p[0]==401){try{localStorage.removeItem(TK)}catch(x){}cb(false,'토큰이 맞지 않습니다. 다시 눌러 입력하세요');return}cb(p[1].ok,p[1].message,p[1])}).catch(function(){cb(false,'저장 서버에 연결하지 못했습니다')})}
function paint(b,on){b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false');b.textContent=on?'🎯 직접 해볼 것 (표시됨)':'🎯 직접 해보기'}
document.querySelectorAll('.act-btn').forEach(function(b){b.addEventListener('click',function(){var on=!b.classList.contains('on'),m=b.parentNode.querySelector('.act-msg');m.textContent='저장 중…';
 post('action',{id:b.getAttribute('data-vid'),on:on},function(ok,msg){if(ok)paint(b,on);m.textContent=(ok?'✅ ':'❌ ')+msg})})});
function paintO(b,on){b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false');b.textContent=on?'💬 의견 action (표시됨)':'💬 의견 action'}
document.querySelectorAll('.oa-btn').forEach(function(b){b.addEventListener('click',function(){var on=!b.classList.contains('on'),m=b.parentNode.querySelector('.oa-msg');m.textContent='저장 중…';
 post('opinion_action',{id:b.getAttribute('data-vid'),on:on},function(ok,msg){if(ok)paintO(b,on);m.textContent=(ok?'✅ ':'❌ ')+msg})})});
fetch(API+'opinion_actions').then(function(r){return r.ok?r.json():null}).then(function(all){if(all)document.querySelectorAll('.oa-btn').forEach(function(b){var d=all[b.getAttribute('data-vid')];paintO(b,!!(d&&d.on))})}).catch(function(){});
function paintS(b,on){b.classList.toggle('on',on);b.setAttribute('aria-pressed',on?'true':'false');b.textContent=on?'⭐ 인상 깊은 영상 (별표됨)':'☆ 인상 깊은 영상'}
document.querySelectorAll('.star-btn').forEach(function(b){b.addEventListener('click',function(){var on=!b.classList.contains('on'),m=b.parentNode.querySelector('.act-msg');m.textContent='저장 중…';
 post('star',{id:b.getAttribute('data-vid'),on:on},function(ok,msg){if(ok)paintS(b,on);m.textContent=(ok?'✅ ':'❌ ')+msg})})});
fetch(API+'stars').then(function(r){return r.json()}).then(function(all){document.querySelectorAll('.star-btn').forEach(function(b){paintS(b,!!all[b.getAttribute('data-vid')])})}).catch(function(){});
fetch(API+'actions').then(function(r){return r.json()}).then(function(all){document.querySelectorAll('.act-btn').forEach(function(b){var d=all[b.getAttribute('data-vid')];paint(b,!!(d&&d.on))})}).catch(function(){});
})();</script>"""

OP_CSS = "<style>.op{margin-top:14px;padding-top:10px;border-top:1px dashed var(--bd)}.op textarea{width:100%;min-height:70px;box-sizing:border-box;font:inherit;padding:8px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:inherit}.oa-row{margin-top:8px}.op .oa-btn{background:transparent;color:inherit;border-color:var(--bd)}.op .oa-btn.on{background:#7048e8;border-color:#7048e8;color:#fff;font-weight:600}.oa-btn{font:inherit;margin-top:6px;padding:5px 14px;border-radius:8px;border:1px solid var(--bd);background:transparent;color:inherit;cursor:pointer}.oa-btn.on{background:#7048e8;border-color:#7048e8;color:#fff;font-weight:600}.op button{margin-top:6px;padding:6px 14px;border-radius:8px;border:1px solid var(--ac);background:var(--ac);color:#fff;cursor:pointer}.op-my{white-space:pre-wrap;background:var(--chip);border-radius:8px;padding:8px 10px}.op-ai{margin-top:8px;border-left:4px solid var(--ac);padding:6px 10px}.act-row{margin-top:12px;padding-top:8px;border-top:1px dashed var(--bd)}.act-btn{font:inherit;padding:5px 14px;border-radius:99px;border:1px solid var(--bd);background:transparent;color:inherit;cursor:pointer}.act-btn.on{background:#e8590c;border-color:#e8590c;color:#fff;font-weight:600}.star-btn{font:inherit;padding:5px 14px;border-radius:99px;border:1px solid var(--bd);background:transparent;color:inherit;cursor:pointer;margin-left:6px}.star-btn.on{background:#f5b301;border-color:#f5b301;color:#222;font-weight:600}</style>"

def box(con, vid, extras=True):
    """영상 카드 맨 아래: ① 🎯 직접 해보기·⭐ 버튼(extras) ② 나의 의견(AI 의견 전까지는 항상 편집 가능) + 있으면 AI 의견 ③ 💬 의견 action 버튼."""
    row = ""
    if extras:
        on = bool(_marked(con, "actions", vid))
        son = bool(_marked(con, "stars", vid))
        row = (f"<div class=act-row><button type=button class='act-btn{' on' if on else ''}' data-vid='{e(vid)}' aria-pressed={'true' if on else 'false'}>"
               f"{'🎯 직접 해볼 것 (표시됨)' if on else '🎯 직접 해보기'}</button>"
               f"<button type=button class='star-btn{' on' if son else ''}' data-vid='{e(vid)}' aria-pressed={'true' if son else 'false'}>"
               f"{'⭐ 인상 깊은 영상 (별표됨)' if son else '☆ 인상 깊은 영상'}</button> <span class='act-msg meta'></span>"
               f"<a class=meta href='actions.html' style='margin-left:8px'>액션 페이지 ›</a><a class=meta href='highlights.html' style='margin-left:8px'>인상 깊은 영상 ›</a></div>")
    o = get(con, vid)
    my = (o["my_opinion"] if o else "") or ""
    h = f"<div class=op data-vid='{e(vid)}'><b>💬 나의 의견</b><div class=op-body>"
    if o and o["ai_reply"]:
        h += f"<div class=op-my>{e(my)}</div><div class=op-ai><b>🤖 AI 의견</b> <span class=meta>({e(o['ai_llm'] or '-')} · {e((o['ai_at'] or '')[:10])})</span><div style='white-space:pre-wrap'>{e(o['ai_reply'])}</div></div>"
    else:
        h += f"<textarea placeholder='이 영상에 대한 내 생각을 적고 저장을 누르세요 (AI 의견은 다음 새벽에 달립니다)'>{e(my)}</textarea><button type=button class=op-save>저장</button> <span class='op-msg meta'></span>"
        if my: h += "<div class=meta>AI 의견 대기 중 — 다음 새벽 실행에서 달립니다. 그 전까지는 수정할 수 있습니다.</div>"
    h += "</div>" + oa_button(vid, bool(_marked(con, "opinion_actions", vid))) + "</div>"
    return row + h

def oa_button(vid, on):
    """💬 의견 action 버튼(영상 카드, 홈·나와 AI 의견 목록에서 같이 씀). 동작은 OP_JS."""
    return (f"<div class=oa-row><button type=button class='oa-btn{' on' if on else ''}' data-vid='{e(vid)}' aria-pressed={'true' if on else 'false'}>"
            f"{'💬 의견 action (표시됨)' if on else '💬 의견 action'}</button> <span class='oa-msg meta'></span></div>")

OI_CSS_BODY = """details.oi{border:1px solid var(--bd);border-radius:12px;padding:8px 12px;margin:10px 0;background:var(--card)}
details.oi>summary{cursor:pointer;list-style:none}details.oi>summary::-webkit-details-marker{display:none}
details.oi>summary b.t{font-size:15px}.cl{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;white-space:pre-wrap;font-size:13.5px;margin-top:3px}
.cl.ai{color:var(--mu)}details.oi[open]>summary .cl{display:none}
.bd{display:inline-block;font-size:12px;border-radius:99px;padding:0 9px;margin-left:6px;background:var(--chip)}.bd.ok{background:var(--ac);color:#fff}
"""
LIST_CSS = ("""<style>
.bar{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--bd);padding:10px 0;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center}
.bar label{font-size:13px;color:var(--mu)}.bar select{font:inherit;margin-left:4px;padding:4px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
.pager{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}.pager button{font:inherit;padding:3px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button.on{background:var(--ac);color:#fff;border-color:var(--ac)}.pager button:disabled{opacity:.4;cursor:default}
""" + OI_CSS_BODY + "</style>")

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

OP_ROWS = ("""SELECT * FROM (SELECT o.*, v.title, v.channel, v.category, v.subtag, COALESCE(v.run_id, v.processed_date) AS page FROM opinions o JOIN videos v ON v.id=o.video_id
              UNION ALL SELECT o.*, r.title, r.source AS channel, '부자들' AS category, r.topic AS subtag, 'rich' AS page FROM opinions o JOIN rich_ideas r ON 'rich:'||r.id=o.video_id) """)

def _item(r, filt=True, tag="", oa_on=False):
    """의견 한 항목(접힌 details). filt=True 이면 목록 페이지용 필터 속성과 hidden 을 붙인다."""
    has = bool(r["ai_reply"])
    attrs = (f" hidden data-ai={1 if has else 0} data-d='{e((r['my_at'] or '0000')[:10])}' data-c='{e(r['category'] or '기타')}' data-s='{e((r['category'] or '기타') + '/' + (r['subtag'] or '기타'))}'") if filt else ""
    return (f"<details class=oi{attrs}>"
            f"<summary><b class=t><span class=no></span>{e(r['title'])}</b><span class='bd{' ok' if has else ''}'>{'🤖 AI 의견 있음' if has else '⏳ AI 의견 대기'}</span> {tag}<span class=meta>{e((r['my_at'] or '')[:10])}</span>"
            f"<div class=cl>💬 {e(_head(r['my_opinion']))}</div>" + (f"<div class='cl ai'>🤖 {e(_head(r['ai_reply']))}</div>" if has else "") + "</summary>"
            f"<div class=meta style='margin-top:8px'>📺 {e(r['channel'] or '')} · {e(r['category'] or '')}/{e(r['subtag'] or '')} · 내 의견 {e((r['my_at'] or '').replace('T', ' '))} · <a href='{('rich.html#r-' + e(r['video_id'][5:])) if r['video_id'].startswith('rich:') else (e(r['page']) + '.html#v-' + e(r['video_id']))}'>{'부자들 항목으로' if r['video_id'].startswith('rich:') else '영상 카드로'} 가기 ›</a></div>"
            f"<p><b>💬 나의 의견</b></p><div class=op-my style='white-space:pre-wrap'>{e(r['my_opinion'])}</div>"
            + (f"<p><b>🤖 AI 의견</b> <span class=meta>({e(r['ai_llm'] or '-')} · {e((r['ai_at'] or '')[:10])})</span></p><div class=op-ai style='white-space:pre-wrap'>{e(r['ai_reply'])}</div>"
               if has else "<p class=meta>🤖 AI 의견은 다음 새벽 실행에서 달립니다.</p>") + oa_button(r["video_id"], oa_on) + "</details>")

def _oa_on(con):
    return {r[0] for r in con.execute("SELECT video_id FROM opinion_actions WHERE on_flag=1")}


def day_block(con, day, vids=()):
    """홈 '어제 확인한 항목' 아래: 그날 AI 의견이 달린 것 + 그날 확인한 항목의 영상에 남긴 의견. 없으면 빈 문자열."""
    vids = [v for v in vids if v]
    q = (OP_ROWS + "WHERE my_opinion IS NOT NULL AND my_opinion<>'' AND (substr(ai_at,1,10)=?" + (f" OR video_id IN ({','.join('?' * len(vids))})" if vids else "") + ") ORDER BY ai_at DESC, my_at DESC")
    rows = con.execute(q, (day, *vids)).fetchall()
    if not rows: return ""
    oa = _oa_on(con)
    items = "".join(_item(r, False, "<span class=meta>[오늘 AI 의견 달림]</span> " if (r["ai_at"] or "")[:10] == day else "<span class=meta>[확인한 항목의 영상]</span> ", r["video_id"] in oa) for r in rows)
    return (f"<h4 style='margin:18px 0 4px'>💬 나와 AI 의견 ({len(rows)})</h4><p class=meta>오늘 새벽({e(day)}) AI 의견이 달린 것과, 그때 확인한 항목의 영상에 남긴 내 의견입니다. 눌러서 펼치세요. <a href='opinions.html'>전체 보기 ›</a></p>"
            f"<style>{OI_CSS_BODY}</style>{OP_CSS}{items}{OP_JS}")


def build(con):
    """'나와 AI 의견' 페이지. 날짜·주제별 보기와 같은 선택(주제·기간·한 페이지 수) + AI 의견 있음/없음. 항목은 접힌 상태(summary=처음 부분)."""
    import report as R
    rows = con.execute(OP_ROWS + "WHERE my_opinion IS NOT NULL AND my_opinion<>'' ORDER BY my_at DESC").fetchall()
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
    oa = _oa_on(con)
    items = "".join(_item(r, oa_on=r["video_id"] in oa) for r in rows)
    body = (f"<h1>💬 나와 AI 의견</h1><p class=meta>내가 남긴 의견 {len(rows)}개 · AI 의견 달림 {n_ai}개 · 대기 {len(rows) - n_ai}개 · 내가 저장한 날짜 최신순 · 항목을 누르면 펼쳐집니다 · <a href='index.html'>🏠 홈</a> · 의견은 각 날짜 리포트나 <a href='browse.html'>🗂️ 날짜·주제별 보기</a>의 영상 카드 맨 아래에서 씁니다</p>")
    if not rows: body += "<p class=meta>아직 남긴 의견이 없습니다. 영상 카드 맨 아래 칸에 의견을 적고 저장하면 여기에 나타납니다.</p>"
    body += (f"<div class=bar><label>🤖 AI 의견 <select id=f-ai>{ai}</select></label><label>🏷️ 주제 <select id=f-topic>{topic}</select></label>"
             f"<label>📅 기간 <select id=f-recent>{recent}</select></label><label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
             f"<p class=meta id=oi-info></p><div class=pager id=pg-top></div><div id=oi-list>{items}</div><div class=pager id=pg-bot></div>")
    (R.OUT / "opinions.html").write_text(R.page("나와 AI 의견", OP_CSS + LIST_CSS + body + LIST_JS + OP_JS, "💬"), encoding="utf-8")
