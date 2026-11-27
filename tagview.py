"""태그별 보기 페이지 (reports/tags.html).

태그는 3단계다: 1 카테고리 → 2 주제(subtag) → 3 추가 태그(extra_tags). 왼쪽 트리는 이 계층 그대로이고,
태그 칩은 단계와 상관없이 '그 태그가 붙은 영상'을 고른다(여러 개 누르면 모두 가진 영상). 띄어쓰기·하이픈·대소문자만 다른 태그는 하나로 본다.
카드 전체를 다시 담지 않고 목록(JSON)만 넣은 뒤 브라우저에서 그린다. 영상 제목을 누르면 그날 리포트의 카드로 간다.

  uv run tagview.py     # reports/tags.html 만 다시 만들기 (report.build_all 도 호출)
"""
import collections, json
import db as D

CSS = """<style>
.tv{display:grid;grid-template-columns:minmax(220px,280px) 1fr;gap:16px;align-items:start}
@media (max-width:760px){.tv{grid-template-columns:1fr}.tree{max-height:45vh}}
.tree{position:sticky;top:8px;max-height:calc(100vh - 16px);overflow:auto;border:1px solid var(--bd);border-radius:10px;padding:8px;background:var(--card);font-size:14px}
.tree details{margin-left:4px}.tree details details,.tree .leafs{margin-left:16px}.tree summary{cursor:pointer;padding:2px 0}
.tree button{font:inherit;background:none;border:0;color:var(--fg);cursor:pointer;padding:1px 5px;border-radius:6px;text-align:left}
.tree button.on{background:var(--ac);color:#fff}.tree .n{color:var(--mu);font-size:12px}.tree button.on .n{color:#fff}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chips button{font:inherit;font-size:13px;border:1px solid var(--bd);border-radius:999px;background:var(--chip);color:var(--fg);padding:2px 10px;cursor:pointer}
.chips button.on{background:var(--ac);border-color:var(--ac);color:#fff}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:10px 0}.bar label{font-size:13px;color:var(--mu)}
.bar select{font:inherit;margin-left:4px;padding:4px 8px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
.pager{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0}.pager button{font:inherit;padding:3px 11px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
.pager button.on{background:var(--ac);color:#fff;border-color:var(--ac)}.pager button:disabled{opacity:.4;cursor:default}
#tq{font:inherit;padding:5px 10px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg);width:min(100%,280px)}
.vi{border-bottom:1px solid var(--bd);padding:10px 0}.vi a{font-weight:700}.vi .chips{margin:4px 0 0}
</style>"""

