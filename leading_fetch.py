"""선행지수 페이지(leading.py)용 장기 월별 시계열 수집 — 웹 호출은 여기서만 한다.

  uv run leading_fetch.py            # 전부 받아 DB leading_series / leading_meta 에 저장 (실패한 항목은 이전 값 유지)
  uv run leading_fetch.py kr_cli     # 하나만

출처: ECOS(한국은행·통계청), FRED(OECD 선행지수·금리·유가·소비자심리), Yahoo(코스피·S&P500·환율).
일별 값은 월평균, 주가·환율은 월말(마지막) 값으로 월 단위로 맞춘다. 파생 계열(전년 대비 %, 3개월 평균)도 같이 저장한다.
"""
import csv, datetime, io, json, sys, time, urllib.parse
import db as D
import marketdata as M

DDL = """CREATE TABLE IF NOT EXISTS leading_series(sid TEXT, date TEXT, value REAL, PRIMARY KEY(sid, date));
CREATE TABLE IF NOT EXISTS leading_meta(sid TEXT PRIMARY KEY, name TEXT, unit TEXT, source TEXT, symbol TEXT, n INTEGER, first TEXT, last TEXT, fetched_at TEXT);"""

# (sid, 이름, 단위, 출처, 심볼, 일별→월 변환 avg|last)
RAW = [
    ("kr_cli", "한국 선행지수 순환변동치", "pt", "ecos", "901Y067/M/I16E", "last"),
    ("kr_cci", "한국 동행지수 순환변동치", "pt", "ecos", "901Y067/M/I16D", "last"),
    ("oecd_kr_cli", "OECD 한국 경기선행지수", "pt", "fred", "KORLOLITOAASTSAM", "last"),
    ("oecd_us_cli", "OECD 미국 경기선행지수", "pt", "fred", "USALOLITOAASTSAM", "last"),
    ("t10y3m", "미국 장단기 금리차(10년-3개월)", "%p", "fred", "T10Y3M", "avg"),
    ("t10y2y", "미국 장단기 금리차(10년-2년)", "%p", "fred", "T10Y2Y", "avg"),
    ("hy", "미국 하이일드 신용스프레드", "%p", "fred", "BAMLH0A0HYM2", "avg"),
    ("dubai", "두바이유 가격", "달러/배럴", "fred", "POILDUBUSDM", "last"),
    ("kr_cpi", "한국 소비자물가지수", "2020=100", "ecos", "901Y009/M/0", "last"),
    ("us_cpi", "미국 소비자물가지수", "지수", "fred", "CPIAUCSL", "last"),
    ("umcsent", "미국 소비자심리(미시간대)", "pt", "fred", "UMCSENT", "last"),
    ("permit", "미국 건축허가 건수", "천 호", "fred", "PERMIT", "last"),
    ("usrec", "미국 경기침체(NBER) 구간", "0/1", "fred", "USREC", "last"),
    ("us_ff", "미국 연방기금금리", "%", "fred", "FEDFUNDS", "last"),
    ("kospi", "코스피", "pt", "yahoo", "^KS11", "last"),
    ("spx", "S&P500", "pt", "yahoo", "^GSPC", "last"),
    ("usdkrw", "원/달러 환율", "원", "yahoo", "KRW=X", "last"),
    ("copper", "구리 선물", "달러/파운드", "yahoo", "HG=F", "last"),
    ("kr_exp", "한국 통관 수출금액(월)", "억달러", "ecos", "901Y118/M/T002|scale=0.00001", "last"),
    ("kr_news", "한은 뉴스심리지수", "pt", "ecos", "523Y001/M/A001", "last"),
    ("kr_esi", "한국 경제심리지수(순환변동치)", "pt", "ecos", "513Y001/M/E2000", "last"),
    ("apt_seoul", "서울 아파트 매매가격지수", "지수", "ecos", "901Y062/M/P63ACA", "last"),
    ("apt_all", "전국 아파트 매매가격지수", "지수", "ecos", "901Y062/M/P63AC", "last"),
    ("kr_rate", "한국은행 기준금리", "%", "ecos", "722Y001/M/0101000", "last"),
    ("kr_bond10", "국고채 10년 금리", "%", "ecos", "721Y001/M/5050000", "avg"),
    ("kr_bond1", "국고채 1년 금리", "%", "ecos", "721Y001/M/5030000", "avg"),
]
# 파생: (sid, 이름, 단위, 기반 sid, 방법)   yoy = 12개월 전 대비 %, ma3 = 3개월 이동평균
DERIVED = [
    ("kr_cpi_yoy", "한국 소비자물가 상승률(전년 대비)", "%", "kr_cpi", "yoy"),
    ("us_cpi_yoy", "미국 소비자물가 상승률(전년 대비)", "%", "us_cpi", "yoy"),
    ("kospi_yoy", "코스피 전년 대비", "%", "kospi", "yoy"),
    ("spx_yoy", "S&P500 전년 대비", "%", "spx", "yoy"),
    ("dubai_yoy", "두바이유 전년 대비", "%", "dubai", "yoy"),
    ("apt_seoul_yoy", "서울 아파트 매매가 전년 대비", "%", "apt_seoul", "yoy"),
    ("apt_all_yoy", "전국 아파트 매매가 전년 대비", "%", "apt_all", "yoy"),
    ("kr_exp_ma3", "한국 수출금액 3개월 평균", "억달러", "kr_exp", "ma3"),
    ("kr_exp_yoy", "한국 수출금액 전년 대비", "%", "kr_exp", "yoy"),
    ("kr_news_ma3", "한은 뉴스심리지수 3개월 평균", "pt", "kr_news", "ma3"),
    ("permit_yoy", "미국 건축허가 전년 대비", "%", "permit", "yoy"),
    ("kr_curve", "한국 장단기 금리차(10년-1년)", "%p", "kr_bond10-kr_bond1", "spread"),
]


