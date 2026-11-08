"""지표 추적: (1) 영상 분석에서 나온 지표/종목 등록 (2) 설명·해석·기준값 채우기 (3) 출처 매핑(Yahoo/FRED, 1회)
(4) 하루 1회 실제 시세 수집(코드) + 변화 신호 계산 + 의미 해설(Claude). 실제 값을 못 구한 지표는 값을 만들지 않고 건너뛴다."""
import json, datetime
import marketdata
from concurrent.futures import ThreadPoolExecutor
from llm import claude_json
from analyze import UsageLimit
import db as D

CYCLE = [  # 경기/매크로 주기 6단계
    ("회복", "바닥을 지나 경기가 되살아나는 구간. 금리 인하 효과가 나타나고 선행지표(주가·신용스프레드)가 먼저 개선된다. 실물지표는 아직 약하다."),
    ("확장 초기", "성장률·고용·소비가 함께 좋아지는 구간. 물가는 안정적이고 금리는 낮거나 완만하게 오른다. 위험자산(주식)에 가장 우호적이다."),
    ("확장 후기", "성장이 정점에 가까워지며 과열 신호(물가·임금·자산가격 상승)가 나온다. 중앙은행이 긴축으로 돌아서기 시작한다."),
    ("정점·둔화", "금리가 높은 수준에서 성장이 꺾이는 구간. 장단기 금리 역전, 기업 이익 둔화, 변동성 확대가 흔하다."),
    ("수축", "생산·소비·고용이 줄어드는 침체 구간. 실업률이 오르고 물가는 내려가며 중앙은행이 완화로 돌아선다."),
    ("바닥", "악화 속도가 멈추고 정책 완화·유동성 공급이 효과를 내기 시작하는 구간. 주가는 실물보다 먼저 저점을 만든다."),
]
ENRICH = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["name", "category", "unit", "description", "interpretation", "baseline", "importance", "warn_low", "warn_high"],
    "properties": {"name": {"type": "string"}, "category": {"type": "string"}, "unit": {"type": "string"},
                   "description": {"type": "string"}, "interpretation": {"type": "string"}, "baseline": {"type": "string"},
                   "importance": {"type": "string", "enum": ["high", "normal"]},
                   "warn_low": {"type": ["number", "null"]}, "warn_high": {"type": ["number", "null"]}}}}}}
MAP = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["name", "source", "symbol"], "properties": {"name": {"type": "string"},
    "source": {"type": "string", "enum": ["yahoo", "fred", "none"]}, "symbol": {"type": "string"}}}}}}
MEANING = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["name", "meaning"], "properties": {"name": {"type": "string"}, "meaning": {"type": "string"}}}}}}
PHASE = {"type": "object", "required": ["phase_index", "reason"], "properties": {"phase_index": {"type": "integer"}, "reason": {"type": "string"}}}
CHUNK = 30
ENRICH_PROMPT = ("각 지표/종목에 대해 한국어로 채우세요. category: 금리/물가/환율/주가지수/고용/성장/원자재/유동성/종목/심리/기타 중 하나. "
              "description: 무엇을 나타내는지 2문장. interpretation: 값이 오르거나 내릴 때 어떻게 해석하는지, 무엇을 조심할지 3~4문장. "
              "baseline: 평균·균형·기본값(정상 범위)을 숫자와 함께 구체적으로. warn_low/warn_high: 이 아래/위로 가면 경고인 임계값(없으면 null). "
              "importance: 거시 판단에 핵심이면 high. name은 입력 그대로 반환. 모르는 항목은 지어내지 말고 baseline에 '확인 필요'.")

MAP_PROMPT = ("각 지표/종목을 실제 시세를 받을 수 있는 출처에 매핑하세요. source=yahoo(Yahoo Finance 심볼: 지수 ^GSPC ^IXIC ^KS11 ^KQ11 ^VIX, 환율 KRW=X JPY=X EURUSD=X, "
              "미 국채금리 ^IRX ^FVX ^TNX ^TYX(단위 %), 원자재 CL=F GC=F HG=F, 코인 BTC-USD, 한국주식 005930.KS, 미국주식 NVDA 등) | "
              "fred(FRED 시리즈 ID: UNRATE, CPIAUCSL, PCEPI, PAYEMS, FEDFUNDS, T10Y2Y, DGS10, DGS2, M2SL, WALCL, BAMLH0A0HYM2 등) | none(재무비율·전망치·질적 판단처럼 시세 시리즈가 없는 것). "
              "확실한 심볼만 쓰고, 모호하면 none. symbol은 source가 none이면 빈 문자열. name은 입력 그대로.")

