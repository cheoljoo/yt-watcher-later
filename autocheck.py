"""확인 시점이 된 항목을 실제 시세(Yahoo/FRED)로 자동 검증한다.
근거 시계열이 있는 항목만 판정하고(영상 시점 값 / 확인일 값 / 최신 값을 Claude에 제공), 근거가 없으면 pending 으로 두고 사유만 남긴다."""
import datetime
from concurrent.futures import ThreadPoolExecutor
from llm import claude_json
from analyze import UsageLimit
import marketdata, indicators
import db as D

SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "status", "result", "opinion", "reason"], "properties": {
        "id": {"type": "integer"}, "status": {"type": "string", "enum": ["confirmed", "partial", "refuted", "unknown"]},
        "result": {"type": "string"}, "opinion": {"type": "string"}, "reason": {"type": "string"}}}}}}
PROMPT = ("각 항목은 영상이 한 '예상'과, 그 시점들의 '실제 시세'입니다. 실제 숫자만 근거로 예상이 맞았는지 판정하세요. "
          "status: confirmed=예상대로, partial=일부만/방향은 맞고 크기 다름, refuted=반대로 감, unknown=주어진 숫자로 판단 불가(숫자로 검증할 수 없는 예상 포함). "
          "result=실제 결과를 숫자와 날짜로 한 문장, opinion=한 줄 의견, reason=판정 이유. 주어진 숫자 밖의 사실을 지어내지 마세요. id는 입력 그대로.")
CHUNK = 12

def _at(rows, day):
    """day 이하 마지막 관측치 (날짜, 값). 없으면 None."""
    best = None
    for d, v in rows:
        if d <= day: best = (d, v)
        else: break
    return best

def _fmt(p): return "자료 없음" if not p else f"{p[1]:,.2f} ({p[0]})"

def run(con, cfg, limit=60):
    today = D.today()
    due = con.execute("""SELECT c.*, v.processed_date, v.upload_date FROM checks c JOIN videos v ON v.id=c.video_id
                         WHERE c.status='pending' AND c.check_date<=? ORDER BY c.check_date LIMIT ?""", (today, limit)).fetchall()
    if not due: return
    print(f"[자동 확인] 확인 시점 도래 {len(due)}건", flush=True)
    # 지표 목록에 없는 확인 대상은 비활성(대시보드 제외) 지표로 만들어 출처를 매핑한다
    for c in due:
        con.execute("INSERT OR IGNORE INTO indicators(name,category,first_seen_at,enriched_at,active) VALUES(?,?,?,?,0)", (c["target"], "확인대상", D.now(), D.now()))
    con.commit()
    try: indicators.map_sources(con, cfg)
    except UsageLimit: print("   사용량 한도 — 출처 매핑 생략", flush=True)
    ind_of = {}
    for c in due:
        i = con.execute("SELECT * FROM indicators WHERE name=?", (c["target"],)).fetchone()
        if i and i["alias_of"]: i = con.execute("SELECT * FROM indicators WHERE id=?", (i["alias_of"],)).fetchone()
        if i and i["source"] in ("yahoo", "fred") and i["symbol"]: ind_of[c["id"]] = i
    syms = {(i["source"], i["symbol"]) for i in ind_of.values()}
    with ThreadPoolExecutor(5) as ex: data = dict(zip(syms, ex.map(lambda s: marketdata.fetch(*s), syms)))
    items = []
    for c in due:
        i = ind_of.get(c["id"]); rows = i and data.get((i["source"], i["symbol"]))
        if not rows:
            con.execute("UPDATE checks SET reason=? WHERE id=?", ("자동 확인 불가: 이 항목에 해당하는 시세 자료가 없어 수동 확인 필요", c["id"])); continue
        vday = c["processed_date"] or c["upload_date"] or c["check_date"]
        items.append((c["id"], f"id={c['id']} | 대상 {c['target']} ({i['symbol']}) | 확인할 것: {c['what_to_check']} | 영상의 예상: {c['expectation']} | "
                               f"영상 시점 값 {_fmt(_at(rows, vday))} | 확인일 값 {_fmt(_at(rows, c['check_date']))} | 최신 값 {_fmt(rows[-1])}"))
    con.commit()
    if not items: print("   시세 근거가 있는 항목 없음(수동 확인 필요)", flush=True); return
    def one(chunk):
        try: return claude_json(PROMPT, "\n".join(t for _, t in chunk), SCHEMA, cfg["model"])["items"]
        except UsageLimit: raise
        except Exception as ex: print(f"   자동 확인 실패(다음 실행에 재시도): {str(ex)[:100]}", flush=True); return []
    n = 0
    try:
        with ThreadPoolExecutor(2) as ex:
            for res in ex.map(one, [items[k:k + CHUNK] for k in range(0, len(items), CHUNK)]):
                for r in res:
                    con.execute("UPDATE checks SET status=?, checked_at=?, result=?, opinion=?, reason=? WHERE id=? AND status='pending'",
                                (r["status"], today, r["result"], r["opinion"], "[자동] " + r["reason"], r["id"])); n += 1
    except UsageLimit: print("   사용량 한도 — 나머지는 다음 실행으로", flush=True)
    con.commit(); print(f"   자동 판정 {n}건 (근거 있는 {len(items)}건 중)", flush=True)
