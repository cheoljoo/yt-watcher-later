"""부자들 페이지(reports/rich.html): 매일 웹을 검색해 '부자들이 쓰는 투자 방법' 3개를 찾아 DB(rich_ideas)에 요약과 원문 링크로 쌓는다.
- 조사는 work.py 의 'rich' 단계(웹 검색 필수)가 하루 한 번 한다. 오늘 이미 있으면 건너뛰고, 최근 제목은 입력에 넣어 중복을 피한다.
- 페이지는 DB 만 읽는다. 주제·기간으로 골라 볼 수 있다. 투자 권유가 아니라 '이런 방법이 있다'는 정보다."""
import datetime
from html import escape as e
import db as D

PER_DAY = 3
TOPICS = ["부동산", "주식·펀드", "대체투자(사모·벤처·실물)", "채권·현금성", "절세·상속·증여", "가족사무소·자산관리", "원자재·귀금속", "가상자산", "기타"]

_ITEM = {"type": "object", "required": ["topic", "title", "summary", "url", "pub_date", "source", "who"], "properties": {
    "topic": {"type": "string", "enum": TOPICS}, "title": {"type": "string"}, "summary": {"type": "string"},
    "url": {"type": "string"}, "pub_date": {"type": "string"}, "source": {"type": "string"}, "who": {"type": "string"}}}
SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": _ITEM}}}

PROMPT = ("오늘({today}) 웹을 검색해 '부자들(고액 자산가·가족사무소·기관급 투자자)만 주로 쓰는 투자 방법' 을 정확히 3개 찾으세요. "
          "★웹 검색 필수★ 검색에서 확인한 내용만 쓰고 기억으로 지어내지 마세요. "
          "★최신 우선★ 먼저 최근 1주일 안에 나온 기사·리포트·인터뷰 중에서 지금 가장 화제이거나 시장 상황과 맞는 것을 찾고, 1주일 안에서 3개를 못 채우면 최근 1개월, 그래도 모자라면 최근 3개월까지 넓히세요. 3개월보다 오래된 자료는 쓰지 마세요. "
          "일반인이 잘 쓰지 못하는 것(사모펀드·프리IPO·벤처·부동산 법인/신탁·가족신탁·증여/상속 절세 구조·헤지 전략·대체투자·원자재·실물자산·패밀리오피스 자산배분 등)을 우선하고, 흔한 적금·ETF 적립식은 제외합니다. "
          "서로 다른 주제에서 고르고, 아래 '이미 수집한 항목'과 같은 방법·같은 링크는 피하세요. "
          "각 항목: topic=주제(목록 중 하나), title=방법 이름(30자 안팎), summary=이 방법이 무엇이고 부자들이 왜·어떻게 쓰는지, 일반인이 따라 하기 어려운 이유나 위험까지 3~4문장(한국어, 숫자·출처 내용 포함), "
          "url=원문 주소(검색에서 실제로 확인한 http 주소만, 모르면 항목을 빼고 다른 것을 찾으세요), pub_date=원문 기사의 게시일(YYYY-MM-DD, 원문에서 확인한 날짜만; 날짜를 확인할 수 없는 자료는 쓰지 마세요), "
          "source=매체·기관 이름, who=누가 쓰는지(예: 국내 자산가, 미국 패밀리오피스, 대형 기관). "
          "투자 권유가 아니라 정보로 쓰고, 광고성·확인되지 않은 주장이면 summary 에 그렇다고 밝히세요. 입력의 이미 수집한 항목: ")


def recent_titles(con, n=60):
    return [r[0] for r in con.execute("SELECT title FROM rich_ideas ORDER BY id DESC LIMIT ?", (n,))]


def task_body(con):
    t = recent_titles(con)
    return "(없음)" if not t else "\n".join("- " + x for x in t)


def prompt(): return PROMPT.format(today=D.today())


def need_today(con):
    return con.execute("SELECT count(*) FROM rich_ideas WHERE date=?", (D.today(),)).fetchone()[0] < PER_DAY


