"""지표 값 이력 1회성 채우기: 시세 출처가 있는 활성 지표의 최근 3년치를 받아 indicator_values 에 넣는다.
  uv run backfill_values.py            # 전부 (이미 있는 날짜는 건드리지 않고, 그 지표의 기존 첫 기록보다 이른 날짜만 추가)
  uv run backfill_values.py 8933 55    # 지표 id 만
매일 도는 일일 수집(indicators.gather_values)은 그대로 오늘 값을 쌓는다. 신호(경고·방향 전환)·AI 해설은 이력에는 채우지 않는다."""
import datetime, sys
from concurrent.futures import ThreadPoolExecutor
import db as D
import indicators as I
import marketdata as M

YEARS = 3

def run(ids=None, years=YEARS):
    con = D.connect()
    inds = con.execute("SELECT * FROM indicators WHERE active=1 AND source IN ('yahoo','fred','kofia','multpl','ecos','rone','krx','sec','llama') AND symbol!=''").fetchall()
    if ids: inds = [i for i in inds if i["id"] in set(ids)]
    back = int(years * 365.25) + 40                                    # 방향 계산용 여유
    cutoff = (datetime.date.today() - datetime.timedelta(days=int(years * 365.25))).isoformat()
    with ThreadPoolExecutor(5) as ex: series = list(ex.map(lambda i: M.fetch(i["source"], i["symbol"], back), inds))
    tot = 0
    for ind, rows in zip(inds, series):
        if not rows: print(f"{ind['id']:6d} {ind['name'][:30]:30s} 값을 못 받음"); continue
        have = con.execute("SELECT min(date), min(value_date) FROM indicator_values WHERE indicator_id=? AND llm IS NOT 'backfill'", (ind["id"],)).fetchone()
        limit = min([x for x in have if x] or ["9999-99-99"])          # 일일 수집이 쌓은 첫 기록보다 이른 것만 채워 겹치지 않게 한다(이력 행은 llm='backfill' 로 표시 — 다시 돌려도 안전)
        unit = f" {ind['unit']}" if ind["unit"] else ""
        suffix = " (전년 대비 %)" if ind["source"] == "fred" and ind["symbol"] in M.YOY else unit
        out = []
        for k, (d, v) in enumerate(rows):
            if d < cutoff or d >= limit: continue
            prev = rows[k - 1][1] if k else None
            a = I.analyze_series(ind, rows[:k + 1])
            out.append((ind["id"], d, v, I._fmt(v) + suffix, d, prev, a["chg"], a["direction"]))
        con.executemany("INSERT OR IGNORE INTO indicator_values(indicator_id,date,value,value_text,value_date,prev_value,change_pct,direction,llm) VALUES(?,?,?,?,?,?,?,?,'backfill')", out)
        con.commit(); tot += len(out)
        print(f"{ind['id']:6d} {ind['name'][:30]:30s} {ind['source']:6s} 받은 {len(rows):5d}개 → 추가 {len(out):4d}개 ({out[0][1] if out else '-'} ~ {out[-1][1] if out else '-'})")
    print(f"합계 {tot}행 추가 / 지표 {len(inds)}개")

if __name__ == "__main__":
    run([int(x) for x in sys.argv[1:]] or None)
