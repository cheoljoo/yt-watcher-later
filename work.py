"""스킬 모드 작업 관리자.  `claude -p` 를 항목마다 새로 띄우는 대신, Claude 세션 하나 안에서 스킬(yt-daily)이
이 스크립트로 '다음 작업'을 받아 처리하고 결과를 제출한다.  DB 를 읽고 쓰는 일, 수집·시세·리포트는 모두 코드가 한다.

  uv run work.py collect            # (LLM 없음) 재생목록 -> 병렬 수집. 작업 큐 초기화
  uv run work.py start --budget N   # 세션 시작(이번 세션에서 읽게 할 입력 크기 상한)
  uv run work.py next               # 다음 Claude 작업 1건을 JSON 으로 출력 (없으면 {"done": true, ...})
  uv run work.py submit TASK_ID --file F  # 결과 JSON 파일(없으면 stdin)을 받아 스키마 검증 후 DB 에 반영
  uv run work.py skip TASK_ID --reason "..."
  uv run work.py status             # all_done | more | stalled  (run_skill.sh 가 라운드 반복 여부를 판단)
  uv run work.py finish             # (LLM 없음) HTML 리포트·JSON 생성

작업 단계 순서: video(영상 분석) -> enrich(지표 설명) -> map(시세 출처) -> meaning(값의 의미) -> phase(매크로 위치) -> check(확인 항목 판정)
"""
import argparse, hashlib, json, pathlib, shutil, sys
from jsonschema import Draft202012Validator
import db as D
import main as M
import opinions as OP, indicators as I, autocheck as A, report, export_json
from analyze import SCHEMA as VIDEO_SCHEMA, build_request, CATEGORIES
from fetcher import collect_many, write_log

W = pathlib.Path("data/_work")
COL, TASKS, INP, SCH, STATE = W / "col", W / "tasks", W / "in", W / "schema", W / "state.json"
STAGES = ["video", "enrich", "map", "meaning", "phase", "check", "checkfill", "opinion"]
SCHEMAS = {"video": VIDEO_SCHEMA, "enrich": I.ENRICH, "map": I.MAP, "meaning": I.MEANING, "phase": I.PHASE, "check": A.SCHEMA, "checkfill": A.FILL_SCHEMA, "opinion": OP.SCHEMA}
MAX_TRANSCRIPT = 60000      # 자막이 이보다 길면 앞·뒤만 남김(컨텍스트 보호). 중앙값은 약 9천자.
cfg = M.cfg
import os
if os.environ.get("YT_STAGES"): STAGES = [x for x in STAGES if x in os.environ["YT_STAGES"].split(",")]   # 예: YT_STAGES=video (벤치마크·부분 실행용)


def load_state():
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if st.get("date") != D.today(): st = {"date": D.today(), "attempted": {}, "total_submitted": 0}
    st.setdefault("attempted", {}); st.setdefault("budget", 250000); st.setdefault("used", 0)
    st.setdefault("round_submitted", 0); st.setdefault("last", "more")
    return st

def save_state(st):
    W.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

def tried(st, kind): return set(st["attempted"].get(kind, []))
def mark_tried(st, kind, keys): st["attempted"][kind] = sorted(tried(st, kind) | set(map(str, keys)))
def tid_of(kind, keys): return f"{kind}-{hashlib.md5('|'.join(map(str, keys)).encode()).hexdigest()[:8]}"

def write_task(kind, keys, prompt, body):
    tid = tid_of(kind, keys)
    INP.mkdir(parents=True, exist_ok=True); TASKS.mkdir(parents=True, exist_ok=True)
    (INP / f"{tid}.txt").write_text(f"# 지시\n{prompt}\n\n# 입력\n{body}\n", encoding="utf-8")
    (TASKS / f"{tid}.json").write_text(json.dumps({"tid": tid, "kind": kind, "keys": list(map(str, keys)), "size": len(prompt) + len(body)}, ensure_ascii=False), encoding="utf-8")

def pending(kind): return sorted(TASKS.glob(f"{kind}-*.json")) if TASKS.exists() else []
def chunks(xs, n): return [xs[i:i + n] for i in range(0, len(xs), n)]