JS = """<script>(function(){
var D=JSON.parse(document.getElementById('tv-data').textContent),V=D.videos,N=D.names,
 sel={c:null,s:null,t:[]},page=1,allChips=false,fO=document.getElementById('f-sort'),fP=document.getElementById('f-per');
function pref(k,v){try{if(v==null)return localStorage.getItem(k);localStorage.setItem(k,v)}catch(e){return null}}
fO.value=pref('tv-sort')||'u-desc';fP.value=pref('tv-per')||'20';
// 정렬: u=업로드, p=처리 / desc=최근(기본), asc=오래된
function sorted(list){var m=fO.value,k=m.charAt(0)==='p'?'p':'d',sg=m.slice(-3)==='asc'?1:-1;return list.slice().sort(function(a,b){return a[k]<b[k]?-sg:a[k]>b[k]?sg:0})}
function pager(id,pages){var p=document.getElementById(id);p.textContent='';if(pages<2)return;
 function add(label,n,dis,on){var b=btn(label,on,function(){page=n;render();if(id==='pg-bot')document.getElementById('tv-top').scrollIntoView()});b.disabled=dis;p.appendChild(b)}
 add('‹ 이전',page-1,page<=1);var lo=Math.max(1,page-3),hi=Math.min(pages,page+3);if(lo>1)add('1',1);if(lo>2)p.appendChild(el('span',null,'…'));
 for(var i=lo;i<=hi;i++)add(String(i),i,false,i===page);if(hi<pages-1)p.appendChild(el('span',null,'…'));if(hi<pages)add(String(pages),pages);add('다음 ›',page+1,page>=pages)}
function el(tag,cls,text){var x=document.createElement(tag);if(cls)x.className=cls;if(text!=null)x.textContent=text;return x}
function btn(text,on,click){var b=el('button',on?'on':'',text);b.type='button';b.onclick=click;return b}
function has(v,k){return v.k.indexOf(k)>=0}
function match(v){return (!sel.c||v.c===sel.c)&&(!sel.s||v.s===sel.s)&&sel.t.every(function(k){return has(v,k)})}
function save(){var p=[];if(sel.c)p.push('c='+encodeURIComponent(sel.c));if(sel.s)p.push('s='+encodeURIComponent(sel.s));sel.t.forEach(function(k){p.push('t='+encodeURIComponent(k))});
 history.replaceState(null,'',p.length?'#'+p.join('&'):location.pathname)}
function load(){sel={c:null,s:null,t:[]};location.hash.slice(1).split('&').forEach(function(p){var i=p.indexOf('=');if(i<0)return;var a=p.slice(0,i),v;try{v=decodeURIComponent(p.slice(i+1))}catch(e){return}
 if(a==='c')sel.c=v;else if(a==='s')sel.s=v;else if(a==='t'&&N[v])sel.t.push(v)})}
function go(c,s,t){sel={c:c,s:s,t:t};page=1;render()}
function toggle(k){var i=sel.t.indexOf(k);if(i<0)sel.t.push(k);else sel.t.splice(i,1);page=1;render()}
function render(){
 [].forEach.call(document.querySelectorAll('.tree button'),function(b){var d=b.dataset,t=d.t||null;
  b.className=((d.c||null)===sel.c&&(d.s||null)===sel.s&&(t?sel.t.length===1&&sel.t[0]===t:!sel.t.length))?'on':''});
 var list=sorted(V.filter(match)),count={},per=+fP.value,pages=Math.max(1,Math.ceil(list.length/per));if(page>pages)page=pages;
 var from=(page-1)*per,to=Math.min(list.length,from+per);list.forEach(function(v){v.k.forEach(function(k){count[k]=(count[k]||0)+1})});
 var path=[sel.c,sel.s].filter(Boolean).concat(sel.t.map(function(k){return '#'+N[k]}));
 document.getElementById('tv-info').textContent=(path.length?path.join(' › '):'전체')+' · 영상 '+list.length+'개'+(list.length?' · '+(from+1)+'–'+to+'번째 · '+page+'/'+pages+' 쪽':'');
 var q=document.getElementById('tq').value.trim().toLowerCase(),box=document.getElementById('tv-chips');box.textContent='';
 var keys=Object.keys(count).filter(function(k){return !q||N[k].toLowerCase().indexOf(q)>=0}).sort(function(a,b){return (sel.t.indexOf(b)>=0)-(sel.t.indexOf(a)>=0)||count[b]-count[a]||N[a].localeCompare(N[b])});
 (allChips||q?keys:keys.slice(0,40)).forEach(function(k){box.appendChild(btn(N[k]+' '+count[k],sel.t.indexOf(k)>=0,function(){toggle(k)}))});
 if(!q&&keys.length>40)box.appendChild(btn(allChips?'접기':'태그 '+(keys.length-40)+'개 더 보기',false,function(){allChips=!allChips;render()}));
 var out=document.getElementById('tv-list');out.textContent='';
 list.slice(from,to).forEach(function(v){var row=el('div','vi'),a=el('a',null,v.title);a.href=v.href;row.appendChild(a);
  row.appendChild(el('div','meta',[v.d&&'업로드 '+v.d,v.p&&'처리 '+v.p.slice(0,10),v.ch,v.c+' / '+v.s].filter(Boolean).join(' · ')));if(v.one)row.appendChild(el('div',null,v.one));
  var ch=el('div','chips');v.k.forEach(function(k){ch.appendChild(btn(N[k],sel.t.indexOf(k)>=0,function(){toggle(k)}))});row.appendChild(ch);out.appendChild(row)});
 pager('pg-top',pages);pager('pg-bot',pages);
 if(!list.length)out.appendChild(el('p','meta','조건에 맞는 영상이 없습니다'));
 save()}
[].forEach.call(document.querySelectorAll('.tree button'),function(b){b.onclick=function(e){e.preventDefault();var d=b.dataset;
 if(b.parentNode.tagName==='SUMMARY')b.parentNode.parentNode.open=true;go(d.c||null,d.s||null,d.t?[d.t]:[])}});
document.getElementById('tq').oninput=render;
fO.onchange=function(){pref('tv-sort',fO.value);page=1;render()};fP.onchange=function(){pref('tv-per',fP.value);page=1;render()};
window.addEventListener('hashchange',function(){load();page=1;render()});
load();render()})();</script>"""


def key(tag):
    """띄어쓰기·하이픈·대소문자만 다른 태그를 하나로."""
    return "".join(str(tag).replace("-", " ").split()).casefold()


