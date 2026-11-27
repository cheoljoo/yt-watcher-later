"""예전에 분석해 track_metrics 가 없는 영상: 저장해 둔 배울 점·확인 항목만 보고 추적 지표를 뽑아 analysis_json 에 채운다.
지표 등록은 indicators.register() 가 한다. 한 번 실행에서 처리할 영상 수는 config.toml 의 track_backfill_per_run (0 이면 끔)."""
import json
from analyze import TRACK_ITEM, TRACK_RULE

CHUNK = 20
SCHEMA = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["video_id", "track_metrics"],
    "properties": {"video_id": {"type": "string"}, "track_metrics": {"type": "array", "items": TRACK_ITEM}}}}}}


def prompt(known):
    return ("영상마다 track_metrics 를 뽑으세요. 기준: " + TRACK_RULE + " 입력에 없는 내용은 지어내지 말고, 입력의 모든 video_id 를 그대로 한 번씩 반환하세요.\n"
            "아래 '이미 있는 지표'와 같은 것이면 이름을 글자 그대로 쓰세요: " + (", ".join(known) or "(없음)"))


def pending(con, limit):
    """track_metrics 가 아직 없는 분석 완료 영상(최근 분석부터). 배울 점도 확인 항목도 없는 영상은 제외."""
    return con.execute("""SELECT id, title, lessons FROM videos v WHERE status='done' AND analysis_json IS NOT NULL AND analysis_json NOT LIKE '%"track_metrics"%'
        AND (COALESCE(lessons,'') NOT IN ('','[]') OR EXISTS(SELECT 1 FROM checks c WHERE c.video_id=v.id))
        ORDER BY processed_at DESC LIMIT ?""", (limit,)).fetchall()


def task_line(con, v):
    try: lessons = json.loads(v["lessons"] or "[]")
    except Exception: lessons = []
    checks = con.execute("SELECT kind, target, what_to_check FROM checks WHERE video_id=?", (v["id"],)).fetchall()
    return (f"video_id={v['id']} | 제목: {v['title']}\n  배울 점: " + (" / ".join(map(str, lessons)) or "(없음)")
            + "\n  확인할 것: " + (" / ".join(f"[{c['kind']}] {c['target']}: {c['what_to_check']}" for c in checks) or "(없음)"))


def apply(con, items):
    n = 0
    for it in items:
        row = con.execute("SELECT analysis_json FROM videos WHERE id=?", (it["video_id"],)).fetchone()
        if not row or not row[0]: continue
        data = json.loads(row[0]); data["track_metrics"] = it["track_metrics"]
        con.execute("UPDATE videos SET analysis_json=? WHERE id=?", (json.dumps(data, ensure_ascii=False), it["video_id"])); n += 1
    con.commit()
    return n
