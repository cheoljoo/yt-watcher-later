"""확인 시점이 된 항목을 실제 시세(Yahoo/FRED)로 자동 검증한다.
근거 시계열이 있는 항목만 판정하고(등록/영상 시점 값 / 확인일 값 / 최신 값을 Claude에 제공), 근거가 없으면 pending 으로 두고 사유만 남긴다."""
import datetime
from concurrent.futures import ThreadPoolExecutor
from llm import claude_json
from analyze import UsageLimit
import marketdata, indicators
import db as D

SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "status", "result", "since_upload", "opinion", "reason"], "properties": {
        "id": {"type": "integer"}, "status": {"type": "string", "enum": ["confirmed", "partial", "refuted", "unknown"]},
        "result": {"type": "string"}, "since_upload": {"type": "string"}, "opinion": {"type": "string"}, "reason": {"type": "string"}}}}}}
PROMPT = ("확인일이 어제까지인 항목입니다. 각 항목은 영상이 한 '예상'과, 영상 업로드일·확인일·(있으면) 그 시점들의 실제 시세입니다. "
          "입력의 모든 id 에 대해 반드시 판정하세요(빠뜨리지 마세요). "
          "★웹 검색 필수★ 당신의 기억·학습 지식은 낡았을 수 있고 오늘(입력의 '오늘' 날짜) 이전에 일어난 일은 모를 수 있습니다. "
          "그러므로 모든 항목에서 판정 전에 반드시 웹 검색(WebSearch/search_web 등)으로 '확인일~오늘' 사이의 최신 보도·공시·시세를 찾아 근거로 쓰세요. "
          "시세 숫자가 입력에 있어도 사건·일정·공시 항목은 검색으로 교차 확인합니다. 검색어에는 대상 이름과 연·월(예: 2026년 11월)을 넣고, 필요하면 영문 이름·티커로도 검색하세요. "
          "기억으로 '아직 ~하지 않았다/예정이다/없다'라고 단정하지 마세요(이미 일어난 일일 수 있음). 검색 결과가 서로 다르면 가장 최근 날짜·1차 출처(공시·거래소·공식 발표·주요 통신사)를 우선합니다. "
          "검색 도구를 쓸 수 없거나 검색해도 근거를 찾지 못하면 지어내지 말고 unknown 으로 하고, result 에 '무엇을 어디서 확인하면 되는지'를 쓰세요. "
          "status: confirmed=예상대로, partial=일부만/방향은 맞고 크기 다름, refuted=반대로 감, unknown=검색해도 확실히 알 수 없음. "
          "result=확인일(또는 가장 최근) 시점의 실제 결과를 숫자·날짜와 함께 한 문장. 가격·주가·공모가 같은 수치는 검색에서 확인한 값만 쓰고, 오늘 기준 최신 상황이 확인일과 다르면 '오늘 기준 …'을 덧붙이세요. "
          "since_upload=영상 업로드 시점부터 확인일(그리고 오늘)까지 상황이 어떻게 변했는지(업로드 때는 어땠고 이후 어떻게 되었는지, 숫자가 있으면 숫자로) 1~2문장. "
          "opinion=예상이 맞았는지에 따라 입력의 '맞을 때/틀릴 때' 행동 중 해당하는 쪽을 골라 지금 어떻게 해야 하는지 한 줄(해당 정보가 없으면 스스로 제안). "
          "reason=판정 이유와 근거 출처(매체/기관 이름과 기사 날짜). 검색에서 확인하지 않은 사실은 쓰지 마세요. id는 입력 그대로.")
FILL_SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["id", "if_right", "if_wrong"], "properties": {
        "id": {"type": "integer"}, "if_right": {"type": "string"}, "if_wrong": {"type": "string"}}}}}}
FILL_PROMPT = ("각 항목은 영상이 한 '예상'입니다. 예상이 맞았을 때(if_right)와 틀렸을 때(if_wrong) 시청자가 각각 어떻게 해야 하는지 "
               "구체적인 행동·판단으로 한두 문장씩 쓰세요(보유 유지/비중 조절/계획 수정/재검토 등). 투자 권유가 아니라 판단 기준으로. 입력에 없는 사실은 지어내지 말고 id는 입력 그대로.")
FILL_PER_RUN = 100       # 예전에 등록돼 if_right/if_wrong 이 없는 대기 항목을 한 번 실행에 채우는 최대 개수

CHUNK = 6            # 항목마다 웹 검색을 하므로 한 번에 보내는 수를 줄인다
CHECK_PER_RUN = 60   # 한 번 실행에서 판정하는 최대 항목 수(오래된 확인일부터)

def _at(rows, day):
    """day 이하 마지막 관측치 (날짜, 값). 없으면 None."""
    best = None
    for d, v in rows:
        if d <= day: best = (d, v)
        else: break
    return best

def _fmt(p): return "자료 없음" if not p else f"{p[1]:,.2f} ({p[0]})"

def due_checks(con, limit=60):
    """확인일이 어제까지(오늘 이전)인 미확인 항목. 새벽에 돌리므로 오늘 날짜 항목은 다음 날 확인한다."""
    return con.execute("""SELECT c.*, v.processed_date, v.upload_date FROM checks c LEFT JOIN videos v ON v.id=c.video_id
                          WHERE c.status='pending' AND c.check_date<? ORDER BY c.check_date LIMIT ?""", (D.today(), limit)).fetchall()

