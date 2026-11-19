"""실제 시세 수집(키 불필요): Yahoo Finance chart API(주가·지수·환율·금리·원자재·코인), FRED CSV(미국 거시지표·BIS 한국 주택가격),
금융투자협회 FreeSIS(고객예탁금·신용융자 잔고 등 증시 자금).
반환: [(YYYY-MM-DD, 값), ...] 오래된 순. 실패하면 None."""
import csv, datetime, io, json, time, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) yt-watcher-later"}

def _get(url, tries=3, ua=UA):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=ua), timeout=20) as r: return r.read().decode("utf-8")
        except Exception:
            time.sleep(2 * (i + 1))
    return None

def yahoo(symbol):
    t = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=6mo&interval=1d")
    try:
        res = json.loads(t)["chart"]["result"][0]
        ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
        off = res["meta"].get("gmtoffset", 0)
        out = [(datetime.datetime.fromtimestamp(a + off, datetime.timezone.utc).date().isoformat(), c) for a, c in zip(ts, cl) if c is not None]
        return out or None
    except Exception: return None

YOY = {"CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "M2SL", "WALCL", "GDPC1", "INDPRO", "RSAFS"}   # 지수/레벨 -> 전년 대비 %

def fred(series):
    start = (datetime.date.today() - datetime.timedelta(days=900)).isoformat()
    t = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={urllib.parse.quote(series)}&cosd={start}{'&transformation=pc1' if series in YOY else ''}", ua={"User-Agent": "curl/8.5.0"})
    try:
        rows = [(d, float(v)) for d, v in list(csv.reader(io.StringIO(t)))[1:] if v not in ("", ".")]
        return rows or None
    except Exception: return None

ENV_FILE = __import__("pathlib").Path.home() / ".config" / "yt-watcher-later" / "env"

def secret(name):
    """~/.config/yt-watcher-later/env (KEY=값 줄, 권한 600)에서 키를 읽는다. 환경변수가 있으면 그것을 우선. 없으면 None."""
    import os
    if os.environ.get(name): return os.environ[name]
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and not line.lstrip().startswith("#"):
                v = v.strip(); return v[1:-1] if len(v) > 1 and v[0] in "\"'" and v[-1] == v[0] else v
    except Exception: pass
    return None

def ecos(symbol):
    """한국은행 ECOS(인증키 필요: ~/.config/yt-watcher-later/env 의 ECOS_API_KEY). symbol = "통계표/주기/항목1[/항목2..][|옵션...]"
    주기 M(월)·Q(분기)·D(일)·A(연). 옵션: diff = 전기 대비 증감, scale=배율, 예) 901Y062/M/P63AC , 151Y005/M/11100A0|diff|scale=0.001"""
    key = secret("ECOS_API_KEY")
    if not key: return None
    try:
        main, *opts = symbol.split("|"); stat, cyc, *items = main.split("/")
        today = datetime.date.today(); back = today - datetime.timedelta(days=1100 if cyc in ("M", "Q", "A") else 200)
        fmt = {"M": lambda d: d.strftime("%Y%m"), "D": lambda d: d.strftime("%Y%m%d"), "A": lambda d: d.strftime("%Y"),
               "Q": lambda d: f"{d.year}Q{(d.month - 1) // 3 + 1}"}[cyc]
        t = _get(f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/400/{stat}/{cyc}/{fmt(back)}/{fmt(today)}/" + "/".join(items))
        rows = []
        for r in json.loads(t)["StatisticSearch"]["row"]:
            p, v = r["TIME"], r["DATA_VALUE"]
            if v in (None, ""): continue
            d = (f"{p[:4]}-{p[4:6]}-01" if cyc == "M" else f"{p[:4]}-{int(p[5]) * 3 - 2:02d}-01" if cyc == "Q" else f"{p[:4]}-{p[4:6]}-{p[6:8]}" if cyc == "D" else f"{p[:4]}-01-01")
            rows.append((d, float(v)))
        rows.sort()
        for o in opts:
            if o == "diff": rows = [(rows[i][0], rows[i][1] - rows[i - 1][1]) for i in range(1, len(rows))]
            elif o.startswith("scale="): rows = [(d, v * float(o[6:])) for d, v in rows]
        return rows or None
    except Exception: return None

def rone(symbol):
    """한국부동산원 R-ONE OpenAPI(인증키 필요: ~/.config/yt-watcher-later/env 의 RONE_API_KEY).
    symbol = "통계표ID/주기/지역(CLS_ID)/항목(ITM_ID)[|scale=배율]"  주기 MM(월)·WK(주). 예) A_2024_00554/MM/500001/100001 = 전국 아파트 매매거래 호수
    CLS_ID·ITM_ID 로 걸러 마지막 두 쪽(최근 값 수십 개)만 받는다."""
    key = secret("RONE_API_KEY")
    if not key: return None
    try:
        main, *opts = symbol.split("|"); sid, cyc, cls, itm = main.split("/")
        base = f"https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do?KEY={key}&Type=json&STATBL_ID={sid}&DTACYCLE_CD={cyc}&CLS_ID={cls}&ITM_ID={itm}"
        def page(i, size): return json.loads(_get(f"{base}&pIndex={i}&pSize={size}"))["SttsApiTblData"]
        total = page(1, 1)[0]["head"][0]["list_total_count"]; size = 24; last = (total + size - 1) // size
        rows = []
        for i in {last, max(1, last - 1)}: rows += page(i, size)[1]["row"]
        out = {}
        for r in rows:
            if r["DTA_VAL"] is None: continue
            p = str(r["WRTTIME_IDTFR_ID"])
            d = (f"{p[:4]}-{p[4:6]}-01" if cyc == "MM" else str(r.get("WRTTIME_DESC") or "")[:10])
            if len(d) == 10: out[d] = float(r["DTA_VAL"])
        rows = sorted(out.items())
        for o in opts:
            if o.startswith("scale="): rows = [(d, v * float(o[6:])) for d, v in rows]
        return rows or None
    except Exception: return None

def kofia(symbol):
    """금융투자협회 FreeSIS(키 불필요). symbol = "표ID:열[:배율]" — 열은 TMPV2 처럼, 배율은 값에 곱할 수(기본 1e-6 = 백만원 → 조원).
    예) STATSCU0100000060BO:TMPV2 = 투자자예탁금(조원), STATSCU0100000070BO:TMPV2 = 신용거래융자 잔고(조원)."""
    try:
        obj, col, *sc = symbol.split(":"); scale = float(sc[0]) if sc else 1e-6
        end = datetime.date.today(); start = end - datetime.timedelta(days=200)
        body = json.dumps({"dmSearch": {"tmpV40": "1000000", "tmpV41": "1", "tmpV1": "D", "tmpV45": start.strftime("%Y%m%d"),
                                         "tmpV46": end.strftime("%Y%m%d"), "OBJ_NM": obj}}).encode()
        for i in range(3):
            try:
                req = urllib.request.Request("https://freesis.kofia.or.kr/meta/getMetaDataList.do", data=body, headers={
                    "Content-Type": "application/json;charset=UTF-8", "User-Agent": UA["User-Agent"], "Referer": "https://freesis.kofia.or.kr/"})
                with urllib.request.urlopen(req, timeout=20) as r: d = json.loads(r.read().decode("utf-8")); break
            except Exception: d = None; time.sleep(2 * (i + 1))
        rows = [(f"{x['TMPV1'][:4]}-{x['TMPV1'][4:6]}-{x['TMPV1'][6:]}", x[col.upper()] * scale) for x in (d or {}).get("ds1", []) if x.get(col.upper()) is not None]
        return sorted(rows) or None
    except Exception: return None

def multpl(symbol):
    """multpl.com 의 현재 값 한 점(키 불필요). 페이지 메타 설명의 'Current ... is 5.80, a change of -0.02 from previous market close' 를 읽는다.
    과거 시계열은 받을 수 없어 (직전 값, 현재 값) 두 점만 돌려주고, 이력은 우리 DB(indicator_values)에 날마다 쌓인다. symbol = 페이지 이름."""
    import re
    t = _get(f"https://www.multpl.com/{urllib.parse.quote(symbol)}", ua={"User-Agent": "Mozilla/5.0"})
    try:
        x = re.search(r"Current[^\"]*? is (-?[\d.]+), a change of (-?[\d.]+)", t)
        v, ch = float(x.group(1)), float(x.group(2)); today = datetime.date.today()
        return [((today - datetime.timedelta(days=1)).isoformat(), round(v - ch, 4)), (today.isoformat(), v)]
    except Exception: return None

def _krx_session():
    """KRX 정보데이터시스템(data.krx.co.kr) 로그인 세션. KRX_ID/KRX_PW 는 ~/.config/yt-watcher-later/env. 이미 로그인돼 있으면(CD011) 중복 로그인을 허용해 이어 간다."""
    import requests
    i, p = secret("KRX_ID"), secret("KRX_PW")
    if not (i and p): return None
    s = requests.Session(); H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader"}
    base = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
    s.get("https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd", headers=H, timeout=20)
    d = {"mbrNm": "", "telNo": "", "di": "", "certType": "", "mbrId": i, "pw": p}
    j = s.post(base, data=d, headers=H, timeout=20).json()
    if j.get("_error_code") == "CD011": j = s.post(base, data={**d, "skipDup": "Y"}, headers=H, timeout=20).json()
    if j.get("_error_code") != "CD001": return None
    s.headers.update(H); return s

def _krx_rows(s, bld, **kw):
    r = s.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd", data={"bld": f"dbms/MDC/STAT/standard/{bld}", "locale": "ko_KR", "csvxls_isNo": "false", **kw}, timeout=40)
    return r.json().get("output") or []

def _n(x):
    try: return float(str(x).replace(",", ""))
    except Exception: return None

def krx(symbol):
    """KRX 정보데이터시스템(로그인) 에서 시장 단위 값을 계산한다. 최근 영업일 2개 점을 돌려준다.
    symbol = "pbr"     코스피 전체 PBR = Σ시가총액 ÷ Σ순자산(종목 PBR>0 인 것만, 순자산 = 시가총액÷PBR)
             "forn200" 코스피200 외국인 지분율(%) = Σ(외국인 보유주식×종가) ÷ Σ(상장주식×종가)"""
    try:
        s = _krx_session()
        if s is None: return None
        out, d = [], datetime.date.today()
        for _ in range(12):
            if len(out) == 2: break
            day = d.strftime("%Y%m%d"); d -= datetime.timedelta(days=1)
            if symbol == "pbr":
                pb = {r["ISU_SRT_CD"]: _n(r["PBR"]) for r in _krx_rows(s, "MDCSTAT03501", searchType="1", mktId="STK", trdDd=day)}
                if not pb: continue
                cap = {}
                for r in _krx_rows(s, "MDCSTAT03701", searchType="1", mktId="STK", trdDd=day, isuCd=""):      # 시가총액 = 종가 × 상장주식수
                    px, sh = _n(r["TDD_CLSPRC"]), _n(r["LIST_SHRS"])
                    if px and sh: cap[r["ISU_SRT_CD"]] = px * sh
                num = sum(cap[k] for k, v in pb.items() if v and v > 0 and cap.get(k))
                den = sum(cap[k] / v for k, v in pb.items() if v and v > 0 and cap.get(k))
                if den: out.append((f"{day[:4]}-{day[4:6]}-{day[6:]}", round(num / den, 4)))
            elif symbol == "forn200":
                codes = {r["ISU_SRT_CD"] for r in _krx_rows(s, "MDCSTAT00601", indIdx="1", indIdx2="028", trdDd=day, money="1", share="1")}
                if not codes: continue
                a = b = 0.0
                for r in _krx_rows(s, "MDCSTAT03701", searchType="1", mktId="STK", trdDd=day, isuCd=""):
                    if r["ISU_SRT_CD"] in codes:
                        px, sh, fq = _n(r["TDD_CLSPRC"]), _n(r["LIST_SHRS"]), _n(r["FORN_HD_QTY"])
                        if px and sh and fq is not None: a += fq * px; b += sh * px
                if b: out.append((f"{day[:4]}-{day[4:6]}-{day[6:]}", round(a / b * 100, 3)))
        return sorted(out) or None
    except Exception: return None

SOURCES = ("yahoo", "fred", "kofia", "multpl", "ecos", "rone", "krx")           # 자동으로 값을 받을 수 있는 출처

def fetch(source, symbol):
    return yahoo(symbol) if source == "yahoo" else fred(symbol) if source == "fred" else kofia(symbol) if source == "kofia" else multpl(symbol) if source == "multpl" else ecos(symbol) if source == "ecos" else rone(symbol) if source == "rone" else krx(symbol) if source == "krx" else None
