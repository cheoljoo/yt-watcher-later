"""액션 페이지 (reports/actions.html): 리포트에서 '🎯 직접 해보기'를 켠 영상만 모아 보고, 해본 뒤의 의견(comment)을 적어 저장한다.
저장은 opinion_server.py (/action, /action_comment) -> DB actions 표."""
from html import escape as e
import db as D

CSS = """<style>
.ac{border:1px solid var(--bd);border-radius:12px;padding:10px 14px;margin:12px 0;background:var(--card)}
.ac textarea{width:100%;min-height:90px;box-sizing:border-box;font:inherit;padding:8px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:inherit}
.ac button{margin-top:6px;padding:6px 14px;border-radius:8px;border:1px solid #e8590c;background:#e8590c;color:#fff;cursor:pointer}
.ac button.off{background:transparent;color:inherit;border-color:var(--bd);margin-left:6px}
</style>"""

JS = """<script>(function(){
var API='api/',TK='ytwl_token';
function tok(){try{return localStorage.getItem(TK)||''}catch(x){return ''}}
function post(path,body,msg,cb){var t=tok();if(!t){t=prompt('저장용 비밀 토큰을 입력하세요 (한 번만 입력하면 이 브라우저에 기억됩니다)')||'';if(!t)return;try{localStorage.setItem(TK,t)}catch(x){}}
 msg.textContent='저장 중…';
 fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-Token':t},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(j){return[r.status,j]})}).then(function(p){
  if(p[0]==401){try{localStorage.removeItem(TK)}catch(x){}msg.textContent='❌ 토큰이 맞지 않습니다. 다시 눌러 입력하세요';return}
  msg.textContent=(p[1].ok?'✅ ':'❌ ')+p[1].message;if(p[1].ok&&cb)cb()}).catch(function(){msg.textContent='❌ 저장 서버에 연결하지 못했습니다'})}
document.querySelectorAll('.ac').forEach(function(b){var vid=b.getAttribute('data-vid'),ta=b.querySelector('textarea'),m=b.querySelector('.ac-msg');
 b.querySelector('.ac-save').onclick=function(){post('action_comment',{id:vid,text:ta.value},m)};
 b.querySelector('.ac-off').onclick=function(){if(!confirm('액션 표시를 해제할까요? (의견은 보관됩니다)'))return;post('action',{id:vid,on:false},m,function(){b.style.opacity=.4})}});
})();</script>"""

def build(con):
    import report as R
    R.OUT.mkdir(exist_ok=True)
    rows = con.execute("""SELECT a.*, v.title, v.channel, v.category, v.subtag, v.one_liner, COALESCE(v.run_id, v.processed_date) AS page
                          FROM actions a JOIN videos v ON v.id=a.video_id WHERE a.on_flag=1 ORDER BY a.on_at DESC""").fetchall()
    done = sum(1 for r in rows if (r["comment"] or "").strip())
    items = ""
    for i, r in enumerate(rows, 1):
        st = f"📝 의견 있음 ({e((r['comment_at'] or '')[:10])})" if (r["comment"] or "").strip() else "⏳ 아직 해보지 않음"
        items += (f"<div class=ac data-vid='{e(r['video_id'])}'><b>#{i} {e(r['title'])}</b> <span class=meta>{st}</span>"
                  f"<div class=meta>📺 {e(r['channel'] or '')} · {e(r['category'] or '')}/{e(r['subtag'] or '')} · 표시 {e((r['on_at'] or '').replace('T', ' '))} · "
                  f"<a href='{e(r['page'])}.html#v-{e(r['video_id'])}'>영상 카드로 가기 ›</a></div>"
                  f"<div style='margin:6px 0'>{e(r['one_liner'] or '')}</div>"
                  f"<textarea placeholder='직접 해보고 느낀 점·결과를 적고 저장을 누르세요'>{e(r['comment'] or '')}</textarea>"
                  f"<button type=button class=ac-save>저장</button><button type=button class='ac-off off'>표시 해제</button> <span class='ac-msg meta'></span></div>")
    body = (f"<h1>🎯 액션 — 직접 해봐야 할 것</h1><p class=meta>표시한 영상 {len(rows)}개 · 의견 남김 {done}개 · 표시한 최신순 · <a href='index.html'>🏠 홈</a> · "
            f"표시는 각 영상 카드 맨 아래 🎯 버튼으로 합니다</p>"
            + (items or "<p class=meta>아직 표시한 영상이 없습니다. 영상 카드 맨 아래 '🎯 직접 해보기' 버튼을 누르세요.</p>"))
    (R.OUT / "actions.html").write_text(R.page("액션", CSS + body + JS, "🎯"), encoding="utf-8")

if __name__ == "__main__":
    build(D.connect()); print("reports/actions.html 생성")