def apply(con, data):
    """결과 저장. 링크가 http 로 시작하지 않거나 이미 있는 링크는 버린다. 반환: 저장 수(하루 최대 PER_DAY)."""
    have = con.execute("SELECT count(*) FROM rich_ideas WHERE date=?", (D.today(),)).fetchone()[0]
    n = 0
    for it in data["items"]:
        if have + n >= PER_DAY: break
        url = it["url"].strip()
        if not url.startswith("http") or not it["summary"].strip() or not it["pub_date"].strip()[:4].isdigit(): continue
        cur = con.execute("INSERT OR IGNORE INTO rich_ideas(date,topic,title,summary,url,source,who,llm,created_at,pub_date) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (D.today(), it["topic"], it["title"].strip(), it["summary"].strip(), url, it["source"].strip(), it["who"].strip(), D.llm_tag(), D.now(), it["pub_date"].strip()))
        n += cur.rowcount
    con.commit()
    return n


def build(con):
    import report as R
    rows = con.execute("SELECT * FROM rich_ideas ORDER BY date DESC, id").fetchall()
    cnt = {}
    for r in rows: cnt[r["topic"]] = cnt.get(r["topic"], 0) + 1
    opt = lambda v, l: f"<option value='{e(str(v))}' data-l='{e(l)}'>{e(l)}</option>"
    topic = opt("all", "모두") + "".join(opt(t, t) for t in TOPICS if t in cnt)
    rec = opt("all", "모두") + "".join(opt(d, t) for d, t in ((0, "오늘"), (7, "최근 1주일"), (30, "최근 1개월"), (90, "최근 3개월"), (365, "최근 1년")))
    items = ""
    for r in rows:
        items += (f"<section class='card ri' hidden data-t='{e(r['topic'])}' data-d='{e(r['date'])}'><h3><span class=no></span>{e(r['title'])}</h3>"
                  f"<div class=meta>🏷️ {e(r['topic'])} · 📰 기사 {e(r['pub_date'] or '날짜 미확인')} · 📅 수집 {e(r['date'])} · 👤 {e(r['who'] or '')} · 🏢 {e(r['source'] or '')}</div>"
                  f"<p style='white-space:pre-wrap'>{e(r['summary'])}</p><p><a href='{e(r['url'])}' target=_blank rel=noopener>원문 보기 ›</a></p></section>")
    body = (f"<h1>💰 부자들</h1><p class=meta>매일 웹을 검색해 부자들(고액 자산가·가족사무소·기관급)이 쓰는 투자 방법을 3개씩 요약해 쌓습니다 · 총 {len(rows)}개 · 선택 칸 옆 숫자는 (해당 개수)-오늘 추가된 개수 · "
            "<a href='index.html'>🏠 홈</a></p><p class=meta>요약은 AI가 웹 검색 결과를 정리한 것이라 틀리거나 광고성일 수 있고, 투자 권유가 아닙니다. 판단 전에 원문을 확인하세요.</p>")
    if not rows: body += "<p class=meta>아직 수집된 항목이 없습니다. 다음 새벽 실행에서 3개가 채워집니다.</p>"
    body += (f"<div class=bar><label>🏷️ 주제 <select class=fk data-k=t id=f-topic>{topic}</select></label>"
             f"<label>📅 기간(수집일) <select class=fk data-k=r id=f-recent>{rec}</select></label></div><p class=meta id=ri-info></p><div id=ri-list>{items}</div>")
    js = """<script>(function(){
var rows=[].slice.call(document.querySelectorAll('.ri')),sels=[].slice.call(document.querySelectorAll('select.fk')),info=document.getElementById('ri-info');
function ymd(d){return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
var td=ymd(new Date());function co(v){var d=new Date();d.setDate(d.getDate()-(+v));return ymd(d)}
function match(x,k,v){if(v==='all')return true;if(k==='t')return x.dataset.t===v;return x.dataset.d>=co(v)}
sels.forEach(function(s){var k=s.dataset.k;[].forEach.call(s.options,function(o){var n=0,m=0;rows.forEach(function(x){if(match(x,k,o.value)){n++;if(x.dataset.d===td)m++}});o.textContent=o.dataset.l+' ('+n+')-'+m})});
function apply(){var n=0;rows.forEach(function(x){var ok=sels.every(function(s){return match(x,s.dataset.k,s.value)});x.hidden=!ok;if(ok){n++;x.querySelector('.no').textContent='#'+n+' '}});info.textContent='조건에 맞는 항목 '+n+'개 / 전체 '+rows.length+'개'}
sels.forEach(function(s){s.onchange=apply});apply()})();</script>"""
    import opinions as OPN
    (R.OUT / "rich.html").write_text(R.page("부자들", OPN.LIST_CSS + body + js, "💰"), encoding="utf-8")
