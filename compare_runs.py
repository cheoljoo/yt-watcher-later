"""같은 영상에 대한 두 분석 실행(도구/모델)의 결과가 얼마나 다른지 요약한다.
  uv run compare_runs.py claude:production agy:benchmark      (형식 engine:source)"""
import json, sqlite3, sys, statistics as st
import db as D
a, b = (x.split(":") for x in sys.argv[1:3])
con = D.connect()
def runs(engine, source):
    return {r["video_id"]: r for r in con.execute("SELECT * FROM analysis_runs WHERE engine=? AND source=?", (engine, source))}
A, B = runs(*a), runs(*b); ids = sorted(set(A) & set(B))
def words(res): return {w.strip().lower() for w in res.get("keywords", [])}
def jac(x, y): return len(x & y) / len(x | y) if x | y else 1
cat = sum(A[i]["category"] == B[i]["category"] for i in ids); sub = sum(A[i]["subtag"] == B[i]["subtag"] for i in ids)
kw = [jac(words(json.loads(A[i]["analysis_json"])), words(json.loads(B[i]["analysis_json"]))) for i in ids]
print(f"비교 {a[0]}({a[1]}) vs {b[0]}({b[1]}): 공통 {len(ids)}개")
print(f"  카테고리 일치 {cat}/{len(ids)}, 2단계 태그 일치 {sub}/{len(ids)}, 키워드 자카드 평균 {st.mean(kw):.2f}")
for k, label in (("n_summary", "요약 항목"), ("n_checks", "확인 항목"), ("n_links", "링크"), ("n_people", "인물")):
    x, y = [A[i][k] for i in ids], [B[i][k] for i in ids]
    print(f"  {label} 평균 {st.mean(x):.1f} vs {st.mean(y):.1f}  (같은 개수 {sum(p == q for p, q in zip(x, y))}/{len(ids)})")
ln = lambda r: len(json.loads(r["analysis_json"]).get("one_liner", "")) 
print(f"  한줄요약 길이 평균 {st.mean(ln(A[i]) for i in ids):.0f} vs {st.mean(ln(B[i]) for i in ids):.0f}자")
print("  분류가 다른 영상:")
for i in ids:
    if A[i]["category"] != B[i]["category"]: print(f"    {i}: {A[i]['category']}/{A[i]['subtag']}  ↔  {B[i]['category']}/{B[i]['subtag']}")
