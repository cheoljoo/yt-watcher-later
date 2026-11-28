"""서비스 서버의 inbox — 사용자가 누른 입력(의견 저장·액션·액션 메모·별표)을 파일에 한 줄씩 모은다.

  data/inbox/current.jsonl            지금 쌓는 중인 파일
  data/inbox/inbox-<시각>-<난수>.jsonl  개발 서버가 가져가려고 닫아 둔 파일(가져간 쪽이 ack 하면 삭제)

규칙: 쌓기만 한다(덮어쓰거나 비우지 않는다). 가져갈 때는 current 를 이름만 바꿔 닫고 새 파일에 이어 쓰므로, 전송 중에 눌린 입력은 새 파일에 남는다.
삭제는 ack 한 '닫힌 파일'만 한다. 개발 서버는 ssh 로 `inbox.py close`(닫기+목록) → scp(가져오기) → `inbox.py ack 이름…`(삭제) 를 호출한다. 이벤트 한 줄: {"id","ts","type":TYPES 중 하나,"vid","text","on","host"}"""
import fcntl, json, os, pathlib, re, secrets, socket, uuid
import db as D

DIR = pathlib.Path(os.environ.get("YT_INBOX_DIR", pathlib.Path(__file__).resolve().parent / "data" / "inbox"))
CUR = DIR / "current.jsonl"
NAME = re.compile(r"^inbox-[0-9T:-]+-[0-9a-f]+\.jsonl$")
TYPES = ("opinion", "action", "action_comment", "action_done", "opinion_action", "opinion_action_comment", "opinion_action_done", "star")


class _Lock:
    def __enter__(self):
        DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(DIR / ".lock", "w"); fcntl.flock(self.f, fcntl.LOCK_EX); return self
    def __exit__(self, *a): fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()


def append(type_, vid, text=None, on=None):
    """이벤트 한 줄을 파일 끝에 쌓는다(즉시 디스크에 반영). 반환: 이벤트 id."""
    ev = {"id": uuid.uuid4().hex, "ts": D.now(), "type": type_, "vid": vid, "text": text, "on": on, "host": socket.gethostname()}
    with _Lock():
        with open(CUR, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    return ev["id"]


def close():
    """current 를 닫고(이름 변경) 닫힌 파일 이름 목록을 돌려준다(ack 안 된 예전 파일 포함). 개발 서버가 ssh 로 호출한다."""
    with _Lock():
        if CUR.exists() and CUR.stat().st_size:
            CUR.rename(DIR / f"inbox-{D.now().replace(' ', 'T')}-{secrets.token_hex(3)}.jsonl")
        return sorted(p.name for p in DIR.glob("inbox-*.jsonl") if NAME.match(p.name))


def take():
    """current 를 닫고(이름 변경) 닫힌 파일 전부의 내용을 돌려준다: [{"name", "lines":[이벤트…]}]. 아직 ack 안 된 예전 파일도 같이 준다."""
    with _Lock():
        if CUR.exists() and CUR.stat().st_size:
            CUR.rename(DIR / f"inbox-{D.now().replace(' ', 'T')}-{secrets.token_hex(3)}.jsonl")
        out = []
        for p in sorted(DIR.glob("inbox-*.jsonl")):
            if not NAME.match(p.name): continue
            evs = []
            for ln in p.read_text(encoding="utf-8").splitlines():
                try: evs.append(json.loads(ln))
                except ValueError: pass
            out.append({"name": p.name, "lines": evs})
        return out


def peek():
    """아직 안 가져간 입력을 닫거나 지우지 않고 읽기만 한다: [{"name", "lines":[이벤트…]}] (쌓인 순서)."""
    with _Lock():
        files = sorted(p for p in DIR.glob("inbox-*.jsonl") if NAME.match(p.name)) + ([CUR] if CUR.exists() else [])
        out = []
        for p in files:
            evs = []
            for ln in p.read_text(encoding="utf-8").splitlines():
                try: evs.append(json.loads(ln))
                except ValueError: pass
            out.append({"name": p.name, "lines": evs})
        return out


def ack(names):
    """받아 간 닫힌 파일을 지운다(이름 규칙에 맞는 것만). 반환: 지운 개수."""
    n = 0
    with _Lock():
        for nm in names:
            if NAME.match(str(nm)) and (DIR / nm).exists(): (DIR / nm).unlink(); n += 1
    return n


def pending():
    """(열린 파일의 이벤트 수, 닫힌 파일 수) — 상태 확인용."""
    cur = sum(1 for _ in open(CUR, encoding="utf-8")) if CUR.exists() else 0
    return cur, len(list(DIR.glob("inbox-*.jsonl"))) if DIR.exists() else 0


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if a[:1] == ["close"]: print(json.dumps({"dir": str(DIR.resolve()), "names": close()}))      # 개발 서버가 ssh 로 호출: inbox 폴더(절대경로)와 닫힌 파일 이름 목록(JSON)
    elif a[:1] == ["ack"]: print(json.dumps({"deleted": ack(a[1:])}))      # 개발 서버가 ssh 로 호출: 반영한 닫힌 파일 삭제
    else:
        c, k = pending(); print(f"열린 inbox 이벤트 {c}건 · 닫힌 파일 {k}개 ({DIR})")