def collect(con):
    """-> (영상 목록, {비교값: 표시 이름}). 영상마다 c(카테고리) s(주제) x(추가 태그 비교값) k(모든 태그 비교값)."""
    tags = collections.defaultdict(list)
    for vid, level, tag in con.execute("SELECT video_id, level, tag FROM tags ORDER BY video_id, level, rowid"):
        if tag and str(tag).strip(): tags[vid].append((level, str(tag).strip()))
    spelled = collections.defaultdict(collections.Counter)
    for items in tags.values():
        for _, t in items: spelled[key(t)][t] += 1
    names = {k: c.most_common(1)[0][0] for k, c in spelled.items()}
    videos = []
    for v in con.execute("""SELECT id, title, channel, category, subtag, one_liner, upload_date, COALESCE(run_id, processed_date) AS run, COALESCE(processed_at, processed_date, '') AS done_at FROM videos WHERE status='done'
                            ORDER BY COALESCE(upload_date,'') DESC, COALESCE(processed_at,'') DESC"""):
        c, s = v["category"] or "기타", names.get(key(v["subtag"] or ""), v["subtag"] or "기타")
        mine = [(l, key(t)) for l, t in tags.get(v["id"], [])]
        all_keys = list(dict.fromkeys(k for _, k in mine))
        extra = list(dict.fromkeys(k for l, k in mine if l == 3 and k not in (key(c), key(s))))
        videos.append({"title": v["title"] or v["id"], "ch": v["channel"] or "", "c": c, "s": s, "x": extra, "k": all_keys, "one": v["one_liner"] or "",
                       "d": v["upload_date"] or "", "p": v["done_at"], "href": f"{v['run']}.html#v-{v['id']}"})
    return videos, names


def tree_html(videos, names):
    """카테고리 → 주제 → (그 주제 영상에 함께 붙은) 추가 태그. 수는 그 자리까지의 영상 수."""
    import report as R
    from html import escape as e
    tree = {}
    for v in videos: tree.setdefault(v["c"], {}).setdefault(v["s"], []).append(v)
    size = lambda c: sum(len(x) for x in tree[c].values())
    def node(label, n, c=None, s=None, t=None):
        data = "".join(f' data-{a}="{e(val)}"' for a, val in (("c", c), ("s", s), ("t", t)) if val)
        return f'<button type=button{data}>{e(label)} <span class=n>{n}</span></button>'
    h = f"<div>{node('전체', len(videos))}</div>"
    for c in sorted(tree, key=lambda c: (R.CAT_ORDER.index(c) if c in R.CAT_ORDER else len(R.CAT_ORDER), c)):
        h += f"<details{' open' if size(c) == max(map(size, tree)) else ''}><summary>{node(R.CAT_ICON.get(c, '📌') + ' ' + c, size(c), c)}</summary>"
        for s, vs in sorted(tree[c].items(), key=lambda kv: (-len(kv[1]), kv[0])):
            counts = collections.Counter(k for v in vs for k in v["x"])
            leafs = "".join(f"<div>{node(names[k], n, c, s, k)}</div>" for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], names[kv[0]])))
            h += (f"<details><summary>{node(s, len(vs), c, s)}</summary><div class=leafs>{leafs}</div></details>" if leafs else f"<div>{node(s, len(vs), c, s)}</div>")
        h += "</details>"
    return h


def build(con=None):
    import report as R
    con = con or D.connect(); R.OUT.mkdir(exist_ok=True)
    videos, names = collect(con)
    data = json.dumps({"videos": videos, "names": names}, ensure_ascii=False).replace("<", "\\u003c")
    sort = "".join(f"<option value={v}>{t}</option>" for v, t in (("u-desc", "업로드 (최근)"), ("u-asc", "업로드 (오래된)"), ("p-desc", "처리날짜 (최근)"), ("p-asc", "처리날짜 (오래된)")))
    per = "".join(f"<option value={n}>{n}개</option>" for n in (10, 20, 50, 100))
    body = (f"<h1>🏷️ 태그별 보기</h1><p class=meta>분석한 영상 {len(videos)}개 · 태그 {len(names)}개 · 왼쪽은 <b>카테고리 → 주제 → 추가 태그</b> 계층, 태그 칩을 여러 개 누르면 모두 붙은 영상만 · "
            f"<a href='browse.html'>🗂️ 날짜·주제별 보기</a> · <a href='index.html'>🏠 홈</a></p>"
            f"<div class=tv><nav class=tree>{tree_html(videos, names)}</nav>"
            f"<div><input id=tq type=search placeholder='태그 이름 찾기'><div class=chips id=tv-chips></div>"
            f"<div class=bar id=tv-top><label>↕️ 정렬 <select id=f-sort>{sort}</select></label><label>📄 한 페이지 <select id=f-per>{per}</select></label></div>"
            f"<p class=meta id=tv-info></p><div class=pager id=pg-top></div><div id=tv-list></div><div class=pager id=pg-bot></div></div></div>"
            f"<script type='application/json' id=tv-data>{data}</script>")
    (R.OUT / "tags.html").write_text(R.page("태그별 보기", CSS + body + JS, "🏷️"), encoding="utf-8")


if __name__ == "__main__":
    build(); print("reports/tags.html 생성")