# ── 단계별 작업 생성 ─────────────────────────────────────────────
def gen_video(con, st):
    done = {r[0] for r in con.execute("SELECT id FROM videos WHERE status='done'")}
    voc, today = M.vocab(con), D.today()
    allowed = int(os.environ.get("MAX_ANALYZE") or cfg.get("max_analyze", 30)) - len(tried(st, "video"))      # 이번 실행(collect~finish)에서 더 분석할 수 있는 수
    cols = [json.loads(f.read_text(encoding="utf-8")) | {"f": f} for f in (COL.glob("*.json") if COL.exists() else [])]
    for d in sorted(cols, key=lambda d: d["v"]["pos"]):                 # 재생목록 앞쪽(최근 추가)부터
        v, col = d["v"], d["col"]
        if v["id"] in done: d["f"].unlink(); continue
        if v["id"] in tried(st, "video"): continue
        if allowed <= 0: break
        allowed -= 1
        ip = M.DATA / v["id"] / f"{v['id']}.info.json"
        col["info"] = json.loads(ip.read_text(encoding="utf-8")) if ip.exists() else {}
        prompt, body = build_request(v, col, voc, today, max_chars=MAX_TRANSCRIPT)
        write_task("video", [v["id"]], prompt, body)

def gen_enrich(con, st):
    I.register(con)
    names = [r[0] for r in con.execute("SELECT name FROM indicators WHERE enriched_at IS NULL") if r[0] not in tried(st, "enrich")]
    for ch in chunks(names, I.CHUNK): write_task("enrich", ch, I.ENRICH_PROMPT, "\n".join(ch))

def gen_map(con, st):
    due = A.due_checks(con); A.prepare(con, due)            # 확인 대상도 출처 매핑 대상에 포함
    names = [r[0] for r in con.execute("SELECT name FROM indicators WHERE mapped_at IS NULL") if r[0] not in tried(st, "map")]
    for ch in chunks(names, I.CHUNK): write_task("map", ch, I.MAP_PROMPT, "\n".join(ch))

def gen_values(con, st):
    I.merge_duplicates(con)
    g = I.gather_values(con)
    if g: print(f"   실제 값 {g[0]}/{g[1]}개 기록 (출처 없음 {g[2]}개는 건너뜀)", file=sys.stderr)

def gen_meaning(con, st):
    gen_values(con, st)
    todo = [(n, l) for n, l in I.value_lines(con, only_missing=True) if n not in tried(st, "meaning")]
    for ch in chunks(todo, I.CHUNK): write_task("meaning", [n for n, _ in ch], I.MEANING_PROMPT, "\n".join(l for _, l in ch))

def gen_phase(con, st):
    today = D.today()
    if con.execute("SELECT 1 FROM macro_daily WHERE date=?", (today,)).fetchone() or "phase" in tried(st, "phase"): return
    key = [l for _, l in I.value_lines(con, today, important=True)][:40] or [l for _, l in I.value_lines(con, today)][:40]
    if key: write_task("phase", ["phase"], I.phase_prompt(today), "\n".join(key))

def gen_check(con, st):
    due = [c for c in A.due_checks(con, 300) if str(c["id"]) not in tried(st, "check")]
    if not due: return
    items = A.build_items(con, due)
    for ch in chunks(items, A.CHUNK): write_task("check", [i for i, _ in ch], A.PROMPT, "\n".join(t for _, t in ch))

def gen_checkfill(con, st):
    """예전에 등록돼 '예상이 맞을 때/틀릴 때' 가 없는 대기 항목을 채운다(한 번에 최대 A.FILL_PER_RUN 개)."""
    rows = [c for c in A.fill_candidates(con) if str(c["id"]) not in tried(st, "checkfill")]
    for ch in chunks(rows, 25): write_task("checkfill", [c["id"] for c in ch], A.FILL_PROMPT, "\n".join(A.fill_line(c) for c in ch))

def gen_opinion(con, st):
    """내 의견은 있고 AI 의견이 없는 영상 -> AI 의견 작업."""
    rows = [r for r in OP.pending(con) if r["video_id"] not in tried(st, "opinion")]
    for ch in chunks(rows, 8): write_task("opinion", [r["video_id"] for r in ch], OP.PROMPT, "\n".join(OP.task_line(r) for r in ch))

GEN = {"video": gen_video, "enrich": gen_enrich, "map": gen_map, "meaning": gen_meaning, "phase": gen_phase, "check": gen_check, "checkfill": gen_checkfill, "opinion": gen_opinion}


# ── 명령 ────────────────────────────────────────────────────────
def write_schemas():
    SCH.mkdir(parents=True, exist_ok=True)
    for k, sc in SCHEMAS.items(): (SCH / f"{k}.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")

