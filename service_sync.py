"""서비스 서버: 개발 서버가 push 한 DB 백업을 pull 해 DB 를 다시 만들고 web 서비스용 페이지를 갱신한다.

  uv run service_sync.py          # 백업 저장소 pull → BACKUP_TIME(백업이 끝난 시각)이 지난번과 다르면 아래 순서로 갱신
  uv run service_sync.py --force  # 시각이 같아도(자기가 만든 백업이어도) 다시 갱신
  ※ BACKUP_TIME 2행(만든 컴퓨터)이 이 컴퓨터이면 복원하지 않는다 — 자기 DB 가 더 새것인데 덮어써 입력을 잃는 것을 막는다.

새 백업이 있을 때의 순서
  1. 프로젝트 소스 `git pull --ff-only` — 개발 서버에서 코드가 바뀌었을 수 있다. HEAD 가 바뀌면 새 코드로 이 스크립트를 다시 실행한다
     (이미 읽어 들인 옛 모듈로 만들지 않게; `uv run` 이라 의존성도 맞춰진다). pull 이 안 되면(로컬 변경·갈라짐) 지금 코드로 계속하고 로그에 남긴다.
  2. DB 복원: 새 파일(data/watchlater.db.new)로 만들어 행 수를 확인 → 기존 DB 를 watchlater.db.bak 으로 복사 → os.replace 로 교체.
  3. HTML 다시 만들기(시세·AI·네트워크 없이 DB 값만).
  4. 입력 서버(yt-opinion) 재시작 — 소스의 .py 나 의존성(pyproject.toml·uv.lock)이 바뀌었을 때만. 문서·Makefile 만 바뀌었거나 DB 만 바뀌면 재시작하지 않는다
     (서버는 요청마다 DB 를 새로 열므로 DB 교체에는 재시작이 필요 없다).
  3·4 가 실패하면 data/_service/pending 에 남겨 다음 회차에 다시 한다.

역할이 service 일 때만 일한다. cron 으로 10분마다 돌려도 백업이 그대로면 곧바로 끝난다(이때는 소스도 pull 하지 않는다).
이 서버의 백업 폴더는 읽기 전용 사본이다 — push 하지 않고 원격(origin)과 똑같이 맞춘다(fetch + reset --hard).
입력은 건드리지 않는다: 사용자가 누른 입력은 inbox 에 있고 개발 서버가 가져가 원본 DB 에 반영한다."""
import json, os, pathlib, socket, sqlite3, subprocess, sys
import db as D, dbbackup as B, role

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / "data" / "_service"
LAST = STATE / "last_backup_time"       # 마지막으로 복원한 백업의 BACKUP_TIME 내용
PENDING = STATE / "pending"             # 복원 뒤 아직 못 끝낸 일 {"restart": true|false}
RESTART_ENV = "YT_RESTART_NEEDED"       # 새 코드로 다시 실행할 때 '재시작 필요'를 넘기는 환경변수


def _git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True, timeout=300)


def needs_restart(files):
    """바뀐 파일 목록으로 입력 서버 재시작이 필요한지 판단: 파이썬 코드나 의존성이 바뀌었을 때만."""
    return any(f.endswith(".py") or f in ("pyproject.toml", "uv.lock") for f in files)


def pull_source():
    """프로젝트 소스를 최신으로. 반환 (바뀌었는가, 재시작 필요한가, 메시지)."""
    before = _git(ROOT, "rev-parse", "HEAD").stdout.strip()
    p = _git(ROOT, "pull", "--ff-only", "-q")
    if p.returncode: return False, False, f"소스 pull 실패(지금 코드로 계속): {(p.stderr or p.stdout).strip()[-200:]}"
    after = _git(ROOT, "rev-parse", "HEAD").stdout.strip()
    if after == before: return False, False, "소스 변경 없음"
    files = _git(ROOT, "diff", "--name-only", before, after).stdout.split()
    return True, needs_restart(files), f"소스 갱신 {before[:7]} → {after[:7]} ({len(files)}개 파일)"


def restart_server():
    """입력 서버(systemd 사용자 서비스) 재시작. cron 에는 사용자 버스 환경변수가 없으므로 넣어 준다."""
    uid = os.getuid()
    env = {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{uid}", "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    cmd = os.environ.get("YT_RESTART_CMD", "systemctl --user restart yt-opinion")
    p = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=60, env=env)
    if p.returncode: raise RuntimeError(f"입력 서버 재시작 실패: {(p.stderr or p.stdout).strip()[-200:]}")


def finish_pending():
    """복원 뒤의 일(HTML 생성, 필요하면 서버 재시작). 실패하면 PENDING 이 남아 다음 회차에 다시 한다."""
    restart = json.loads(PENDING.read_text(encoding="utf-8")).get("restart", False)
    os.environ["YT_NO_FETCH"] = "1"                                     # 시세·AI·네트워크 없이 복원한 DB 값으로만 페이지를 만든다
    import report
    report.build_all(D.connect())
    if restart: restart_server()
    PENDING.unlink()
    return "리포트 다시 만듦" + (" · 입력 서버 재시작" if restart else " · 서버 재시작 불필요")


