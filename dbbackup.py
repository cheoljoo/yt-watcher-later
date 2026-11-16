"""DB 백업/복구 (git 에 올릴 수 있는 텍스트 형식).

  uv run dbbackup.py dump [백업폴더]              # DB -> 백업폴더 (schema.sql + 표마다 <표>.jsonl)
  uv run dbbackup.py restore 백업폴더 새DB경로      # 백업 -> 새 SQLite 파일 (이미 있으면 거부)
  uv run dbbackup.py verify [백업폴더]             # 지금 DB 와 백업이 같은지 비교

형식: 표 하나 = 파일 하나, 행 하나 = 한 줄(JSON), 기본키 순 정렬. 그래서 git 은 바뀐 줄만 diff·압축한다.
기본 백업폴더: 환경변수 YT_BACKUP_DIR 또는 ~/yt-watcher-later-backup  (※ 공개 저장소가 아닌 별도 비공개 저장소 권장 — 개인 의견·시청 기록·자막 포함)
"""
import json, os, pathlib, sqlite3, sys
import db as D

DEFAULT = pathlib.Path(os.environ.get("YT_BACKUP_DIR", pathlib.Path.home() / "yt-watcher-later-backup"))

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
    for t in _tables(con):
        cols, cur = _rows(con, t)
        with open(out / f"{t}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            c = 0
            for row in cur:
                f.write(_line(cols, row) + "\n"); c += 1
        n[t] = c; keep.add(f"{t}.jsonl")
    for p in out.glob("*.jsonl"):                      # 없어진 표의 옛 파일 정리
        if p.name not in keep: p.unlink()
    return n

def restore(src, dest):
    src, dest = pathlib.Path(src), pathlib.Path(dest)
    if dest.exists(): raise SystemExit(f"이미 있습니다(덮어쓰지 않음): {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dest); n = {}
    con.executescript((src / "schema.sql").read_text(encoding="utf-8"))
    for t in _tables(con):
        p = src / f"{t}.jsonl"
        if not p.exists(): continue
        c = 0
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip(): continue
                d = json.loads(ln); ks = list(d)
                con.execute(f"INSERT INTO {t}({','.join(ks)}) VALUES({','.join('?' * len(ks))})", [d[k] for k in ks]); c += 1
        n[t] = c
    con.commit(); con.close()
    return n

def verify(src=None):
    src = pathlib.Path(src or DEFAULT); con = sqlite3.connect(D.DB_PATH); bad = []
    for t in _tables(con):
        cols, cur = _rows(con, t); p = src / f"{t}.jsonl"
        have = p.read_text(encoding="utf-8").splitlines() if p.exists() else None
        now = [_line(cols, r) for r in cur]
        if have != now: bad.append(f"{t}: DB {len(now)}행 / 백업 {'없음' if have is None else len(have)}행" + ("" if have is None or len(have) != len(now) else " (내용 다름)"))
    return bad

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("dump", "restore", "verify"): raise SystemExit(__doc__)
    if a[0] == "dump":
        n = dump(a[1] if len(a) > 1 else None); print(f"백업 완료 → {a[1] if len(a) > 1 else DEFAULT}  ({len(n)}개 표, {sum(n.values())}행)")
    elif a[0] == "restore":
        if len(a) < 3: raise SystemExit("사용: restore 백업폴더 새DB경로")
        n = restore(a[1], a[2]); print(f"복구 완료 → {a[2]}  ({len(n)}개 표, {sum(n.values())}행)")
    else:
        bad = verify(a[1] if len(a) > 1 else None); print("백업이 현재 DB 와 같습니다" if not bad else "다른 표:\n  " + "\n  ".join(bad)); sys.exit(1 if bad else 0)