def cmd_collect(a):
    """(LLM 없음) 새 영상 + 재시도 대상 영상을 병렬 수집해 작업 큐(data/_work/col)에 넣는다."""
    con = D.connect(); st = load_state()
    for d in (TASKS, INP):
        shutil.rmtree(d, ignore_errors=True)
    COL.mkdir(parents=True, exist_ok=True); write_schemas()
    st["attempted"] = {}; st["round_submitted"] = 0
    rows = con.execute("SELECT id,url,title,wl_position,owner,playlist_name FROM videos WHERE transcript_status='pending_retry' AND transcript_retry_at<=?", (D.today(),)).fetchall()
    retry = [{"id": r["id"], "url": r["url"], "title": r["title"], "pos": r["wl_position"], "owner": r["owner"] or "cheoljoo", "playlist": r["playlist_name"]} for r in rows]
    for v in retry:
        for f in (M.DATA / v["id"]).glob(f"{v['id']}.*.vtt"): f.unlink()
        (M.DATA / v["id"] / f"{v['id']}.info.json").unlink(missing_ok=True)
    vids = M.load_playlists()
    done = {r[0] for r in con.execute("SELECT id FROM videos WHERE status='done'")}
    ids = {v["id"] for v in retry}
    backlog = [v for v in vids if v["id"] not in done]
    have = {f.stem for f in COL.glob("*.json")}                         # 앞선 실행에서 이미 수집해 둔 것은 다시 받지 않는다
    targets = retry + [v for v in backlog if v["id"] not in ids and v["id"] not in have]
    con.execute("DELETE FROM backlog")
    con.executemany("INSERT OR REPLACE INTO backlog VALUES(?,?,?,?,?,?)", [(v["id"], v["title"], v["owner"], v["playlist"], v["pos"], D.now()) for v in backlog])
    con.commit()
    print(f"전체 {len(vids)}개 중 미분석 {len(backlog)}개, 이번에 수집할 것 {len(targets)}개 (재시도 {len(retry)}개 포함) — Claude 분석은 최대 {cfg.get('max_analyze', 30)}개", flush=True)
    if targets:
        got, bad, lines = collect_many(targets, cfg)
        for vid, msg in bad.items(): M.mark_error(con, next(v for v in targets if v["id"] == vid), msg)
        for v in targets:
            if v["id"] in got:
                c = got[v["id"]]
                (COL / f"{v['id']}.json").write_text(json.dumps({"v": v, "col": {"meta": c["meta"], "lang": c["lang"], "transcript": c["transcript"]}}, ensure_ascii=False), encoding="utf-8")
        print(f"수집 성공 {len(got)} / 실패 {len(bad)} — 로그: {write_log(lines)}", flush=True)
    con.execute("UPDATE videos SET transcript_status='gave_up', transcript_retry_at=NULL WHERE transcript_status='pending_retry' AND transcript_attempts>=2 AND transcript_retry_at<=?", (D.today(),))
    con.commit(); save_state(st)

def cmd_start(a):
    st = load_state(); st.update(budget=a.budget, used=0, round_submitted=0, last="more"); save_state(st)

def cmd_next(a):
    con = D.connect(); st = load_state(); (W / "out").mkdir(parents=True, exist_ok=True); write_schemas()
    for kind in STAGES:
        if not pending(kind): GEN[kind](con, st)
        ts = pending(kind)
        while ts:
            t = json.loads(ts[0].read_text(encoding="utf-8"))
            if kind == "video" and not (COL / f"{t['keys'][0]}.json").exists():    # 입력이 사라진 작업은 버린다
                ts[0].unlink(); ts = pending(kind); continue
            if st["used"] > 0 and st["used"] + t["size"] > st["budget"]:
                st["last"] = "more"; save_state(st)
                print(json.dumps({"done": True, "reason": "session_budget", "message": "이번 세션 입력 한도에 도달 — 남은 작업은 다음 세션에서 이어서 처리합니다."}, ensure_ascii=False)); return
            st["used"] += t["size"]; save_state(st)
            print(json.dumps({"task": t["tid"], "kind": kind, "input_file": str((INP / f"{t['tid']}.txt").resolve()),
                              "schema_file": str((SCH / f"{kind}.json").resolve()), "stage_remaining": len(ts)}, ensure_ascii=False)); return
    st["last"] = "all_done"; save_state(st)
    print(json.dumps({"done": True, "reason": "all_done", "message": "처리할 작업이 더 없습니다."}, ensure_ascii=False))

