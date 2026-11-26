"""DB 백업/복구 (git 에 올릴 수 있는 텍스트 형식).

  uv run dbbackup.py dump [백업폴더]              # DB -> 백업폴더 (schema.sql + 표마다 <표>.jsonl)
  uv run dbbackup.py keep-previous                 # DB 를 갱신하기 직전 상태를 data/watchlater.db.bak 하나로 복사(날짜별로 쌓지 않고 덮어씀)
  uv run dbbackup.py restore 백업폴더 새DB경로      # 백업 -> 새 SQLite 파일 (이미 있으면 거부)
  uv run dbbackup.py verify [백업폴더]             # 지금 DB 와 백업이 같은지 비교
  uv run dbbackup.py sync [백업폴더]               # dump + README.md·HISTORY.md 갱신 + git commit + push (run_skill.sh 끝에서 호출; push 까지 못 하면 종료코드 1)

형식: 표 하나 = 파일 하나, 행 하나 = 한 줄(JSON), 기본키 순 정렬. 그래서 git 은 바뀐 줄만 diff·압축한다.
표 하나의 덤프가 40MB 를 넘으면(GitHub 은 파일 하나 100MB 초과 push 를 거부) <표>.s00.jsonl, .s01 … 로 나눈다 — 조각 수는 SHARDS.json 에 기록하고 줄이지 않으며,
행은 기본키 해시로 조각이 정해져 행이 늘어도 기존 행은 제자리라 git diff 가 작다. restore·verify 는 조각 여부를 알아서 처리한다.
기본 백업폴더: 환경변수 YT_BACKUP_DIR 또는 ~/yt-watcher-later-backup  (※ 공개 저장소가 아닌 별도 비공개 저장소 권장 — 개인 의견·시청 기록·자막 포함)
"""
import datetime, glob, json, math, os, pathlib, re, sqlite3, subprocess, sys, zlib
import db as D

DEFAULT = pathlib.Path(os.environ.get("YT_BACKUP_DIR", pathlib.Path.home() / "yt-watcher-later-backup"))

# GitHub 는 파일 하나가 100MB 를 넘으면 push 를 거부한다(50MB 부터 경고). 표 하나가 이 크기에 다가가기 전에 미리 여러 파일로 나눈다.
SHARD_AT = 40 * 1024 * 1024        # 표 하나의 덤프가 이 크기를 넘으면 조각으로 나누기 시작
SHARD_TARGET = 25 * 1024 * 1024    # 조각 하나가 이 크기 안팎이 되도록 개수를 정한다(2의 거듭제곱)
SHARD_FILE = "SHARDS.json"         # {표: 조각 수} — 조각 수는 줄이지 않는다(같은 행이 늘 같은 조각에 들어가야 git diff 가 작다)

def _tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

def _rows(con, t):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
    pk = [r[1] for r in sorted(con.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5]]
    order = ",".join(pk) if pk else "rowid"
    return cols, con.execute(f"SELECT {','.join(cols)} FROM {t} ORDER BY {order}")

def _line(cols, row):
    return json.dumps(dict(zip(cols, row)), ensure_ascii=False, separators=(",", ":"), sort_keys=False)

