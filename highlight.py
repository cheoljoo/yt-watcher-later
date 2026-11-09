"""'제일 인상 깊은 영상' 모음.  수집·저장·페이지 생성은 코드가, 상세 분석 JSON 작성만 AI(yt-highlight 스킬)가 한다.

  uv run highlight.py prepare URL [--note "왜 인상 깊었나"]  # (LLM 없음) 영상 수집 -> data/_work/hl/ID.input.md + 스키마 경로 출력
  uv run highlight.py submit ID --file F                    # 분석 JSON 검증 후 DB 저장, highlights.html 갱신
  uv run highlight.py build                                 # reports/highlights.html 만 다시 만들기 (report.build_all 도 호출)
  uv run highlight.py list
"""
import argparse, json, os, pathlib, re, sys
from html import escape as e
from jsonschema import Draft202012Validator
import db as D

W = pathlib.Path("data/_work/hl")
S = {"type": "string"}
def arr(item): return {"type": "array", "items": item}
def obj(req, **props): return {"type": "object", "required": req, "properties": props}
SCHEMA = obj(
    ["title_ko", "one_liner", "why_impressive", "tldr", "outline", "key_points", "concepts", "evidence", "numbers", "people",
     "lessons", "business", "action_items", "caveats", "further_questions"],
    title_ko=S, one_liner=S,
    why_impressive=dict(S, description="이 영상이 왜 인상 깊은지(2~4문장)"),
    tldr=dict(S, description="5~8문장 요약"),
    outline=dict(arr(obj(["when", "topic", "detail"], when=dict(S, description="자막상 대략의 구간/순서(예: 초반, 12분경)"), topic=S, detail=dict(S, description="그 구간의 내용을 상세히(3~6문장)"))), description="영상 흐름을 구간별로 6~15개"),
    key_points=dict(arr(obj(["point", "explanation"], point=S, explanation=dict(S, description="상세 설명 3~5문장"))), description="핵심 주장·통찰 8~15개"),
    concepts=arr(obj(["term", "explanation"], term=S, explanation=S)),
    evidence=arr(obj(["claim", "support", "caveat"], claim=S, support=dict(S, description="영상이 제시한 근거"), caveat=dict(S, description="한계·반론·검증 필요"))),
    numbers=arr(obj(["item", "detail"], item=S, detail=S)),
    people=arr(obj(["name", "role"], name=S, role=S)),
    lessons=dict(arr(S), description="배울 점 5개 이상, 구체적으로"),
    business=obj(["possible", "idea", "how", "risks"], possible={"type": "string", "enum": ["가능", "조건부", "어려움"]}, idea=S, how=dict(S, description="단계별 실행 방법(상세)"), risks=S),
    action_items=dict(arr(S), description="바로 해볼 수 있는 일"),
    caveats=dict(arr(S), description="오인식·편향·검증 필요한 부분"),
    further_questions=arr(S),
    links=arr(obj(["url", "context"], url=S, context=S)),
)
INSTR = """# 지시
아래 영상을 **매우 상세히** 분석해 JSON 으로 만드세요(스키마: {schema}). 한국어. 자막은 자동 음성인식이라 오인식이 있을 수 있으니 문맥으로 보정하세요.
- 요약이 아니라 '정리 노트'를 쓰는 기분으로: 구간별 흐름(outline), 핵심 주장마다 근거와 한계(evidence), 숫자·데이터(numbers), 용어(concepts)를 빠짐없이.
- why_impressive: 사용자 메모가 있으면 그것을 반영하고, 영상 내용에 근거해 무엇이 인상 깊은지 쓰세요.
- business: 이 내용으로 돈 버는 사업이 가능한지, 가능하면 고객·수익 방식·시작 단계·위험까지 구체적으로. 수익을 보장하는 것처럼 쓰지 마세요.
- 영상에 없는 내용을 지어내지 마세요. 자막이 잘렸으면 caveats 에 밝히세요.
- links 는 영상/설명/댓글에 실제로 나온 URL 만(없으면 빈 배열).
"""

def vid_of(url):
    m = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([\w-]{11})", url) or re.fullmatch(r"([\w-]{11})", url.strip())
    if not m: sys.exit(f"영상 ID 를 찾지 못했습니다: {url}")
    return m.group(1)

def schema_path():
    W.mkdir(parents=True, exist_ok=True); p = W / "schema.json"
    p.write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=1), encoding="utf-8"); return p