def register(con):
    """영상 분석에서 나온 '봐야 할 지표'와 종목 확인항목을 지표 테이블에 등록(이미 있으면 출처만 추가)."""
    def add(name, vid, why, cat=None):
        name = (name or "").strip()
        if not name: return
        con.execute("INSERT OR IGNORE INTO indicators(name,category,first_seen_at) VALUES(?,?,?)", (name, cat, D.now()))
        iid = con.execute("SELECT id FROM indicators WHERE name=?", (name,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO indicator_sources VALUES(?,?,?)", (iid, vid, why))
    for r in con.execute("SELECT id, indicators_to_watch FROM videos WHERE status='done' AND indicators_to_watch IS NOT NULL").fetchall():
        try: items = json.loads(r["indicators_to_watch"])
        except Exception: continue
        for i in items: add(i.get("name"), r["id"], i.get("why"))
    for c in con.execute("SELECT video_id, target, what_to_check FROM checks WHERE kind IN ('indicator','stock')").fetchall():
        add(c["target"], c["video_id"], c["what_to_check"])
    con.commit()

def _map(con, fn, chunks, workers=2):
    with ThreadPoolExecutor(workers) as ex: return list(ex.map(fn, chunks))

def apply_enrich(con, items):
    for it in items:
        con.execute("""UPDATE indicators SET category=?,unit=?,description=?,interpretation=?,baseline=?,importance=?,warn_low=?,warn_high=?,enriched_at=?,enrich_llm=?
                       WHERE name=?""", (it["category"], it["unit"], it["description"], it["interpretation"], it["baseline"], it["importance"],
                                          it["warn_low"], it["warn_high"], D.now(), D.llm_tag(), it["name"]))
    con.commit()

def apply_map(con, items):
    for it in items:
        con.execute("UPDATE indicators SET source=?, symbol=?, mapped_at=?, map_llm=? WHERE name=?", (it["source"], it["symbol"], D.now(), D.llm_tag(), it["name"]))
    con.commit()

def enrich(con, cfg):
    names = [r[0] for r in con.execute("SELECT name FROM indicators WHERE enriched_at IS NULL")]
    if not names: return
    prompt = ENRICH_PROMPT
    def one(chunk):
        try: return claude_json(prompt, "\n".join(chunk), ENRICH, cfg["model"])["items"]
        except UsageLimit: raise
        except Exception as ex: print(f"   지표 설명 실패: {str(ex)[:120]}", flush=True); return []
    for items in _map(con, one, [names[i:i + CHUNK] for i in range(0, len(names), CHUNK)]): apply_enrich(con, items)


def map_sources(con, cfg):
    """아직 출처가 없는 지표를 Yahoo 심볼 / FRED 시리즈에 한 번만 매핑(결과는 DB에 저장). 시세가 없는 질적 지표는 none."""
    names = [r[0] for r in con.execute("SELECT name FROM indicators WHERE mapped_at IS NULL")]
    if not names: return
    prompt = MAP_PROMPT
    def one(chunk):
        try: return claude_json(prompt, "\n".join(chunk), MAP, cfg["model"])["items"]
        except UsageLimit: raise
        except Exception as ex: print(f"   출처 매핑 실패: {str(ex)[:120]}", flush=True); return []
    for items in _map(con, one, [names[i:i + CHUNK] for i in range(0, len(names), CHUNK)]): apply_map(con, items)

def merge_duplicates(con):
    """같은 출처·심볼을 가리키는 지표는 하나로 합친다(가장 짧은 이름이 대표). 나머지는 별칭(alias_of)으로 비활성화하고 영상 출처를 대표에 옮긴다."""
    n = 0
    for g in con.execute("SELECT source, symbol FROM indicators WHERE source IN ('yahoo','fred') AND symbol!='' AND alias_of IS NULL GROUP BY source, symbol HAVING count(*)>1").fetchall():
        rows = sorted(con.execute("SELECT id,name FROM indicators WHERE source=? AND symbol=? AND alias_of IS NULL", (g["source"], g["symbol"])).fetchall(), key=lambda r: (len(r["name"]), r["id"]))
        main, rest = rows[0]["id"], rows[1:]
        for r in rest:
            con.execute("INSERT OR IGNORE INTO indicator_sources SELECT ?, video_id, why FROM indicator_sources WHERE indicator_id=?", (main, r["id"]))
            con.execute("DELETE FROM indicator_sources WHERE indicator_id=?", (r["id"],))
            con.execute("DELETE FROM indicator_values WHERE indicator_id=?", (r["id"],))
            con.execute("UPDATE indicators SET active=0, alias_of=? WHERE id=?", (main, r["id"])); n += 1
    con.commit()
    if n: print(f"   중복 지표 {n}개를 대표 지표로 병합", flush=True)

def _dir(delta_pct, flat=0.3):
    return "unknown" if delta_pct is None else "up" if delta_pct > flat else "down" if delta_pct < -flat else "flat"

def _pct(a, b): return None if a is None or b in (None, 0) else (a - b) / abs(b) * 100

def analyze_series(ind, rows):
    """실제 시계열 -> 현재값/직전값/변화율/방향/신호. 신호 = 경고(급변) | 임계값 돌파 | 방향 전환."""
    last_d, last = rows[-1]; prev = rows[-2][1] if len(rows) > 1 else None
    k = 5 if ind["source"] == "yahoo" else 1                # 시장 시세는 1주, 월간 거시지표는 직전 발표 대비
    ref = rows[-1 - k][1] if len(rows) > k else prev
    ref2 = rows[-1 - 2 * k][1] if len(rows) > 2 * k else None
    d_now, d_before = _dir(_pct(last, ref)), _dir(_pct(ref, ref2))
    chg = _pct(last, prev)
    sig = why = None
    lo, hi = ind["warn_low"], ind["warn_high"]
    if prev is not None and hi is not None and prev <= hi < last: sig, why = "threshold", f"상단 임계 {hi:g} 돌파"
    elif prev is not None and hi is not None and last <= hi < prev: sig, why = "threshold", f"상단 임계 {hi:g} 아래로 복귀"
    elif prev is not None and lo is not None and prev >= lo > last: sig, why = "threshold", f"하단 임계 {lo:g} 이탈"
    elif prev is not None and lo is not None and last >= lo > prev: sig, why = "threshold", f"하단 임계 {lo:g} 위로 복귀"
    if chg is not None and abs(chg) >= 5 and ind["source"] == "yahoo": sig, why = "warning", f"전 거래일 대비 {chg:+.1f}% 급변"
    if not sig and {d_now, d_before} == {"up", "down"}: sig, why = "direction", f"추세 전환: {d_before} → {d_now}"
    return dict(value=last, value_date=last_d, prev=prev, chg=None if chg is None else round(chg, 2), direction=d_now, signal=sig, why=why)

def _fmt(v): return f"{v:,.2f}".rstrip("0").rstrip(".")

MEANING_PROMPT = ("각 지표의 '실제 최신 값'이 주어집니다. 이 값이 현재 무엇을 의미하는지 기준값(평균·균형)과 비교해 1~2문장으로 해석하세요. "
                  "주어진 숫자만 근거로 하고 모르는 최신 사실을 지어내지 마세요. name은 입력 그대로.")

def phase_prompt(today):
    return f"아래는 {today} 기준 실제 지표 값입니다. 매크로 주기 6단계({', '.join(f'{i}={n}' for i, (n, _) in enumerate(CYCLE))}) 중 현재 위치를 고르고, 주어진 값만으로 근거를 쓰세요."

def _line(ind, value, value_date, prev, chg, direction):
    return (f"{ind['name']} | 단위 {ind['unit'] or '-'} | 기준 {ind['baseline'] or '-'} | 현재 {_fmt(value)} ({value_date}) | "
            f"직전 {_fmt(prev) if prev is not None else '-'} | 변화 {chg}% | 추세 {direction}")

def gather_values(con, force=False):
    """(코드) 활성 지표의 실제 시세를 받아 오늘 값·변화·신호를 저장한다(의미 해설은 비워 둠). 이미 수집했으면 None."""
    today = D.today()
    if not force and con.execute("SELECT 1 FROM indicator_values WHERE date=? LIMIT 1", (today,)).fetchone(): return None
    inds = con.execute("SELECT * FROM indicators WHERE active=1 AND source IN ('yahoo','fred') AND symbol!=''").fetchall()
    skipped = con.execute("SELECT count(*) FROM indicators WHERE active=1 AND (source IS NULL OR source='none' OR symbol='')").fetchone()[0]
    with ThreadPoolExecutor(5) as ex: series = list(ex.map(lambda i: marketdata.fetch(i["source"], i["symbol"]), inds))
    n = 0
    for ind, rows in zip(inds, series):
        if not rows: continue                                  # 못 구한 지표는 그날 건너뜀(값을 만들지 않음)
        a = analyze_series(ind, rows)
        con.execute("INSERT OR REPLACE INTO indicator_values VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (ind["id"], today, a["value"], _fmt(a["value"]) + (" (전년 대비 %)" if ind["source"] == "fred" and ind["symbol"] in marketdata.YOY else (f" {ind['unit']}" if ind["unit"] else "")),
                     a["value_date"], a["prev"], a["chg"], a["direction"], a["signal"], a["why"], None)); n += 1
    con.commit()
    return n, len(inds), skipped

def value_lines(con, today=None, only_missing=False, important=False):
    """오늘 저장된 값 -> [(지표이름, 입력줄)]. only_missing: 의미 해설이 아직 없는 것만, important: 중요 지표만."""
    today = today or D.today()
    q = ("SELECT i.*, v.value, v.value_date, v.prev_value, v.change_pct, v.direction AS dir, v.meaning FROM indicator_values v "
         "JOIN indicators i ON i.id=v.indicator_id WHERE v.date=? AND i.active=1")
    if only_missing: q += " AND v.meaning IS NULL"
    if important: q += " AND i.importance='high'"
    return [(r["name"], _line(r, r["value"], r["value_date"], r["prev_value"], r["change_pct"], r["dir"])) for r in con.execute(q + " ORDER BY i.id", (today,))]

def apply_meaning(con, items, today=None):
    today = today or D.today()
    for x in items:
        con.execute("UPDATE indicator_values SET meaning=?, llm=? WHERE date=? AND indicator_id=(SELECT id FROM indicators WHERE name=?)", (x["meaning"], D.llm_tag(), today, x["name"]))
    con.commit()

def apply_phase(con, r, today=None):
    today = today or D.today()
    if 0 <= r["phase_index"] < len(CYCLE):
        con.execute("INSERT OR REPLACE INTO macro_daily(date,phase_index,phase,reason,llm) VALUES(?,?,?,?,?)", (today, r["phase_index"], CYCLE[r["phase_index"]][0], r["reason"], D.llm_tag()))
        con.commit()

def collect_values(con, cfg, force=False):
    """(claude -p 호출 방식) 값 수집 후 의미 해설·매크로 위치를 Claude로 받는다."""
    today = D.today()
    g = gather_values(con, force)
    if g is None: print("   오늘 지표 값은 이미 수집됨 — 건너뜀", flush=True); return
    lines = value_lines(con, today, only_missing=True)
    def one(ch):
        try: return claude_json(MEANING_PROMPT, "\n".join(l for _, l in ch), MEANING, cfg["model"])["items"]
        except UsageLimit: raise
        except Exception as ex: print(f"   의미 해설 실패(값은 저장): {str(ex)[:100]}", flush=True); return []
    try:
        for items in _map(con, one, [lines[k:k + CHUNK] for k in range(0, len(lines), CHUNK)]): apply_meaning(con, items, today)
    except UsageLimit: print("   사용량 한도 — 의미 해설 생략(값은 저장)", flush=True)
    key = [l for _, l in value_lines(con, today, important=True)][:40] or [l for _, l in lines][:40]
    if key:
        try: apply_phase(con, claude_json(phase_prompt(today), "\n".join(key), PHASE, cfg["model"]), today)
        except UsageLimit: print("   사용량 한도 — 매크로 위치 판단 생략", flush=True)
        except Exception as ex: print(f"   매크로 위치 판단 실패: {str(ex)[:100]}", flush=True)
    print(f"   실제 값 {g[0]}/{g[1]}개 기록 (출처 없음 {g[2]}개는 건너뜀)", flush=True)

def update(con, cfg, force=False):
    print("[지표] 등록 → 설명 → 출처 매핑 → 오늘 실제 값", flush=True)
    register(con)
    try: enrich(con, cfg); map_sources(con, cfg); merge_duplicates(con); collect_values(con, cfg, force)
    except UsageLimit: print("   사용량 한도 — 지표 단계는 다음 실행으로 미룹니다.", flush=True)