def cmd_submit(a):
    con = D.connect(); st = load_state()
    tf = TASKS / f"{a.tid}.json"
    if not tf.exists(): sys.exit(f"알 수 없는 작업: {a.tid} (이미 제출했거나 만료됨)")
    t = json.loads(tf.read_text(encoding="utf-8")); kind = t["kind"]
    try: data = json.load(open(a.file, encoding="utf-8") if a.file else sys.stdin)
    except Exception as ex: sys.exit(f"JSON 파싱 실패: {ex}")
    errs = sorted(Draft202012Validator(SCHEMAS[kind]).iter_errors(data), key=lambda e: list(e.path))
    if errs:
        print("스키마 검증 실패 — 고쳐서 다시 제출하세요:", file=sys.stderr)
        for e in errs[:6]: print(f"  - {'/'.join(map(str, e.path)) or '(최상위)'}: {e.message[:200]}", file=sys.stderr)
        sys.exit(2)
    msg = ""
    if kind == "video":
        d = json.loads((COL / f"{t['keys'][0]}.json").read_text(encoding="utf-8"))
        M.store(con, d["v"], d["col"], data, os.environ.get("YT_MODEL") or cfg["model"], os.environ.get("YT_ENGINE") or "claude"); (COL / f"{t['keys'][0]}.json").unlink()
        msg = f"저장 {d['v']['owner']}/{d['v']['id']} [{data['category']}/{data['subtag']}] 확인항목 {len(data['checks'])}개"
    elif kind == "enrich": I.apply_enrich(con, data["items"]); msg = f"지표 설명 {len(data['items'])}개"
    elif kind == "map": I.apply_map(con, data["items"]); msg = f"출처 매핑 {len(data['items'])}개"
    elif kind == "meaning": I.apply_meaning(con, data["items"]); msg = f"의미 해설 {len(data['items'])}개"
    elif kind == "phase": I.apply_phase(con, data); msg = f"매크로 위치 {data['phase_index']}"
    elif kind == "opinion": msg = f"AI 의견 {OP.apply_ai(con, data['items'])}건"
    elif kind == "checkfill": msg = f"예상 맞을 때/틀릴 때 {A.apply_fill(con, data['items'])}건"
    elif kind == "check": msg = f"자동 판정 {A.apply(con, data['items'])}건"
    mark_tried(st, kind, t["keys"]); st["round_submitted"] += 1; st["total_submitted"] = st.get("total_submitted", 0) + 1
    save_state(st); tf.unlink(); (INP / f"{a.tid}.txt").unlink(missing_ok=True)
    if a.file: pathlib.Path(a.file).unlink(missing_ok=True)
    print("OK", msg)

def cmd_skip(a):
    con = D.connect(); st = load_state()
    tf = TASKS / f"{a.tid}.json"
    if not tf.exists(): sys.exit("알 수 없는 작업")
    t = json.loads(tf.read_text(encoding="utf-8"))
    if t["kind"] == "video":
        d = json.loads((COL / f"{t['keys'][0]}.json").read_text(encoding="utf-8")); M.mark_error(con, d["v"], a.reason or "건너뜀")
    mark_tried(st, t["kind"], t["keys"]); save_state(st); tf.unlink(); (INP / f"{a.tid}.txt").unlink(missing_ok=True)
    print("SKIPPED", a.tid, a.reason or "")

def cmd_status(a):
    st = load_state()
    word = "all_done" if st["last"] == "all_done" else "stalled" if st["round_submitted"] == 0 else "more"
    print(word, f"(이번 라운드 제출 {st['round_submitted']}건, 오늘 누적 {st.get('total_submitted', 0)}건)")
    sys.exit(0 if word == "more" else 1)

def cmd_finish(a):
    con = D.connect()
    report.build_all(con); print("JSON:", export_json.export(con), export_json.export(con, "data/watchlater_full.json", True), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect"); sub.add_parser("next"); sub.add_parser("status"); sub.add_parser("finish")
    s = sub.add_parser("start"); s.add_argument("--budget", type=int, default=250000)
    s = sub.add_parser("submit"); s.add_argument("tid"); s.add_argument("--file")
    s = sub.add_parser("skip"); s.add_argument("tid"); s.add_argument("--reason", default="")
    a = ap.parse_args(); globals()["cmd_" + a.cmd](a)
