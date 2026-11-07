"""실제 시세 수집(키 불필요): Yahoo Finance chart API(주가·지수·환율·금리·원자재·코인), FRED CSV(미국 거시지표).
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

def fetch(source, symbol):
    return yahoo(symbol) if source == "yahoo" else fred(symbol) if source == "fred" else None