def _month(d): return d[:7] + "-01"


def monthly(rows, how):
    """(날짜, 값) 목록 → {YYYY-MM-01: 값}. how: avg=월평균, last=월 마지막 값."""
    by = {}
    for d, v in sorted(rows): by.setdefault(_month(d), []).append(v)
    return {m: (sum(vs) / len(vs) if how == "avg" else vs[-1]) for m, vs in by.items()}


def _fred(series):
    t = M._get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series)}&cosd=1990-01-01", ua={"User-Agent": "curl/8.5.0"})
    return [(d, float(v)) for d, v in list(csv.reader(io.StringIO(t)))[1:] if v not in ("", ".")]


def _yahoo(sym):
    t = M._get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1=946684800&period2={int(time.time()) + 172800}&interval=1mo")     # range=max 는 옛 구간이 분기 단위로 성겨서 시작·끝을 직접 지정
    res = json.loads(t)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    return [(datetime.datetime.fromtimestamp(a + off, datetime.timezone.utc).date().isoformat(), c)
            for a, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]


def _ecos(symbol):
    key = M.secret("ECOS_API_KEY")
    if not key: raise RuntimeError("ECOS_API_KEY 없음")
    main, *opts = symbol.split("|"); stat, cyc, item = main.split("/")
    t = M._get(f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat}/{cyc}/199001/202612/{item}")
    rows = []
    for r in json.loads(t)["StatisticSearch"]["row"]:
        if r["DATA_VALUE"] in (None, ""): continue
        p = r["TIME"]; rows.append((f"{p[:4]}-{p[4:6]}-01", float(r["DATA_VALUE"])))
    for o in opts:
        if o.startswith("scale="): rows = [(d, v * float(o[6:])) for d, v in rows]
    return rows


def fetch_raw(src, symbol):
    return {"fred": _fred, "yahoo": _yahoo, "ecos": _ecos}[src](symbol)


def derive(series, how):
    ms = sorted(series); out = {}
    for i, m in enumerate(ms):
        if how == "yoy":
            y, mo = int(m[:4]), m[5:7]; prev = f"{y - 1}-{mo}-01"
            if prev in series and series[prev]: out[m] = (series[m] / series[prev] - 1) * 100
        elif how == "ma3" and i >= 2:
            out[m] = sum(series[x] for x in ms[i - 2:i + 1]) / 3
    return out


def save(con, sid, name, unit, src, symbol, data):
    con.execute("DELETE FROM leading_series WHERE sid=?", (sid,))
    con.executemany("INSERT INTO leading_series VALUES(?,?,?)", [(sid, d, v) for d, v in sorted(data.items())])
    ks = sorted(data)
    con.execute("INSERT OR REPLACE INTO leading_meta VALUES(?,?,?,?,?,?,?,?,?)", (sid, name, unit, src, symbol, len(ks), ks[0], ks[-1], D.now()))


def load(con, sid):
    return {r[0]: r[1] for r in con.execute("SELECT date, value FROM leading_series WHERE sid=? ORDER BY date", (sid,))}


def run(only=None):
    con = D.connect(); con.executescript(DDL)
    for sid, name, unit, src, symbol, how in RAW:
        if only and sid != only: continue
        try:
            data = monthly(fetch_raw(src, symbol), how)
            if len(data) < 12: raise RuntimeError(f"값이 {len(data)}개뿐")
            save(con, sid, name, unit, src, symbol, data); con.commit()
            ks = sorted(data); print(f"{sid:12s} {len(data):4d}개  {ks[0][:7]} ~ {ks[-1][:7]}  마지막 {data[ks[-1]]:.3f}")
        except Exception as ex:
            print(f"{sid:12s} 실패: {ex} (이전 값 유지)")
    for sid, name, unit, base, how in DERIVED:
        if only and only != sid and only not in base.split("-"): continue
        if how == "spread":
            a_, b_ = (load(con, x) for x in base.split("-"))
            data = {m: a_[m] - b_[m] for m in a_ if m in b_}
        else:
            b = load(con, base)
            if not b: continue
            data = derive(b, how)
        if data: save(con, sid, name, unit, "derived", f"{base}|{how}", data)
    con.commit()


def run_if_stale():
    """오늘 이미 받았으면 건너뛴다(cron 하루 여러 번 실행 대비). 실패해도 호출한 쪽 실행에는 영향 없다."""
    con = D.connect(); con.executescript(DDL)
    r = con.execute("SELECT max(fetched_at) FROM leading_meta").fetchone()[0]
    if r and r[:10] == D.today(): return False
    run(); return True


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