def restore(out, marker):
    """백업 → 새 파일 → 검증 → 이전 DB 사본 → 교체. 반환 (성공, 행 수 또는 오류 메시지)."""
    new = pathlib.Path(str(D.DB_PATH) + ".new")
    for f in (new, pathlib.Path(str(new) + "-wal"), pathlib.Path(str(new) + "-shm")): f.unlink(missing_ok=True)
    counts = B.restore(out, str(new))
    con = sqlite3.connect(new); bad = []
    for t, n in counts.items():
        if con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] != n: bad.append(t)
    con.close()
    if bad: new.unlink(missing_ok=True); return False, f"복원본 행 수 불일치({bad}) — 교체하지 않음"
    old = pathlib.Path(D.DB_PATH)
    B.keep_previous(old)                                                # 교체 직전의 DB 를 watchlater.db.bak 한 개로 남긴다
    if old.exists():
        try: c = sqlite3.connect(old); c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.close()
        except Exception: pass
    os.replace(new, old)
    for ext in ("-wal", "-shm"): pathlib.Path(str(old) + ext).unlink(missing_ok=True)   # 옛 DB 의 로그가 새 파일에 붙지 않게
    LAST.write_text(marker + "\n", encoding="utf-8")
    return True, sum(counts.values())


def run(force=False):
    r = role.role()
    if r != "service": return f"역할이 {r} 라서 하지 않음 ({role.why()})"
    out = B.DEFAULT
    if not (out / ".git").exists(): return f"백업 폴더 {out} 가 git 저장소가 아님 — git clone 으로 먼저 받으세요"
    f = _git(out, "fetch", "-q")
    if f.returncode: return f"git fetch 실패: {(f.stderr or f.stdout).strip()[-200:]}"
    _git(out, "reset", "-q", "--hard", "@{u}")                          # 읽기 전용 사본 — 원격과 똑같이
    bt = out / "BACKUP_TIME"
    if not bt.exists(): return "BACKUP_TIME 없음 — 개발 서버가 아직 새 방식으로 백업하지 않음(기존 DB 로 계속 서비스)"
    marker = bt.read_text(encoding="utf-8").strip()                     # 1행 백업이 끝난 시각, 2행 만든 컴퓨터
    when = marker.splitlines()[0]
    STATE.mkdir(parents=True, exist_ok=True)
    maker = (marker.splitlines() + [""])[1]
    own = maker == socket.gethostname()
    seen = LAST.exists() and LAST.read_text(encoding="utf-8").strip() == marker
    if not force and (own or seen):
        if PENDING.exists(): return "지난번에 못 끝낸 일 마저 함: " + finish_pending()
        if own: return f"마지막 백업({when})은 이 컴퓨터가 만든 것 — 지금 DB 가 더 새것이라 복원하지 않음(개발 서버의 백업을 기다림)"
        return f"새 백업 없음(마지막 백업 시각 {when})"

    # 1. 새 백업이 있으면 먼저 소스를 최신으로, 바뀌었으면 새 코드로 다시 실행
    restart = os.environ.get(RESTART_ENV) == "1"
    if RESTART_ENV not in os.environ:
        changed, need, msg = pull_source()
        print("서비스 동기화:", msg, flush=True)
        if changed:
            os.environ[RESTART_ENV] = "1" if need else "0"
            os.execvp("uv", ["uv", "run", "python", str(ROOT / "service_sync.py"), *sys.argv[1:]])
    if PENDING.exists(): restart = restart or json.loads(PENDING.read_text(encoding="utf-8")).get("restart", False)
    PENDING.write_text(json.dumps({"restart": restart}), encoding="utf-8")   # 여기부터 끊겨도 재시작 필요 여부를 잃지 않게
    ok, info = restore(out, marker)                                     # 2. DB 복원
    if not ok: return info
    return f"복원 완료({info}행, 백업 시각 {when}) · " + finish_pending()    # 3·4. HTML, 필요하면 재시작


def notify(message, failed):
    """새 백업을 반영했거나 새로운 실패가 생겼을 때만 결과 메일(mailreport.py). 10분마다 같은 실패를 반복해 보내지 않는다."""
    import mailreport
    mark = STATE / "mail_error"
    if failed:
        if mark.exists() and mark.read_text(encoding="utf-8") == message: return
    else:
        mark.unlink(missing_ok=True)
        if not message.startswith(("복원 완료", "지난번에 못 끝낸 일")): return
    sent = mailreport.safe_report(log=str(ROOT / "logs" / "service.log"), tail=200, note=message, exit_code=1 if failed else 0)
    if failed and sent: STATE.mkdir(parents=True, exist_ok=True); mark.write_text(message, encoding="utf-8")


if __name__ == "__main__":
    try: message = run("--force" in sys.argv)
    except Exception as e:
        print("서비스 동기화 실패:", repr(e), flush=True)
        if role.role() == "service": notify(f"서비스 동기화 실패: {e!r}", True)
        raise
    print("서비스 동기화:", message, flush=True)
    if role.role() == "service": notify(message, any(w in message for w in ("실패", "불일치")))
