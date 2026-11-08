"""벤치마크 임시 DB(/tmp/yt-bench/<도구>/data/watchlater.db)의 분석 결과를 운영 DB 의 analysis_runs 에 옮긴다.
  uv run import_bench.py agy "Gemini 3.8 Flash (Medium)"      uv run import_bench.py claude sonnet"""
import json, pathlib, random, sqlite3, sys
import db as D
tool, model = sys.argv[1], sys.argv[2]
src = sqlite3.connect(pathlib.Path("/tmp/yt-bench") / tool / "data" / "watchlater.db"); src.row_factory = sqlite3.Row
con = D.connect(); n = 0
# bench_usage.py 와 같은 방식으로 표본 ID 를 다시 뽑는다(seed·개수 인자 가능)
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1; cnt = int(sys.argv[4]) if len(sys.argv) > 4 else 30
ids = [r[0] for r in con.execute("SELECT id FROM videos WHERE status='done' AND transcript IS NOT NULL ORDER BY id")]
random.Random(seed).shuffle(ids); ids = set(ids[:cnt])
for r in src.execute("SELECT id, processed_at, analysis_json FROM videos WHERE status='done' AND analysis_json IS NOT NULL"):
    if r["id"] in ids:
        D.add_run(con, r["id"], tool, model, json.loads(r["analysis_json"]), r["processed_at"], "benchmark"); n += 1
con.commit(); print(f"{tool}/{model}: {n}개 옮김")
