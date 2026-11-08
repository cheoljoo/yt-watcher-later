"""Claude Code vs agy 사용량(quota %) 비교용 벤치마크.
운영 DB 는 건드리지 않고, 임시 폴더에 프로젝트 사본과 '이미 분석된 영상 N개를 미분석으로 되돌린 DB'를 만들어
스킬(yt-daily)의 영상 분석 단계만 각 도구로 실행한 뒤 /usage 의 증가분을 보여준다.
  uv run bench_usage.py --n 30 --tools claude,agy [--seed 1] [--agy-model MODEL]"""
import argparse, json, pathlib, re, shutil, sqlite3, subprocess, time, os

ROOT = pathlib.Path(__file__).resolve().parent

def usage(tool):
    """-> {라벨: 사용한 %}  (agy 는 남은 %를 100-에서 환산)"""
    if tool == "claude":
        out = subprocess.run(["claude", "-p", "/usage"], capture_output=True, text=True, timeout=900).stdout
        return {k: int(v) for k, v in re.findall(r"(Current session|Current week \(all models\)): (\d+)% used", out)}
    out = subprocess.run(["agy", "-p", "/usage"], capture_output=True, text=True, timeout=300).stdout
    r = {}
    for line in out.splitlines():
        m = re.match(r"(.+?)\t(.+?)\s+Remaining\t(\d+)%", line)
        if m: r[f"{m.group(1)} / {m.group(2)}"] = 100 - int(m.group(3))
    return r

def make_scratch(dst, ids):
    if dst.exists(): shutil.rmtree(dst)
    dst.mkdir(parents=True); (dst / "data").mkdir()
    for f in list(ROOT.glob("*.py")) + [ROOT / "config.toml", ROOT / "pyproject.toml", ROOT / "uv.lock", ROOT / ".python-version", ROOT / "run_skill.sh"]:
        if f.exists(): shutil.copy(f, dst / f.name)
    shutil.copytree(ROOT / ".claude", dst / ".claude")
    (dst / ".agents").mkdir(); (dst / ".agents" / "skills").symlink_to("../.claude/skills")
    if (ROOT / ".venv").exists(): (dst / ".venv").symlink_to(ROOT / ".venv")
    shutil.copy(ROOT / "data" / "watchlater.db", dst / "data" / "watchlater.db")
    con = sqlite3.connect(dst / "data" / "watchlater.db"); con.row_factory = sqlite3.Row
    work = dst / "data" / "_work" / "col"; work.mkdir(parents=True)
    for i, vid in enumerate(ids):
        r = con.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
        meta_keys = ["upload_date", "channel", "channel_id", "channel_url", "uploader_id", "duration_sec", "view_count", "like_count", "comment_count",
                     "yt_categories", "yt_tags", "description", "thumbnail", "live_status"]
        v = {"id": vid, "url": r["url"], "title": r["title"], "pos": i, "owner": r["owner"], "playlist": r["playlist_name"]}
        (work / f"{vid}.json").write_text(json.dumps({"v": v, "col": {"meta": {k: r[k] for k in meta_keys}, "lang": r["transcript_lang"], "transcript": r["transcript"]}}, ensure_ascii=False), encoding="utf-8")
        src = ROOT / "data" / vid
        (dst / "data" / vid).mkdir()
        for f in src.glob("*.info.json"): shutil.copy(f, dst / "data" / vid / f.name)
        for t in ("people", "links", "tags", "checks"): con.execute(f"DELETE FROM {t} WHERE video_id=?", (vid,))
        con.execute("DELETE FROM videos WHERE id=?", (vid,))
    con.commit(); con.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tools", default="claude,agy"); ap.add_argument("--agy-model", default="")
    a = ap.parse_args()
    con = sqlite3.connect(ROOT / "data" / "watchlater.db")
    ids = [r[0] for r in con.execute("SELECT id FROM videos WHERE status='done' AND transcript IS NOT NULL ORDER BY id")]
    import random; random.Random(a.seed).shuffle(ids); ids = ids[:a.n]
    chars = sum(con.execute("SELECT length(transcript) FROM videos WHERE id=?", (i,)).fetchone()[0] for i in ids)
    print(f"표본 {len(ids)}개 (seed {a.seed}), 자막 합계 {chars:,}자, 평균 {chars // len(ids):,}자", flush=True)
    results = {}
    for tool in a.tools.split(","):
        dst = pathlib.Path(os.environ.get("BENCH_DIR", "/tmp/yt-bench")) / tool
        make_scratch(dst, ids)
        env = dict(os.environ, YT_STAGES="video", ROUNDS="1", BUDGET="2000000", MAX_ANALYZE=str(a.n))
        if a.agy_model: env["AGY_MODEL"] = a.agy_model
        b = usage(tool); t0 = time.time()
        cmd = ["bash", "-c", f"cd {dst} && ./run_skill.sh --{tool} --no-collect --no-finish"]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        dt = time.time() - t0
        a_ = usage(tool)
        done = sqlite3.connect(dst / "data" / "watchlater.db").execute("SELECT count(*) FROM videos WHERE status='done' AND id IN (%s)" % ",".join("?" * len(ids)), ids).fetchone()[0]
        results[tool] = dict(done=done, seconds=round(dt), before=b, after=a_, delta={k: a_.get(k, 0) - b.get(k, 0) for k in a_}, log=(r.stdout + r.stderr)[-600:])
        print(f"\n[{tool}] 완료 {done}/{len(ids)}개, {dt:.0f}초\n  사용량 변화: " + ", ".join(f"{k} {b.get(k, 0)}%→{a_[k]}% (+{a_[k] - b.get(k, 0)})" for k in a_ if a_[k] != b.get(k, 0) or 'Five' in k or 'session' in k), flush=True)
    pathlib.Path("logs").mkdir(exist_ok=True)
    pathlib.Path("logs/bench-usage.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__": main()