def prepare(con, due):
    """(코드) 확인 대상이 지표 목록에 없으면 비활성 지표로 등록(출처 매핑 대상이 되게)."""
    for c in due:
        con.execute("INSERT OR IGNORE INTO indicators(name,category,first_seen_at,enriched_at,active) VALUES(?,?,?,?,0)", (c["target"], "확인대상", D.now(), D.now()))
    con.commit()

def build_items(con, due):
    """(코드) 확인일이 지난 모든 항목 -> [(check_id, 입력줄)]. 시세 자료가 있으면 업로드 시점/확인일/최신 값을 넣고, 없으면 '없음'으로 표시한다."""
    ind_of = {}
    for c in due:
        i = con.execute("SELECT * FROM indicators WHERE name=?", (c["target"],)).fetchone()
        if i and i["alias_of"]: i = con.execute("SELECT * FROM indicators WHERE id=?", (i["alias_of"],)).fetchone()
        if i and i["source"] in marketdata.SOURCES and i["symbol"]: ind_of[c["id"]] = i
    syms = {(i["source"], i["symbol"]) for i in ind_of.values()}
    with ThreadPoolExecutor(5) as ex: data = dict(zip(syms, ex.map(lambda s: marketdata.fetch(*s), syms)))
    items, today = [], D.today()
    for c in due:
        i = ind_of.get(c["id"]); rows = i and data.get((i["source"], i["symbol"]))
        up = c["upload_date"] or c["processed_date"] or (c["created_at"] or c["check_date"])[:10]
        try: gap = f"업로드 후 {(datetime.date.fromisoformat(c['check_date']) - datetime.date.fromisoformat(up)).days}일째가 확인일"
        except Exception: gap = ""
        line = (f"id={c['id']} | 대상 {c['target']} | 확인할 것: {c['what_to_check']} | 영상의 예상: {c['expectation']}"
                f"{(' | 예상 근거: ' + c['rationale']) if c['rationale'] else ''}"
                f"{(' | 예상이 맞을 때: ' + c['if_right']) if c['if_right'] else ''}{(' | 예상이 틀릴 때: ' + c['if_wrong']) if c['if_wrong'] else ''}"
                f" | 영상 업로드일 {up} | 확인일 {c['check_date']} ({gap}) | 오늘 {today}")
        if rows:
            line += f" | 시세 {i['symbol']}: 업로드 시점 값 {_fmt(_at(rows, up))} / 확인일 값 {_fmt(_at(rows, c['check_date']))} / 최신 값 {_fmt(rows[-1])}"
        else:
            line += " | 시세 자료: 없음(자동 조회 불가 — 웹 검색으로 최신 사실을 찾아 판정, 근거를 못 찾으면 unknown)"
        items.append((c["id"], line))
    return items

def fill_candidates(con, limit=FILL_PER_RUN):
    """if_right/if_wrong 이 비어 있는 대기 항목(가까운 확인일부터)."""
    return con.execute("""SELECT c.*, v.title FROM checks c LEFT JOIN videos v ON v.id=c.video_id
                          WHERE c.status='pending' AND (c.if_right IS NULL OR c.if_wrong IS NULL) ORDER BY c.check_date LIMIT ?""", (limit,)).fetchall()

def fill_line(c):
    return f"id={c['id']} | 영상 {(c['title'] or '')[:60]} | 대상 {c['target']} | 확인할 것: {c['what_to_check']} | 예상: {c['expectation']}" + (f" | 근거: {c['rationale']}" if c["rationale"] else "") + f" | 확인일 {c['check_date']}"

def apply_fill(con, results):
    n = 0
    for r in results:
        con.execute("UPDATE checks SET if_right=?, if_wrong=? WHERE id=?", (r["if_right"], r["if_wrong"], r["id"])); n += 1
    con.commit()
    return n

def apply(con, results):
    n = 0
    for r in results:
        con.execute("UPDATE checks SET status=?, checked_at=?, result=?, since_upload=?, opinion=?, reason=? WHERE id=? AND status='pending'",
                    (r["status"], D.today(), r["result"], r["since_upload"], r["opinion"], "[자동] " + r["reason"], r["id"])); n += 1
    con.commit()
    return n

def run(con, cfg, limit=CHECK_PER_RUN):
    due = due_checks(con, limit)
    if not due: return
    print(f"[자동 확인] 확인 시점 도래 {len(due)}건", flush=True)
    prepare(con, due)
    try: indicators.map_sources(con, cfg)
    except UsageLimit: print("   사용량 한도 — 출처 매핑 생략", flush=True)
    items = build_items(con, due)
    def one(chunk):
        try: return claude_json(PROMPT, "\n".join(t for _, t in chunk), SCHEMA, cfg["model"], web=True)["items"]
        except UsageLimit: raise
        except Exception as ex: print(f"   자동 확인 실패(다음 실행에 재시도): {str(ex)[:100]}", flush=True); return []
    n = 0
    try:
        with ThreadPoolExecutor(2) as ex:
            for res in ex.map(one, [items[k:k + CHUNK] for k in range(0, len(items), CHUNK)]): n += apply(con, res)
    except UsageLimit: print("   사용량 한도 — 나머지는 다음 실행으로", flush=True)
    print(f"   자동 판정 {n}건 ({len(items)}건 중)", flush=True)
    fill = fill_candidates(con)
    for k in range(0, len(fill), 25):
        try: apply_fill(con, claude_json(FILL_PROMPT, "\n".join(fill_line(c) for c in fill[k:k + 25]), FILL_SCHEMA, cfg["model"])["items"])
        except UsageLimit: break
        except Exception as ex: print(f"   예상 맞을 때/틀릴 때 채우기 실패: {str(ex)[:100]}", flush=True); break