def dump(out=None, con=None):
    out = pathlib.Path(out or DEFAULT); out.mkdir(parents=True, exist_ok=True)
    con = con or sqlite3.connect(D.DB_PATH); n = {}
    ddl = [r[0] + ";" for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name")]
    (out / "schema.sql").write_text("\n".join(ddl) + "\n", encoding="utf-8")
    keep = {"schema.sql"}
    marker = out / SHARD_FILE
    try: shards = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
    except Exception: shards = {}
    for t in _tables(con):
        cols, cur = _rows(con, t); pkn = [r[1] for r in sorted(con.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5]]
        lines = [(_line(cols, row), "|".join(str(row[cols.index(k)]) for k in pkn) if pkn else "") for row in cur]
        size = sum(len(l.encode("utf-8")) + 1 for l, _ in lines)
        k = max(shards.get(t, 1), 1 if size <= SHARD_AT else 2 ** math.ceil(math.log2(max(2, size / SHARD_TARGET))))
        if k > 1: shards[t] = k
        names = [f"{t}.jsonl"] if k == 1 else [f"{t}.s{i:02d}.jsonl" for i in range(k)]
        bucket = {nm: [] for nm in names}
        for l, key in lines: bucket[names[0] if k == 1 else names[zlib.crc32(key.encode("utf-8")) % k]].append(l)   # 기본키 해시로 조각을 정해 행이 늘어도 기존 행은 제자리
        for nm in names:
            with open(out / nm, "w", encoding="utf-8", newline="\n") as f:
                for l in bucket[nm]: f.write(l + "\n")
            keep.add(nm)
        n[t] = len(lines)
    if shards: marker.write_text(json.dumps(shards, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    for p in out.glob("*.jsonl"):                      # 없어진 표·옛 조각 구성의 파일 정리
        if p.name not in keep: p.unlink()
    return n

def _files(src, t):
    """표 t 의 덤프 파일들(조각 나뉨 여부와 무관)."""
    src = pathlib.Path(src); one = src / f"{t}.jsonl"
    return [one] if one.exists() else sorted(src.glob(f"{t}.s[0-9][0-9].jsonl"))

def _read(src, t):
    out = []
    for p in _files(src, t): out += [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out

def restore(src, dest):
    src, dest = pathlib.Path(src), pathlib.Path(dest)
    if dest.exists(): raise SystemExit(f"이미 있습니다(덮어쓰지 않음): {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dest); n = {}
    con.executescript((src / "schema.sql").read_text(encoding="utf-8"))
    for t in _tables(con):
        if not _files(src, t): continue
        c = 0
        for ln in _read(src, t):
            d = json.loads(ln); ks = list(d)
            con.execute(f"INSERT INTO {t}({','.join(ks)}) VALUES({','.join('?' * len(ks))})", [d[k] for k in ks]); c += 1
        n[t] = c
    con.commit(); con.close()
    return n

def verify(src=None):
    src = pathlib.Path(src or DEFAULT); con = sqlite3.connect(D.DB_PATH); bad = []
    for t in _tables(con):
        cols, cur = _rows(con, t); fs = _files(src, t)
        have = _read(src, t) if fs else None
        now = [_line(cols, r) for r in cur]
        if have is not None and len(fs) > 1: have = sorted(have); now = sorted(now)     # 조각으로 나뉜 표는 순서 대신 내용만 비교
        if have != now: bad.append(f"{t}: DB {len(now)}행 / 백업 {'없음' if have is None else len(have)}행" + ("" if have is None or len(have) != len(now) else " (내용 다름)"))
    return bad

def _git(out, *args, timeout=600):
    return subprocess.run(["git", "-C", str(out), *args], capture_output=True, text=True, timeout=timeout)

README = """# yt-watcher-later DB 백업

`yt-watcher-later` 프로젝트의 SQLite DB(`data/watchlater.db`)를 **텍스트로 저장**한 비공개 백업 저장소입니다.
의견·시청 기록·자막이 들어 있으므로 공개하면 안 됩니다.

## 마지막 백업
- 시각: **{now}**
- 원본 DB: `data/watchlater.db` ({size:.1f} MB), 프로젝트 커밋 `{rev}`
- 총 {total}행 / {ntab}개 표
- 이번 백업에서 바뀐 것: {changed}

| 표 | 행 수 |
|---|---:|
{rows}

## 최근 백업 기록 (전체는 [HISTORY.md](HISTORY.md))
{recent}

## 파일 구성
- `schema.sql` — 표·인덱스 정의
- `<표>.jsonl` — 표마다 한 파일, 행 하나가 한 줄(JSON), 기본키 순 정렬. 같은 DB 면 항상 같은 내용이라 git 에는 **바뀐 줄만** 기록됩니다.
- `<표>.sNN.jsonl`, `SHARDS.json` — 표 하나가 40MB 를 넘으면 자동으로 여러 조각으로 나눕니다(GitHub 파일 100MB 한도 대비). 복구·검증은 조각을 자동으로 합칩니다.
- `BACKUP_TIME` — 백업이 끝난 시각(1행)과 만든 컴퓨터(2행). 매 백업마다 같은 commit 으로 push 된다. 서비스 서버는 이 시각이 지난번과 다르면 DB 를 복원하고, 마지막 백업이 언제 만들어졌는지·문제가 어디서 생겼는지 알아보는 데도 쓴다
- `HISTORY.md` — 백업할 때마다 한 줄 추가(언제, 몇 행, 무엇이 바뀌었는지)

## 언제 갱신되나
매일 01:00 cron(`run_skill.sh --agy`)이 끝날 때 `dbbackup.py sync` 가 덤프 → 이 README·HISTORY 갱신 → commit → push 를 합니다.
push 가 실패하면(네트워크 등) 그 commit 은 로컬에 남고 다음 실행 때 함께 push 됩니다. 수동 실행: 프로젝트에서 `make backup-push`.

## 복구 방법
```
git clone <이 저장소> ~/yt-watcher-later-backup
cd ~/code/yt-watcher-later
uv run dbbackup.py restore ~/yt-watcher-later-backup /tmp/restored.db   # 새 파일로 복구(기존 파일은 덮어쓰지 않음)
uv run dbbackup.py verify ~/yt-watcher-later-backup                     # 현재 DB 와 비교
```
복구본을 확인한 뒤 서비스(yt-opinion)와 cron 을 멈추고 `data/watchlater.db` 와 교체하세요.
"""

def sync(out=None):
    """덤프 -> README/HISTORY 갱신 -> commit -> push. 어느 단계가 실패해도 예외 대신 메시지를 돌려준다(일일 실행을 막지 않음)."""
    out = pathlib.Path(out or DEFAULT)
    if not (out / ".git").exists(): return "백업 폴더가 git 저장소가 아니어서 commit/push 생략"
    n = dump(out); now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st = _git(out, "status", "--porcelain", "--", "*.jsonl", "schema.sql").stdout.split("\n")
    changed = sorted({re.sub(r"\.s\d\d$", "", ln[3:].rsplit(".jsonl", 1)[0]) for ln in st if ln.strip().endswith((".jsonl", "schema.sql"))})
    stat = _git(out, "diff", "--numstat", "HEAD", "--", "*.jsonl").stdout.split("\n")   # 줄 단위 변경량(추가/삭제)
    add = sum(int(p[0]) for p in (l.split("\t") for l in stat if l) if p[0].isdigit()); dele = sum(int(p[1]) for p in (l.split("\t") for l in stat if l) if p[1].isdigit())
    ch = (", ".join(changed) + f" (+{add}/-{dele}줄)") if changed else "변경 없음"
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "-"
    hist = out / "HISTORY.md"
    if not hist.exists(): hist.write_text("# 백업 기록\n\n| 시각 | 총 행 수 | 바뀐 표 |\n|---|---:|---|\n", encoding="utf-8")
    with open(hist, "a", encoding="utf-8") as f: f.write(f"| {now} | {sum(n.values())} | {ch} |\n")
    import socket
    (out / "BACKUP_TIME").write_text(f"{now}\n{socket.gethostname()}\n", encoding="utf-8")   # 백업이 끝난 시각 — 같은 commit·push 로 올라가고, 서비스 서버는 이 값이 지난번과 다르면 DB 를 복원한다
    recent = "\n".join(hist.read_text(encoding="utf-8").splitlines()[-10:][::-1])
    (out / "README.md").write_text(README.format(now=now, size=pathlib.Path(D.DB_PATH).stat().st_size / 1e6, rev=rev, total=sum(n.values()), ntab=len(n), changed=ch,
        rows="\n".join(f"| `{t}` | {c} |" for t, c in sorted(n.items())), recent="| 시각 | 총 행 수 | 바뀐 표 |\n|---|---:|---|\n" + "\n".join(l for l in recent.splitlines() if l.startswith("| 20"))), encoding="utf-8")
    _git(out, "add", "-A")
    r = _git(out, "commit", "-q", "-m", f"DB 백업 {now}: {ch}")
    if r.returncode: return f"commit 실패: {(r.stderr or r.stdout).strip()[:200]}"
    msg = f"commit 완료 ({ch})"
    try: _git(out, "gc", "--quiet", timeout=600)      # commit 직후 파일은 통째로(느슨한 객체) 저장돼 있다 — gc 로 묶어야 바뀐 줄만 델타로 압축된다(실측 50MB → 6MB)
    except Exception: pass
    try: p = _git(out, "push", timeout=600)
    except subprocess.TimeoutExpired: return msg + " / push 시간 초과(다음 실행에서 재시도)"
    return msg + (" / push 완료" if p.returncode == 0 else f" / push 실패(다음 실행에서 재시도): {(p.stderr or p.stdout).strip()[-200:]}")

def keep_previous(db=None):
    """DB 갱신(일일 실행·복원) 직전의 DB 를 같은 폴더의 <이름>.bak 한 개로 복사한다(덮어씀). SQLite backup API 라 쓰는 중이어도 일관된 사본이 된다."""
    src = pathlib.Path(db or D.DB_PATH)
    if not src.exists(): return None
    dst, tmp = src.with_name(src.name + ".bak"), src.with_name(src.name + ".bak.tmp")
    if tmp.exists(): tmp.unlink()
    a, b = sqlite3.connect(src), sqlite3.connect(tmp)
    try: a.backup(b)
    finally: a.close(); b.close()
    os.replace(tmp, dst)                                    # 복사가 끝난 뒤에만 이전 .bak 을 바꾼다
    return dst


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("dump", "restore", "verify", "sync", "keep-previous"): raise SystemExit(__doc__)
    if a[0] == "keep-previous": print("갱신 전 DB 사본:", keep_previous() or "DB 없음")
    elif a[0] == "dump":
        n = dump(a[1] if len(a) > 1 else None); print(f"백업 완료 → {a[1] if len(a) > 1 else DEFAULT}  ({len(n)}개 표, {sum(n.values())}행)")
    elif a[0] == "sync":
        m = sync(a[1] if len(a) > 1 else None); print("DB 백업:", m); sys.exit(0 if "push 완료" in m else 1)
    elif a[0] == "restore":
        if len(a) < 3: raise SystemExit("사용: restore 백업폴더 새DB경로")
        n = restore(a[1], a[2]); print(f"복구 완료 → {a[2]}  ({len(n)}개 표, {sum(n.values())}행)")
    else:
        bad = verify(a[1] if len(a) > 1 else None); print("백업이 현재 DB 와 같습니다" if not bad else "다른 표:\n  " + "\n  ".join(bad)); sys.exit(1 if bad else 0)
