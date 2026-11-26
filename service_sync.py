"""서비스 서버: 개발 서버가 push 한 DB 백업을 pull 해 DB 를 다시 만들고 web 서비스용 페이지를 갱신한다.

  uv run service_sync.py          # 백업 저장소 pull → BACKUP_TIME(백업이 끝난 시각)이 지난번과 다르면 DB 복원·교체 → 리포트 다시 만들기(네트워크·AI 없음)
  uv run service_sync.py --force  # 시각이 같아도(자기가 만든 백업이어도) 다시 복원
  ※ BACKUP_TIME 2행(만든 컴퓨터)이 이 컴퓨터이면 복원하지 않는다 — 자기 DB 가 더 새것인데 덮어써 입력을 잃는 것을 막는다.

역할이 service 일 때만 일한다(legacy 면 아무것도 안 함 — 분리 전에는 예전처럼 이 서버가 전부 한다). cron 으로 자주(예: 10분마다) 돌려도 된다: 백업 저장소의 BACKUP_TIME 이 지난번 복원한 것과 같으면 곧바로 끝난다.
이 서버의 백업 폴더는 읽기 전용 사본이다 — push 하지 않고 원격(origin)과 똑같이 맞춘다(fetch + reset --hard).
개발 서버는 덤프 → BACKUP_TIME 기록 → commit·push 를 한 번에 하므로, pull 로 받은 커밋은 항상 완결된 백업이고 BACKUP_TIME 이 '언제 만든 백업인지'를 알려 준다(문제가 생기면 이 시각으로 어느 단계에서 멈췄는지 가린다).
복원: 새 파일(data/watchlater.db.new)로 만들어 행 수를 확인한 뒤 os.replace 로 한 번에 교체한다(서비스 중인 opinion_server 는 요청마다 DB 를 새로 열어서 그대로 계속 동작).
입력은 이 단계에서 건드리지 않는다: 사용자가 누른 입력은 inbox 에 있고 개발 서버가 가져가 원본 DB 에 반영한다."""
import os, pathlib, socket, sqlite3, subprocess, sys
import db as D, dbbackup as B, role

STATE = pathlib.Path(__file__).resolve().parent / "data" / "_service"
LAST = STATE / "last_backup_time"       # 마지막으로 복원한 백업의 BACKUP_TIME 내용


def run(force=False):
    r = role.role()
    if r != "service": return f"역할이 {r} 라서 하지 않음 ({role.why()})"
    out = B.DEFAULT
    if not (out / ".git").exists(): return f"백업 폴더 {out} 가 git 저장소가 아님 — git clone 으로 먼저 받으세요"
    g = lambda *x: subprocess.run(["git", "-C", str(out), *x], capture_output=True, text=True, timeout=300)
    f = g("fetch", "-q")
    if f.returncode: return f"git fetch 실패: {(f.stderr or f.stdout).strip()[-200:]}"
    g("reset", "-q", "--hard", "@{u}")                                  # 읽기 전용 사본 — 원격과 똑같이
    bt = out / "BACKUP_TIME"
    if not bt.exists(): return "BACKUP_TIME 없음 — 개발 서버가 아직 새 방식으로 백업하지 않음(기존 DB 로 계속 서비스)"
    marker = bt.read_text(encoding="utf-8").strip()                     # 1행 백업이 끝난 시각, 2행 만든 컴퓨터
    when = marker.splitlines()[0]
    STATE.mkdir(parents=True, exist_ok=True)
    maker = (marker.splitlines() + [""])[1]
    if not force and maker == socket.gethostname(): return f"마지막 백업({when})은 이 컴퓨터가 만든 것 — 지금 DB 가 더 새것이라 복원하지 않음(개발 서버의 백업을 기다림)"
    if not force and LAST.exists() and LAST.read_text(encoding="utf-8").strip() == marker: return f"새 백업 없음(마지막 백업 시각 {when})"
    new = pathlib.Path(str(D.DB_PATH) + ".new")
    for f in (new, pathlib.Path(str(new) + "-wal"), pathlib.Path(str(new) + "-shm")): f.unlink(missing_ok=True)
    counts = B.restore(out, str(new))                                   # 백업 → 새 파일
    con = sqlite3.connect(new); bad = []
    for t, n in counts.items():
        if con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] != n: bad.append(t)
    con.close()
    if bad: new.unlink(missing_ok=True); return f"복원본 행 수 불일치({bad}) — 교체하지 않음"
    old = pathlib.Path(D.DB_PATH)
    B.keep_previous(old)                                                # 교체 직전의 DB 를 watchlater.db.bak 한 개로 남긴다
    if old.exists():
        try: c = sqlite3.connect(old); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
        except Exception: pass
    os.replace(new, old)
    for ext in ("-wal", "-shm"): pathlib.Path(str(old) + ext).unlink(missing_ok=True)   # 옛 DB 의 로그가 새 파일에 붙지 않게
    LAST.write_text(marker + "\n", encoding="utf-8")
    os.environ["YT_NO_FETCH"] = "1"                                     # 시세·AI·네트워크 없이 복원한 DB 값으로만 페이지를 만든다
    import report
    report.build_all(D.connect())
    return f"복원 완료({sum(counts.values())}행, 백업 시각 {when}) · 리포트 다시 만듦"


if __name__ == "__main__":
    print("서비스 동기화:", run("--force" in sys.argv))
