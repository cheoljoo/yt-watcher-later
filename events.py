"""주별 큰 일(week_events): 지표 추이의 '중요한 날'(붉은 큰 점)과 보라 띠가 있는 날의 해당 주·전주에 무슨 큰 일이 있었는지.
- 조사 단위는 '주'(월~일). 주마다 한국·미국·세계 각각에서 경제·금융시장에 가장 큰 영향을 준 일 1개씩을 웹 검색으로 찾아 week_events 에 (주, 지역) 한 줄씩 저장한다.
- 큰 일이 없었던 지역은 title 을 빈 문자열로 저장해(다시 조사하지 않게 하되) 페이지에서는 건너뛴다. 오늘이 들어 있는 주는 조사도 표시도 하지 않는다(알고 있으니까).
- 페이지(indicator_trends.py)는 DB 에 있는 것만 읽는다. 조사는 work.py 의 'events' 단계(웹 검색 필수)가 한다."""
import datetime
import db as D

PER_RUN = 20       # 한 번 실행에서 조사하는 최대 주 수
CHUNK = 4          # 한 작업(세션 한 번)에 맡기는 주 수
CATS = ["통화정책", "경제지표", "증시·시장", "무역·정책", "기업·실적", "원자재·환율", "정치·지정학", "기타경제"]
REGIONS = [("kr", "한국"), ("us", "미국"), ("world", "세계")]
_ITEM = {"type": "object", "required": ["date", "title", "detail", "category"], "properties": {
    "date": {"type": "string"}, "title": {"type": "string"}, "detail": {"type": "string"}, "category": {"type": "string", "enum": CATS}}}
SCHEMA = {"type": "object", "required": ["weeks"], "properties": {"weeks": {"type": "array", "items": {
    "type": "object", "required": ["week"] + [k for k, _ in REGIONS], "properties": {"week": {"type": "string"}, **{k: _ITEM for k, _ in REGIONS}}}}}}

PROMPT = ("입력의 각 항목은 조사할 '주'(월요일 날짜, 월~일)입니다. 주마다 한국(kr)·미국(us)·세계(world) 세 곳에서 그 주 '경제에 가장 큰 영향을 준 일'을 각각 '딱 1개'씩 골라 웹 검색으로 확인하세요. "
          "뽑는 기준은 '경제·금융시장에 미친 영향'입니다. 금리·중앙은행 결정, 물가·고용·성장률·수출 같은 경제지표 발표, 주가·환율·채권금리·유가의 큰 움직임, 관세·무역·재정·규제 같은 경제 정책, 대형 기업 실적·인수·상장은 물론, "
          "정치·전쟁·분쟁·재난·사건사고도 유가·원자재·소비재 가격, 환율, 증시, 교역, 물가에 크게 영향을 준 일이면 반드시 포함합니다(예: 전쟁으로 유가 급등, 선거 결과로 증시·환율 급변, 제재로 공급 차질). "
          "그런 일은 사건 자체와 함께 '경제에 어떤 영향이 났는지'(가격·지수 변화 숫자)를 detail 에 쓰세요. 경제·시장에 뚜렷한 영향이 없는 정치·사건은 넣지 않습니다. "
          "kr=한국 경제·금융시장과 한국에 영향을 준 일(코스피·환율·한국은행·수출·정부 경제정책 등), us=미국 경제·금융시장과 미국발 영향(연준·고용·물가·증시·경제정책 등), "
          "world=한국·미국 밖이거나 전 세계 경제에 영향을 준 일(중국·유럽·일본 경제, 유가·원자재, 전쟁·지정학, 글로벌 기업 등, kr·us 와 같은 일을 또 쓰지 마세요). "
          "★웹 검색 필수★ 당신의 기억은 틀릴 수 있으니 주마다 검색(WebSearch/search_web 등)으로 확인하고, 검색에서 확인한 사실만 쓰세요. "
          "검색어에는 연·월과 '코스피', '원달러 환율', '유가', '금리 결정', 'CPI', '고용지표', '나스닥', '관세', '전쟁 증시' 등을 섞어 쓰세요. "
          "각 지역 객체: date=그 일이 일어난 날(YYYY-MM-DD, 반드시 그 주 월~일 안), title=20자 안팎 제목, detail=한 문장(80자 안팎, 경제에 미친 영향을 숫자·결과로 포함), "
          "category=통화정책(금리 결정·중앙은행)/경제지표(고용·물가·성장률·수출 등 발표)/증시·시장(주가·채권 급등락)/무역·정책(관세·재정·규제)/기업·실적(대형 실적·인수·상장)/원자재·환율(유가·금·환율·소비재 가격)/정치·지정학(경제에 큰 영향을 준 정치·전쟁·분쟁)/기타경제. "
          "그 지역에 경제·시장을 움직인 큰 일이 없었거나 검색해도 확인되지 않으면 date·title·detail 을 빈 문자열로 두세요(그 지역은 건너뜁니다). 지어내지 마세요. "
          "출력은 주마다 week(입력의 월요일 날짜 그대로)와 kr·us·world 객체입니다. 입력의 모든 week 를 한 번씩 반환하세요.")


def monday(d):
    d = datetime.date.fromisoformat(d) if isinstance(d, str) else d
    return d - datetime.timedelta(days=d.weekday())


def week_end(w): return (datetime.date.fromisoformat(w) + datetime.timedelta(days=6)).isoformat()


def cur_week(): return monday(D.today()).isoformat()


def weeks_for(d):
    """날짜 d 가 속한 주와 그 전주(월요일 날짜) -> [전주, 해당 주]."""
    m = monday(d)
    return [(m - datetime.timedelta(days=7)).isoformat(), m.isoformat()]


def pending_weeks(con, weight, limit=PER_RUN):
    """아직 조사하지 않은 지난 주(오늘이 든 주는 제외). weight={주: 그 주를 필요로 하는 표시 수}. 많이 필요한 주부터, 같으면 최근 주부터."""
    done = {r[0] for r in con.execute("SELECT week FROM week_events GROUP BY week HAVING count(*) >= 3")}
    cw = cur_week()
    out = [(w, n) for w, n in weight.items() if w < cw and w not in done]
    out.sort(key=lambda x: (-x[1], -int(x[0].replace("-", ""))))
    return [w for w, _ in out[:limit]]


def task_body(weeks):
    return "\n".join(f"week={w} ({w} ~ {week_end(w)})" for w in weeks)


def apply(con, data):
    """조사 결과를 DB 에 반영한다. 반환: 저장한 큰 일(지역별) 수. 모르는 주·오늘이 든 주는 버리고, 날짜가 그 주 밖이면 그 지역은 '큰 일 없음'으로 둔다."""
    cw, n = cur_week(), 0
    for r in data["weeks"]:
        w = r["week"]
        try:
            if monday(w).isoformat() != w or w >= cw: continue
        except Exception: continue
        end = week_end(w)
        for key, region in REGIONS:
            it = r[key]; title, date = it["title"].strip(), it["date"].strip()
            if not title or not (w <= date <= end): title = date = ""
            con.execute("INSERT OR REPLACE INTO week_events VALUES(?,?,?,?,?,?,?,?)",
                        (w, region, date, title, it["detail"].strip() if title else "", it["category"] if title else "", D.llm_tag(), D.now()))
            n += bool(title)
    con.commit()
    return n


def load(con):
    """페이지용: {주(월요일): {지역: 행}}."""
    out = {}
    for r in con.execute("SELECT * FROM week_events"): out.setdefault(r["week"], {})[r["region"]] = dict(r)
    return out
