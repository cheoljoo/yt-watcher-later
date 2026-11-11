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

def build(con):
    """'나와 AI 의견' 페이지: 의견을 남긴 영상 목록(최근 저장 순)."""
    import report as R
    rows = con.execute("""SELECT o.*, v.title, v.url, v.channel, COALESCE(v.run_id, v.processed_date) AS page FROM opinions o JOIN videos v ON v.id=o.video_id
                          WHERE o.my_opinion IS NOT NULL AND o.my_opinion<>'' ORDER BY o.my_at DESC""").fetchall()
    n_ai = sum(1 for r in rows if r["ai_reply"])
    body = (f"<h1>💬 나와 AI 의견</h1><p class=meta>내가 남긴 의견 {len(rows)}개 · AI 의견 달림 {n_ai}개 · 대기 {len(rows) - n_ai}개 · <a href='index.html'>🏠 홈</a> · 의견은 각 날짜 리포트의 영상 카드 맨 아래에서 씁니다</p>")
    if not rows: body += "<p class=meta>아직 남긴 의견이 없습니다.</p>"
    body += "<div class=numbered>"
    for r in rows:
        body += (f"<section class='card vc'><h3><a href='{e(r['page'])}.html#v-{e(r['video_id'])}'>{e(r['title'])}</a></h3>"
                 f"<div class=meta>📺 {e(r['channel'] or '')} · 내 의견 {e((r['my_at'] or '').replace('T', ' '))}</div>"
                 f"<p><b>💬 나의 의견</b></p><div class=op-my style='white-space:pre-wrap'>{e(r['my_opinion'])}</div>")
        if r["ai_reply"]: body += f"<p><b>🤖 AI 의견</b> <span class=meta>({e(r['ai_llm'] or '-')} · {e((r['ai_at'] or '')[:10])})</span></p><div class=op-ai style='white-space:pre-wrap'>{e(r['ai_reply'])}</div>"
        else: body += "<p class=meta>🤖 AI 의견 대기 중 (다음 새벽 실행에서 달립니다)</p>"
        body += "</section>"
    body += "</div>"
    (R.OUT / "opinions.html").write_text(R.page("나와 AI 의견", OP_CSS + body, "💬"), encoding="utf-8")
