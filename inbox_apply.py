"""개발 서버: 서비스 서버(psncs)의 inbox 를 ssh/scp 로 가져와 DB 에 반영한다(run_skill.sh 의 dev 역할이 작업 맨 앞에서 호출).

  uv run inbox_apply.py            # ssh 로 서비스 서버 inbox 닫기 → scp 로 가져오기 → DB 반영 → ssh 로 반영한 파일 삭제
  uv run inbox_apply.py --dry      # 서비스 서버에 쌓인 입력 개수만 확인(아무것도 닫거나 가져오거나 지우지 않음) — 연결 확인용

접속 정보는 개발 서버 프로젝트 폴더의 .env (KEY=값 줄, 권한 600, git 에 올리지 않음):
  PSNCS_HOST          서비스 서버 주소 (예: psncs.iptime.org)                 ← 필수
  PSNCS_ID            ssh 사용자 (PSNCS_USER 도 가능)                        ← 필수
  PSNCS_YT_WATCH_DIR  서비스 서버의 프로젝트 폴더 (PSNCS_DIR 도 가능)         ← 필수
  PSNCS_PORT          ssh 포트 (없으면 ssh 기본값)
  PSNCS_PASSWD        비밀번호 접속용(있으면 sshpass 가 필요). 없으면 ssh 키로 접속(BatchMode). 가능하면 키 접속을 권한다
  PSNCS_SSH_OPTS      ssh/scp 에 더 줄 옵션 (예: -i ~/.ssh/id_ed25519)
.env 가 없거나 필수 값이 하나라도 없으면 오류(종료코드 2)를 낸다 — run_skill.sh 는 이 오류에서 개발 서버 실행을 멈춘다(잘못된 설정을 조용히 넘기지 않기 위해).
접속·전송이 실패하면(종료코드 1) 이번 실행은 inbox 없이 계속하고 다음 실행에서 이어 받는다.

순서와 안전: ① ssh `inbox.py close` — 쌓던 파일을 닫고(이름 변경) 닫힌 파일 목록을 받는다. 이후 도착하는 입력은 새 파일에 쌓인다.
② scp 로 닫힌 파일을 가져온다. ③ 이벤트 id 로 중복을 걸러 시각순(같은 초는 쌓인 순서)으로 opinions.py 의 저장 함수로 DB 에 반영한다(그래서 'AI 의견이 달린 항목은 수정 불가' 규칙이 그대로 적용되고, 거부된 것은 표 inbox_applied 에 사유가 남는다).
④ DB commit 이 끝난 뒤에만 ssh `inbox.py ack 이름…` 으로 서비스 서버의 그 파일을 지운다. 중간에 끊겨도 다음 실행이 같은 파일을 다시 받아 중복 없이 이어 반영한다."""
import json, pathlib, re, shlex, shutil, subprocess, sys, tempfile
import db as D, marketdata as M, opinions as O

NAME = re.compile(r"^inbox-[0-9T:-]+-[0-9a-f]+\.jsonl$")


class ConfigError(Exception): pass


# 필수: 주소·사용자·서비스 서버의 프로젝트 폴더. 사용자·폴더는 PSNCS_ID / PSNCS_YT_WATCH_DIR 이름(또는 PSNCS_USER / PSNCS_DIR)으로 적는다.
ALIASES = {"host": ("PSNCS_HOST",), "user": ("PSNCS_ID", "PSNCS_USER"), "dir": ("PSNCS_YT_WATCH_DIR", "PSNCS_DIR")}


def _first(names):
    for n in names:
        v = M.secret(n)
        if v: return v
    return None


def conf():
    """접속 정보. 개발 서버에는 프로젝트 폴더의 .env 가 반드시 있어야 하고, 주소·사용자·폴더가 모두 있어야 한다(없으면 ConfigError — 기본값으로 추측하지 않는다).
    PSNCS_PASSWD 가 있으면 sshpass(-e)로 비밀번호 접속, 없으면 키 접속(BatchMode)."""
    envf = pathlib.Path(__file__).resolve().parent / ".env"
    if not envf.exists(): raise ConfigError(f".env 파일이 없습니다: {envf}  (개발 서버에 PSNCS_HOST·PSNCS_ID·PSNCS_YT_WATCH_DIR 을 적어 만들어 주세요)")
    v = {k: _first(n) for k, n in ALIASES.items()}
    miss = [" 또는 ".join(ALIASES[k]) for k in ALIASES if not v[k]]
    if miss: raise ConfigError(f".env 에 {', '.join(miss)} 값이 없습니다 ({envf})")
    pw = M.secret("PSNCS_PASSWD")
    if pw and not shutil.which("sshpass"): raise ConfigError("PSNCS_PASSWD 를 쓰려면 sshpass 가 필요합니다: sudo apt install sshpass  (또는 ssh 키를 등록하고 PSNCS_PASSWD 를 지우세요)")
    return {"target": f"{v['user']}@{v['host']}", "port": M.secret("PSNCS_PORT"), "dir": v["dir"].rstrip("/"), "opts": shlex.split(M.secret("PSNCS_SSH_OPTS") or ""), "pw": pw}


def _ssh_args(c, prog):
    """ssh/scp 명령. 비밀번호가 있으면 sshpass -e (비밀번호는 명령줄이 아니라 환경변수로만 넘긴다), 없으면 BatchMode(키 접속)."""
    base = (["sshpass", "-e"] if c["pw"] else []) + [prog, "-o", "ConnectTimeout=20"] + ([] if c["pw"] else ["-o", "BatchMode=yes"]) + c["opts"]
    return base + (["-P" if prog == "scp" else "-p", str(c["port"])] if c["port"] else [])


