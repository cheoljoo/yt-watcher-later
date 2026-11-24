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

def yahoo(symbol, back=None):
    """back: 며칠 전부터 받을지(1회성 이력 채우기용). 없으면 최근 6개월."""
    rng = "range=6mo" if not back else f"period1={int(time.time()) - back * 86400}&period2={int(time.time()) + 172800}"
    t = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{rng}&interval=1d")
    try:
        res = json.loads(t)["chart"]["result"][0]
        ts, cl = res["timestamp"], res["indicators"]["quote"][0]["close"]
        off = res["meta"].get("gmtoffset", 0)
        out = [(datetime.datetime.fromtimestamp(a + off, datetime.timezone.utc).date().isoformat(), c) for a, c in zip(ts, cl) if c is not None]
        return out or None
    except Exception: return None

YOY = {"CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "M2SL", "WALCL", "GDPC1", "INDPRO", "RSAFS"}   # 지수/레벨 -> 전년 대비 %

def fred(series, back=None):
    start = (datetime.date.today() - datetime.timedelta(days=max(900, back or 0))).isoformat()
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

def ecos(symbol, back=None):
    """한국은행 ECOS(인증키 필요: ~/.config/yt-watcher-later/env 의 ECOS_API_KEY). symbol = "통계표/주기/항목1[/항목2..][|옵션...]"
    주기 M(월)·Q(분기)·D(일)·A(연). 옵션: diff = 전기 대비 증감, ma3 = 3기간 이동평균, scale=배율, minus=항목코드(같은 통계표·주기의 다른 항목을 날짜별로 뺌: 금리 스프레드),
    예) 901Y062/M/P63AC , 151Y005/M/11100A0|diff|scale=0.001 , 817Y002/D/010300000|minus=010200000 (회사채 AA- 3년 − 국고채 3년)"""
    key = secret("ECOS_API_KEY")
    if not key: return None
    try:
        main, *opts = symbol.split("|"); stat, cyc, *items = main.split("/")
        today = datetime.date.today(); back_d = today - datetime.timedelta(days=max(back or 0, 1100 if cyc in ("M", "Q", "A") else 200))
        fmt = {"M": lambda d: d.strftime("%Y%m"), "D": lambda d: d.strftime("%Y%m%d"), "A": lambda d: d.strftime("%Y"),
               "Q": lambda d: f"{d.year}Q{(d.month - 1) // 3 + 1}"}[cyc]
        def fetch_rows(its):
            t = _get(f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10000/{stat}/{cyc}/{fmt(back_d)}/{fmt(today)}/" + "/".join(its))
            rows = []
            for r in json.loads(t)["StatisticSearch"]["row"]:
                p, v = r["TIME"], r["DATA_VALUE"]
                if v in (None, ""): continue
                d = (f"{p[:4]}-{p[4:6]}-01" if cyc == "M" else f"{p[:4]}-{int(p[5]) * 3 - 2:02d}-01" if cyc == "Q" else f"{p[:4]}-{p[4:6]}-{p[6:8]}" if cyc == "D" else f"{p[:4]}-01-01")
                rows.append((d, float(v)))
            rows.sort()
            return rows
        rows = fetch_rows(items)
        for o in opts:
            if o.startswith("minus="):
                other = dict(fetch_rows([o[6:]])); rows = [(d, v - other[d]) for d, v in rows if d in other]
        for o in opts:
            if o == "diff": rows = [(rows[i][0], rows[i][1] - rows[i - 1][1]) for i in range(1, len(rows))]
            elif o.startswith("scale="): rows = [(d, v * float(o[6:])) for d, v in rows]
            elif o == "ma3": rows = [(rows[i][0], sum(v for _, v in rows[i - 2:i + 1]) / 3) for i in range(2, len(rows))]
        return rows or None
    except Exception: return None

# ── 빅테크 재무(SEC EDGAR XBRL, 키 불필요) ────────────────────────────────
SEC_CIK = {"MSFT": "0000789019", "GOOGL": "0001652044", "AMZN": "0001018724", "META": "0001326801"}      # 분기 말이 3·6·9·12월이라 달력 분기로 합산할 수 있는 4사
SEC_TAGS = {"OCF": ["NetCashProvidedByUsedInOperatingActivities"],
            "CAPEX": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
            "DEBT": ["LongTermDebtNoncurrent", "LongTermDebt"]}
_SEC_CACHE = {}

def _sec_facts(cik):
    if cik not in _SEC_CACHE:
        _SEC_CACHE[cik] = json.loads(_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", ua={"User-Agent": "yt-watcher-later personal research"}))["facts"]["us-gaap"]
    return _SEC_CACHE[cik]

def _quarters(units):
    """공시(10-Q·10-K)의 기간 값 -> {분기말: 그 분기만의 값}. 현금흐름은 누적(3·6·9·12개월)으로 공시되므로 직전 누적을 뺀다."""
    best = {}
    for u in units:
        if u.get("form") not in ("10-Q", "10-K") or "start" not in u: continue
        k = (u["start"], u["end"])
        if k not in best or u["filed"] > best[k]["filed"]: best[k] = u            # 정정 공시는 나중 것을 쓴다
    out = {}
    for (st, en), u in sorted(best.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        days = (datetime.date.fromisoformat(en) - datetime.date.fromisoformat(st)).days
        if days < 120: out.setdefault(en, u["val"]); continue                       # 3개월 값
        prev = [(e2, v["val"]) for (s2, e2), v in best.items() if s2 == st and e2 < en]
        if prev:
            pe, pv = max(prev)
            if 70 <= (datetime.date.fromisoformat(en) - datetime.date.fromisoformat(pe)).days <= 110: out.setdefault(en, u["val"] - pv)
    return out

def _instants(units):
    best = {}
    for u in units:
        if u.get("form") in ("10-Q", "10-K") and "start" not in u:
            if u["end"] not in best or u["filed"] > best[u["end"]]["filed"]: best[u["end"]] = u
    return {e: u["val"] for e, u in best.items()}

def sec(symbol, back=None):
    """symbol = "BIGTECH:OCF|CAPEX|FCF|DEBT" — 마이크로소프트·알파벳·아마존·메타 4사 합산(분기, 십억 달러). FCF = 영업현금흐름 − 설비투자. DEBT = 분기 말 장기부채 잔액."""
    try:
        grp, kind = symbol.split(":")
        per = {}
        for tk, cik in SEC_CIK.items():
            facts = _sec_facts(cik)
            def merged(k):
                out = {}
                for tag in SEC_TAGS[k]:                                      # 태그가 회사·연도마다 달라 다음 태그로 메운다
                    if tag in facts:
                        u = facts[tag]["units"]["USD"]
                        for e, v in (_instants(u) if k == "DEBT" else _quarters(u)).items(): out.setdefault(e, v)
                return out
            if kind == "FCF":
                o, c = merged("OCF"), merged("CAPEX")
                per[tk] = {e: o[e] - c[e] for e in o if e in c}
            else: per[tk] = merged(kind)
        dates = set.intersection(*[set(v) for v in per.values()])
        cut = (datetime.date.today() - datetime.timedelta(days=max(back or 0, 1500))).isoformat()
        rows = sorted((d, sum(per[t][d] for t in per) / 1e9) for d in dates if d >= cut)
        return rows or None
    except Exception: return None

def rone(symbol, back=None):
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
        npg = 2 if not back else max(2, back // (7 if cyc == "WK" else 30) // size + 2)       # 이력 채우기는 필요한 만큼 더 뒤 쪽까지
        rows = []
        for i in {max(1, last - k) for k in range(npg)}: rows += page(i, size)[1]["row"]
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

def kofia(symbol, back=None):
    """금융투자협회 FreeSIS(키 불필요). symbol = "표ID:열[:배율]" — 열은 TMPV2 처럼, 배율은 값에 곱할 수(기본 1e-6 = 백만원 → 조원).
    예) STATSCU0100000060BO:TMPV2 = 투자자예탁금(조원), STATSCU0100000070BO:TMPV2 = 신용거래융자 잔고(조원)."""
    try:
        obj, col, *sc = symbol.split(":"); scale = float(sc[0]) if sc else 1e-6
        end = datetime.date.today(); start = end - datetime.timedelta(days=max(200, back or 0))
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

def multpl_history(symbol):
    """multpl.com 월별 표(…/table/by-month)에서 과거 월별 값. 이력 채우기 전용."""
    import re
    t = _get(f"https://www.multpl.com/{urllib.parse.quote(symbol)}/table/by-month", ua={"User-Agent": "Mozilla/5.0"})
    try:
        out = []
        for d, v in re.findall(r"<td[^>]*>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</td>\s*<td[^>]*>[^\d\-<]*(?:<[^>]*>[^\d\-<]*)*([-\d.,]+)", t):
            out.append((datetime.datetime.strptime(d, "%b %d, %Y").date().isoformat(), float(v.replace(",", ""))))
        return sorted(out) or None
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

def _krx_point(s, symbol, day):
    """한 영업일 day(YYYYMMDD)의 시장 값. 휴장·자료 없음이면 None."""
    if symbol == "pbr":
        pb = {r["ISU_SRT_CD"]: _n(r["PBR"]) for r in _krx_rows(s, "MDCSTAT03501", searchType="1", mktId="STK", trdDd=day)}
        if not pb: return None
        cap = {}
        for r in _krx_rows(s, "MDCSTAT03701", searchType="1", mktId="STK", trdDd=day, isuCd=""):      # 시가총액 = 종가 × 상장주식수
            px, sh = _n(r["TDD_CLSPRC"]), _n(r["LIST_SHRS"])
            if px and sh: cap[r["ISU_SRT_CD"]] = px * sh
        num = sum(cap[k] for k, v in pb.items() if v and v > 0 and cap.get(k))
        den = sum(cap[k] / v for k, v in pb.items() if v and v > 0 and cap.get(k))
        return (f"{day[:4]}-{day[4:6]}-{day[6:]}", round(num / den, 4)) if den else None
    if symbol == "forn200":
        codes = {r["ISU_SRT_CD"] for r in _krx_rows(s, "MDCSTAT00601", indIdx="1", indIdx2="028", trdDd=day, money="1", share="1")}
        if not codes: return None
        a = b = 0.0
        for r in _krx_rows(s, "MDCSTAT03701", searchType="1", mktId="STK", trdDd=day, isuCd=""):
            if r["ISU_SRT_CD"] in codes:
                px, sh, fq = _n(r["TDD_CLSPRC"]), _n(r["LIST_SHRS"]), _n(r["FORN_HD_QTY"])
                if px and sh and fq is not None: a += fq * px; b += sh * px
        return (f"{day[:4]}-{day[4:6]}-{day[6:]}", round(a / b * 100, 3)) if b else None
    return None

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
            p = _krx_point(s, symbol, d.strftime("%Y%m%d")); d -= datetime.timedelta(days=1)
            if p: out.append(p)
        return sorted(out) or None
    except Exception: return None

def krx_history(symbol, months):
    """이력 채우기 전용: 최근 months 개월의 '월말(마지막 영업일)' 값. 하루 값마다 수천 종목을 받아야 해서 일별 대신 월말만 받는다."""
    try:
        s = _krx_session()
        if s is None: return None
        out, today = [], datetime.date.today()
        for k in range(months):
            y, m = divmod(today.year * 12 + today.month - 1 - k, 12); m += 1
            d = min(datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1), today)       # 그 달 말일(이번 달이면 오늘)
            for _ in range(7):                                    # 말일이 휴장이면 직전 영업일
                p = _krx_point(s, symbol, d.strftime("%Y%m%d")); d -= datetime.timedelta(days=1)
                if p: out.append(p); break
        return sorted(out) or None
    except Exception: return None

SOURCES = ("yahoo", "fred", "kofia", "multpl", "ecos", "rone", "krx", "sec")           # 자동으로 값을 받을 수 있는 출처

def fetch(source, symbol, back=None):
    """back: 며칠 전까지의 이력을 받을지(1회성 이력 채우기). 없으면 평소처럼 최근 값만."""
    if source == "yahoo": return yahoo(symbol, back)
    if source == "fred": return fred(symbol, back)
    if source == "kofia": return kofia(symbol, back)
    if source == "ecos": return ecos(symbol, back)
    if source == "rone": return rone(symbol, back)
    if source == "sec": return sec(symbol, back)
    if source == "multpl": return (multpl_history(symbol) if back else None) or multpl(symbol)
    if source == "krx": return (krx_history(symbol, back // 30) if back else None) or krx(symbol)
    return None