def prepare(url, note):
    import main as M
    from collect import collect
    vid = vid_of(url); W.mkdir(parents=True, exist_ok=True)
    col = collect(vid, M.cfg)
    info, cm = col["info"], col["info"].get("comments") or []
    comments = "\n".join(f"- ({c.get('like_count', 0)}👍) {c.get('text', '')[:400]}" for c in cm[:40]) or "(없음)"
    tr = col["transcript"] or "(자막 없음 — 제목/설명/댓글만으로 분석하고 caveats 에 밝히세요)"
    MAX = 150000
    if len(tr) > MAX: tr = tr[:MAX * 2 // 3] + f"\n…(중간 {len(tr) - MAX:,}자 생략)…\n" + tr[-MAX // 3:]
    meta = {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": info.get("title"), "note": note or "", **{k: col["meta"][k] for k in ("channel", "channel_url", "upload_date", "duration_sec", "view_count", "like_count")}}
    (W / f"{vid}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    sp = schema_path()
    (W / f"{vid}.input.md").write_text(
        INSTR.format(schema=sp) + f"\n# 입력\n[제목] {meta['title']}\n[채널] {meta['channel']}\n[업로드] {meta['upload_date']}\n[길이] {meta['duration_sec']}초\n"
        f"[사용자 메모] {note or '(없음)'}\n[설명]\n{(info.get('description') or '')[:3000]}\n\n[댓글]\n{comments}\n\n[자막]\n{tr}\n", encoding="utf-8")
    print(json.dumps({"id": vid, "input_file": str(W / f"{vid}.input.md"), "schema_file": str(sp), "out_file": str(W / f"{vid}.json"), "transcript_chars": len(col["transcript"] or "")}, ensure_ascii=False))

def submit(vid, file):
    data = json.loads(open(file, encoding="utf-8").read() if file else sys.stdin.read())
    errs = sorted(Draft202012Validator(SCHEMA).iter_errors({**{"links": []}, **data}), key=lambda x: list(x.path))
    if errs: sys.exit("스키마 검증 실패:\n" + "\n".join(f"- {'/'.join(map(str, x.path)) or '(최상위)'}: {x.message[:200]}" for x in errs[:8]))
    mp = W / f"{vid}.meta.json"
    if not mp.exists(): sys.exit("먼저 prepare 를 실행하세요")
    m = json.loads(mp.read_text(encoding="utf-8"))
    import tomllib
    model = os.environ.get("YT_MODEL") or tomllib.load(open("config.toml", "rb")).get("model", "sonnet")
    con = D.connect()
    con.execute("""INSERT INTO highlights(video_id,url,title,channel,channel_url,upload_date,duration_sec,view_count,note,added_at,engine,model,analysis_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET note=excluded.note, added_at=excluded.added_at,
                   engine=excluded.engine, model=excluded.model, analysis_json=excluded.analysis_json, title=excluded.title""",
                (vid, m["url"], m["title"], m["channel"], m["channel_url"], m["upload_date"], m["duration_sec"], m["view_count"], m["note"],
                 D.now(), os.environ.get("YT_ENGINE") or "claude", model, json.dumps(data, ensure_ascii=False)))
    con.commit(); build(con)
    print(f"OK {vid} 저장 — reports/highlights.html")

def ul(items): return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>" if items else "<p class=meta>없음</p>"

def card(r, n=None):
    a = json.loads(r["analysis_json"]); b = a.get("business") or {}
    h = f"<section class=card id='h-{e(r['video_id'])}'><h3>{('#' + str(n) + ' ') if n else ''}⭐ <a href='{e(r['url'])}'>{e(r['title'])}</a></h3>"
    h += (f"<div class=meta>📺 <a href='{e(r['channel_url'] or '#')}'>{e(r['channel'] or '')}</a> · 업로드 {e(r['upload_date'] or '-')} · "
          f"{(r['duration_sec'] or 0) // 60}분 · 조회 {r['view_count']:,} · 담은 시각 {e((r['added_at'] or '').replace('T', ' '))} · 🤖 {e(r['engine'])} · {e(r['model'])}</div>"
          if r["view_count"] is not None else "")
    h += f"<p><b>{e(a.get('one_liner', ''))}</b></p>"
    h += f"<h2>💡 왜 인상 깊은가</h2><p>{e(a.get('why_impressive', ''))}</p>"
    if r["note"]: h += f"<p class=meta>📝 내 메모: {e(r['note'])}</p>"
    h += f"<h2>📌 한눈에 보기</h2><p>{e(a.get('tldr', ''))}</p>"
    h += "<h2>🧭 영상 흐름</h2>" + "".join(f"<details><summary><b>{e(o['topic'])}</b> <span class=meta>{e(o['when'])}</span></summary><p>{e(o['detail'])}</p></details>" for o in a.get("outline", []))
    h += "<h2>🔑 핵심 내용</h2>" + "".join(f"<p><b>{i}. {e(k['point'])}</b><br>{e(k['explanation'])}</p>" for i, k in enumerate(a.get("key_points", []), 1))
    if a.get("evidence"): h += "<h2>🧪 근거와 한계</h2>" + "".join(f"<details><summary>{e(x['claim'])}</summary><p><b>근거</b> {e(x['support'])}</p><p><b>한계·검증</b> {e(x['caveat'])}</p></details>" for x in a["evidence"])
    if a.get("numbers"): h += "<h2>🔢 숫자·데이터</h2><ul>" + "".join(f"<li><b>{e(x['item'])}</b> — {e(x['detail'])}</li>" for x in a["numbers"]) + "</ul>"
    if a.get("concepts"): h += "<h2>📖 용어</h2><ul>" + "".join(f"<li><b>{e(x['term'])}</b> — {e(x['explanation'])}</li>" for x in a["concepts"]) + "</ul>"
    if a.get("people"): h += "<h2>🧑 등장 인물</h2><ul>" + "".join(f"<li>{e(x['name'])} <span class=meta>{e(x['role'])}</span></li>" for x in a["people"]) + "</ul>"
    h += "<h2>🎓 배울 점</h2>" + ul(a.get("lessons"))
    icon = {"가능": "💰", "조건부": "🟡", "어려움": "⚪"}.get(b.get("possible"), "💰")
    h += (f"<h2>{icon} 돈 버는 사업이 될 수 있나</h2><p><b>{e(b.get('possible', ''))}</b> — {e(b.get('idea', ''))}</p>"
          f"<p><b>어떻게</b> {e(b.get('how', ''))}</p><p><b>위험</b> {e(b.get('risks', ''))}</p>")
    h += "<h2>✅ 바로 해볼 일</h2>" + ul(a.get("action_items")) + "<h2>⚠️ 주의할 점</h2>" + ul(a.get("caveats")) + "<h2>❓ 더 알아볼 것</h2>" + ul(a.get("further_questions"))
    if a.get("links"): h += "<h2>🔗 링크</h2><ul>" + "".join(f"<li><a href='{e(x['url'])}'>{e(x['url'])}</a> <span class=meta>{e(x['context'])}</span></li>" for x in a["links"]) + "</ul>"
    return h + "</section>"

LAYOUT_CSS = """
main{max-width:none!important}
.hl{display:flex;gap:20px;align-items:flex-start}
.hl-nav{flex:0 0 280px;position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto;border-right:1px solid rgba(128,128,128,.35);padding-right:12px}
.hl-nav a{display:block;padding:8px 10px;margin:2px 0;border-radius:8px;text-decoration:none;color:inherit;line-height:1.35}
.hl-nav a:hover{background:rgba(128,128,128,.15)}
.hl-nav a.on{background:rgba(76,139,245,.2);font-weight:600;box-shadow:inset 3px 0 0 #4c8bf5}
.hl-nav{counter-reset:hn}.hl-nav a::before{counter-increment:hn;content:counter(hn) ". ";font-weight:700;color:#4c8bf5}.hl-nav small{display:block;opacity:.65;font-weight:400}
.hl-body{flex:1;min-width:0}
.js .hl-body section.card{display:none}.js .hl-body section.card.on{display:block}
@media(max-width:760px){.hl{display:block}.hl-nav{position:static;max-height:none;border-right:0;border-bottom:1px solid rgba(128,128,128,.35);padding:0 0 8px;margin-bottom:12px}}
"""
LAYOUT_JS = """<script>
(function(){document.documentElement.classList.add('js');
var links=[].slice.call(document.querySelectorAll('.hl-nav a')),cards=[].slice.call(document.querySelectorAll('.hl-body section.card'));
function show(){var id=(location.hash||'').slice(1);if(!id||!document.getElementById(id))id=cards.length?cards[0].id:'';
cards.forEach(function(c){c.classList.toggle('on',c.id===id)});links.forEach(function(a){a.classList.toggle('on',a.getAttribute('href')==='#'+id)});window.scrollTo(0,0)}
window.addEventListener('hashchange',show);show()})();
</script>"""

def build(con=None):
    import report as R
    con = con or D.connect(); R.OUT.mkdir(exist_ok=True)
    rows = con.execute("SELECT * FROM highlights ORDER BY added_at DESC").fetchall()
    nav = "".join(f"<a href='#h-{e(r['video_id'])}'>{e(r['title'])}<small>{e(r['channel'] or '')} · 담은 날 {e((r['added_at'] or '')[:10])}</small></a>" for r in rows)
    body = (f"<style>{LAYOUT_CSS}</style><h1>⭐ 제일 인상 깊었던 영상</h1><p class=meta>직접 고른 영상을 아주 상세히 정리한 모음 · {len(rows)}개 · 왼쪽에서 고르면 오른쪽에 내용이 나옵니다 · <a href='index.html'>목록</a> · "
            f"추가: Claude/agy 에서 <code>/yt-highlight URL</code></p>")
    if rows: body += f"<div class=hl><nav class=hl-nav>{nav}</nav><div class=hl-body>{''.join(card(r, i) for i, r in enumerate(rows, 1))}</div></div>{LAYOUT_JS}"
    else: body += "<p class=meta>아직 없습니다.</p>"
    (R.OUT / "highlights.html").write_text(R.page("인상 깊은 영상", body, "⭐"), encoding="utf-8")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("prepare"); p.add_argument("url"); p.add_argument("--note", default="")
    p = sp.add_parser("submit"); p.add_argument("id"); p.add_argument("--file")
    sp.add_parser("build"); sp.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "prepare": prepare(a.url, a.note)
    elif a.cmd == "submit": submit(a.id, a.file)
    elif a.cmd == "build": build()
    else:
        for r in D.connect().execute("SELECT video_id,title,added_at,engine,model FROM highlights ORDER BY added_at DESC"): print(tuple(r))