def _env(c):
    import os
    return {**os.environ, "SSHPASS": c["pw"]} if c["pw"] else None


def remote(c, cmd, timeout=120):
    """서비스 서버에서 프로젝트 폴더로 이동해 명령 실행(uv 가 PATH 에 없는 비대화형 ssh 도 되도록 ~/.local/bin 추가). 표준출력을 돌려준다."""
    full = f'export PATH="$HOME/.local/bin:$PATH"; cd {c["dir"]} && {cmd}'
    r = subprocess.run(_ssh_args(c, "ssh") + [c["target"], full], capture_output=True, text=True, timeout=timeout, env=_env(c))
    if r.returncode: raise RuntimeError(f"ssh 실패({r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def fetch(c, rdir, names, dest):
    """닫힌 inbox 파일을 scp 로 dest 폴더에 가져온다. 반환: [{"name", "lines":[이벤트…]}]"""
    files = []
    for nm in names:
        if not NAME.match(nm): continue                                   # 이름 규칙에 맞는 것만(이상한 이름은 건드리지 않음)
        src = f'{c["target"]}:{rdir}/{nm}'
        r = subprocess.run(_ssh_args(c, "scp") + ["-q", src, str(dest / nm)], capture_output=True, text=True, timeout=300, env=_env(c))
        if r.returncode: raise RuntimeError(f"scp 실패 {nm}: {(r.stderr or r.stdout).strip()[-200:]}")
        evs = []
        for ln in (dest / nm).read_text(encoding="utf-8").splitlines():
            try: evs.append(json.loads(ln))
            except ValueError: pass
        files.append({"name": nm, "lines": evs})
    return files


def apply_event(con, ev):
    t, vid = ev.get("type"), str(ev.get("vid", ""))
    if t == "opinion": return O.save_mine(con, vid, ev.get("text") or "")
    if t == "action": return O.set_action(con, vid, bool(ev.get("on", True)))
    if t == "star": return O.set_star(con, vid, bool(ev.get("on", True)))
    if t == "action_comment": return O.save_action_comment(con, vid, ev.get("text") or "")
    if t == "action_done": return O.set_done(con, vid, bool(ev.get("on", True)))
    if t == "opinion_action": return O.set_opinion_action(con, vid, bool(ev.get("on", True)))
    if t == "opinion_action_comment": return O.save_action_comment(con, vid, ev.get("text") or "", "opinion")
    if t == "opinion_action_done": return O.set_done(con, vid, bool(ev.get("on", True)), "opinion")
    return False, f"알 수 없는 종류 {t}"


def apply_files(con, files):
    """받은 파일들의 이벤트를 시각순으로 반영한다. 반환: (새로 반영, 거부, 이미 반영돼 건너뜀)."""
    evs = sorted((e for f in files for e in f["lines"]), key=lambda e: e.get("ts", ""))      # 안정 정렬: 같은 초의 입력은 파일에 쌓인 순서 유지(표시 → 처리완료 순서가 바뀌면 거부된다)
    ok_n = bad_n = dup = 0
    for ev in evs:
        if con.execute("SELECT 1 FROM inbox_applied WHERE id=?", (ev["id"],)).fetchone(): dup += 1; continue
        try: ok, msg = apply_event(con, ev)
        except Exception as ex: ok, msg = False, f"오류 {ex}"[:200]
        con.execute("INSERT INTO inbox_applied(id,ts,type,vid,ok,msg,applied_at) VALUES(?,?,?,?,?,?,?)", (ev["id"], ev.get("ts"), ev.get("type"), ev.get("vid"), int(bool(ok)), msg, D.now()))
        ok_n += bool(ok); bad_n += not ok
    con.commit()
    return ok_n, bad_n, dup


def run(dry=False):
    c = conf()
    if dry:
        print("[dry] 서비스 서버 inbox:", remote(c, "uv run python inbox.py").strip(), f"· 접속 {c['target']}:{c['dir']}"); return 0
    got = json.loads(remote(c, "uv run python inbox.py close").strip().splitlines()[-1])         # ① 닫고 (inbox 폴더, 목록)
    names = got["names"]
    if not names: print("inbox: 가져올 파일 없음"); return 0
    with tempfile.TemporaryDirectory() as td:
        files = fetch(c, got["dir"], names, pathlib.Path(td))                                                # ② scp
    n = sum(len(f["lines"]) for f in files)
    con = D.connect()
    ok_n, bad_n, dup = apply_files(con, files)                                                   # ③ DB 반영(commit 까지)
    done = [f["name"] for f in files]
    remote(c, "uv run python inbox.py ack " + " ".join(shlex.quote(x) for x in done))             # ④ 반영한 파일만 삭제
    print(f"inbox: 파일 {len(files)}개 · 이벤트 {n}건 → 반영 {ok_n} · 거부 {bad_n} · 이미 반영 {dup} · 서비스 서버에서 삭제 완료")
    return ok_n


if __name__ == "__main__":
    try: run("--dry" in sys.argv)
    except ConfigError as ex:
        print("설정 오류:", ex, file=sys.stderr); sys.exit(2)
    except Exception as ex:
        print("inbox 가져오기 실패(이번 실행은 inbox 없이 계속, 다음 실행에서 이어 받음):", str(ex)[:300]); sys.exit(1)
