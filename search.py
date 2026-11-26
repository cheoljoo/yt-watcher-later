"""홈 화면 검색창: YouTube URL 이나 키워드(제목 일부)를 넣으면 분석해 둔 영상을 찾아 그 영상 카드로 보내 준다.

build(con) 이 reports/search_index.json 을 만들고(제목·채널·키워드·태그·등장인물·한 줄·요약; 자막 원문은 크기 때문에 넣지 않음),
widget() 은 홈에 넣을 검색창 HTML+JS 를 돌려준다. 검색은 브라우저에서만 한다(서버 부하 없음). 검색창에 처음 손댈 때 색인을 한 번 받는다."""
import json


def _list(s):
    try: v = json.loads(s or "[]")
    except Exception: return str(s or "")
    return " ".join(str(x) for x in v) if isinstance(v, list) else str(v)


def build(con):
    import report as R
    tags, people = {}, {}
    for r in con.execute("SELECT video_id, tag FROM tags"): tags.setdefault(r["video_id"], []).append(r["tag"])
    for r in con.execute("SELECT video_id, name FROM people"): people.setdefault(r["video_id"], []).append(r["name"])
    out, seen = [], set()
    for v in con.execute("SELECT * FROM videos WHERE status='done' ORDER BY COALESCE(upload_date, processed_date) DESC"):
        vid = v["id"]; seen.add(vid)
        out.append({"i": vid, "t": v["title"] or "", "c": v["channel"] or "", "d": v["upload_date"] or v["processed_date"] or "",
                    "g": f"{v['category'] or ''} {v['subtag'] or ''}".strip(), "p": v["run_id"] or v["processed_date"],
                    "o": v["one_liner"] or "",
                    "k": " ".join([_list(v["keywords"]), _list(v["extra_tags"]), " ".join(tags.get(vid, [])), " ".join(people.get(vid, []))]),
                    "s": v["summary"] or ""})
    for b in con.execute("SELECT video_id, title FROM backlog"):                 # 재생목록에는 있지만 아직 분석 전
        if b["video_id"] not in seen: seen.add(b["video_id"]); out.append({"i": b["video_id"], "t": b["title"] or "", "w": 1})
    (R.OUT / "search_index.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(out)


# 순수 함수(검색 규칙) — node 로 따로 시험할 수 있게 분리해 둔다
CORE_JS = r"""
function ytId(q){var m=q.match(/(?:[?&]v=|youtu\.be\/|\/shorts\/|\/live\/|\/embed\/)([A-Za-z0-9_-]{11})/);return m?m[1]:null}
function norm(s){return (s||'').normalize('NFC').toLowerCase()}
function find(data,q){
  q=q.trim(); if(!q) return {items:[],note:''};
  var id=ytId(q), bare=/^[A-Za-z0-9_-]{11}$/.test(q)&&data.some(function(x){return x.i===q});
  if(id||bare){var hit=data.filter(function(x){return x.i===(id||q)});
    return {items:hit,note:hit.length?'':'이 URL 의 영상은 수집된 목록에 없습니다'}}
  var toks=norm(q).split(/[\s|│·,]+/).filter(function(t){return t.length>0});
  if(!toks.length) return {items:[],note:''};
  var scored=data.map(function(x){
    var t=norm(x.t),k=norm(x.k),c=norm(x.c),rest=norm((x.o||'')+' '+(x.s||'')+' '+(x.g||'')),n=0,sc=0;
    toks.forEach(function(w){var s=0;if(t.indexOf(w)>=0)s=10;else if(k.indexOf(w)>=0)s=4;else if(c.indexOf(w)>=0)s=3;else if(rest.indexOf(w)>=0)s=1;if(s){n++;sc+=s}});
    return {x:x,n:n,sc:sc}});
  var all=scored.filter(function(r){return r.n===toks.length}), note='';
  if(!all.length&&toks.length>1){all=scored.filter(function(r){return r.n>=Math.ceil(toks.length/2)});if(all.length)note='모든 단어가 들어간 영상은 없어, 일부 단어가 맞는 영상을 보여 줍니다'}
  all.sort(function(a,b){return b.n-a.n||b.sc-a.sc||String(b.x.d||'').localeCompare(String(a.x.d||''))});
  return {items:all.map(function(r){return r.x}),note:note||(all.length?'':'찾은 영상이 없습니다')}
}
"""

UI_JS = r"""
(function(){
var inp=document.getElementById('sq'),out=document.getElementById('sres'),data=null,loading=null,limit=20,timer=null;
function load(){if(!loading)loading=fetch('search_index.json',{cache:'no-cache'}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){data=d;return d}).catch(function(){loading=null;out.textContent='검색 색인을 불러오지 못했습니다'});return loading}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e}
function link(text,href,blank){var a=el('a',null,text);a.href=href;if(blank){a.target='_blank';a.rel='noopener'}return a}
function render(){
  out.textContent='';var q=inp.value;if(!q.trim()||!data)return;
  var r=find(data,q);
  if(r.items.length)out.appendChild(el('div','meta',r.items.length+'개'+(r.items.length>limit?' 중 '+limit+'개':'')));
  if(r.note)out.appendChild(el('div','meta',r.note));
  r.items.slice(0,limit).forEach(function(x){
    var box=el('div','sr'),h=el('div');var yt='https://www.youtube.com/watch?v='+x.i;
    if(x.w){h.appendChild(link(x.t||x.i,yt,true));h.appendChild(el('span','meta',' · 아직 분석 전(재생목록에만 있음)'));box.appendChild(h)}
    else{h.appendChild(link(x.t,x.p+'.html#v-'+x.i));box.appendChild(h);
      var m=el('div','meta',[x.c,x.d,x.g].filter(Boolean).join(' · ')+' · ');m.appendChild(link('YouTube ›',yt,true));box.appendChild(m);
      if(x.o)box.appendChild(el('div','so',x.o))}
    out.appendChild(box)});
  if(r.items.length>limit){var b=el('button',null,'더 보기');b.type='button';b.onclick=function(){limit+=20;render()};out.appendChild(b)}
}
function go(){limit=20;load().then(function(){if(data)render()})}
inp.addEventListener('focus',load);
inp.addEventListener('input',function(){clearTimeout(timer);timer=setTimeout(go,200)});
document.getElementById('sform').addEventListener('submit',function(ev){ev.preventDefault();clearTimeout(timer);
  load().then(function(){if(!data)return;limit=20;render();var r=find(data,inp.value);
    if(ytId(inp.value)&&r.items.length===1&&!r.items[0].w)location.href=r.items[0].p+'.html#v-'+r.items[0].i});
  history.replaceState(null,'','?q='+encodeURIComponent(inp.value))});
var m=location.search.match(/[?&]q=([^&]*)/);if(m){inp.value=decodeURIComponent(m[1].replace(/\+/g,' '));go()}
})();
"""

CSS = """<style>.srch{margin:10px 0 14px}.srch form{display:flex;gap:8px;max-width:680px;margin:0 auto}
.srch input{flex:1;min-width:0;font:inherit;font-size:16px;padding:11px 18px;border:1px solid var(--bd);border-radius:99px;background:var(--card);color:var(--fg);box-shadow:0 1px 6px rgba(0,0,0,.1)}
.srch button{font:inherit;padding:8px 18px;border:1px solid var(--bd);border-radius:99px;background:var(--card);color:var(--fg);cursor:pointer}
#sres{max-width:680px;margin:8px auto 0}#sres .sr{border:1px solid var(--bd);border-radius:10px;padding:8px 12px;margin:6px 0;background:var(--card)}#sres .so{font-size:13.5px;margin-top:2px}</style>"""


def widget():
    return (CSS + "<div class=srch><form id=sform role=search><input id=sq type=search autocomplete=off aria-label='영상 검색' "
            "placeholder='YouTube URL 또는 키워드·제목으로 영상 찾기'><button type=submit>검색</button></form><div id=sres></div></div>"
            "<script>" + CORE_JS + UI_JS + "</script>")
