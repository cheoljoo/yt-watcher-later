"""시청 성향 분석 페이지 (reports/stats.html): 어떤 채널을 많이 보는가, 어떤 인물이 나오는 영상을 많이 보는가.
DB 만 읽는다(LLM·네트워크 없음). report.build_all 이 마지막에 호출하므로 매일 cron 끝에 갱신된다."""
from collections import defaultdict
from html import escape as e
import report as R

TOP = 30

def bar(n, mx): return f"<span style='display:inline-block;height:.7em;width:{max(2, int(120 * n / mx)) if mx else 2}px;background:#4c8bf5;border-radius:3px;vertical-align:middle'></span>"
def hm(sec): return f"{sec // 3600}시간 {sec % 3600 // 60}분" if sec >= 3600 else f"{sec // 60}분"
def link(v): return f"<a href='{e(v['page'])}.html#v-{e(v['id'])}'>{e((v['title'] or '')[:50])}</a>"

def build(con):
    vs = [dict(r, page=r["run_id"] or r["processed_date"]) for r in con.execute(
        "SELECT id,title,channel,owner,category,duration_sec,view_count,upload_date,watched_at,run_id,processed_date FROM videos WHERE status='done'")]
    n = len(vs)
    if not n: return
    total = sum(v["duration_sec"] or 0 for v in vs); watched = sum(1 for v in vs if v["watched_at"])
    body = (f"<h1>📈 내 시청 성향</h1><p class=meta>저장해 둔 영상 {n}개 기준 (분석 완료분) · 총 길이 {hm(total)} · 본 날짜 기록 {watched}개 · "
            f"<a href='index.html'>🏠 홈</a></p>")

    # 채널별
    ch = defaultdict(list)
    for v in vs: ch[v["channel"] or "(알 수 없음)"].append(v)
    rows = sorted(ch.items(), key=lambda kv: (-len(kv[1]), -sum(x["duration_sec"] or 0 for x in kv[1])))
    mx = len(rows[0][1])
    def chan_table(limit):
        t = "<tr><th>#<th>채널<th>영상 수<th>총 길이<th>주 카테고리<th>저장한 사람</tr>"
        for i, (name, lst) in enumerate(rows[:limit], 1):
            cats = defaultdict(int)
            for x in lst: cats[x["category"]] += 1
            cat = max(cats, key=cats.get)
            owners = ", ".join(sorted({x["owner"] or "-" for x in lst}))
            t += (f"<tr><td>{i}<td><details><summary><b>{e(name)}</b></summary><ul>{''.join('<li>' + link(x) + '</li>' for x in sorted(lst, key=lambda x: (x["upload_date"] or "", x["id"])))}</ul></details>"
                  f"<td>{bar(len(lst), mx)} {len(lst)}<td>{hm(sum(x['duration_sec'] or 0 for x in lst))}<td>{R.CAT_ICON.get(cat, '📌')} {e(cat)}<td>👤 {e(owners)}</tr>")
        return f"<table>{t}</table>"
    one = sum(1 for _, l in rows if len(l) == 1)
    body += (f"<h2>📺 많이 보는 채널 TOP {min(TOP, len(rows))} <span class=meta>(전체 {len(rows)}개 채널, 1개짜리 {one}개)</span></h2>"
             f"<p><a href='stats_channels.html'>📺 모든 채널 {len(rows)}개 보기 ›</a></p>{chan_table(TOP)}")
    (R.OUT / "stats_channels.html").write_text(R.page("모든 채널", f"<h1>📺 모든 채널 ({len(rows)}개)</h1><p class=meta>영상 수 많은 순 · 같으면 총 길이 긴 순 · 채널 이름을 누르면 영상 목록 · <a href='stats.html'>‹ 시청 성향</a> · <a href='index.html'>🏠 홈</a></p>{chan_table(len(rows))}", "📺"), encoding="utf-8")

    # 등장 인물별
    byid = {v["id"]: v for v in vs}
    pp = defaultdict(lambda: {"vids": {}, "roles": defaultdict(int)})
    for r in con.execute("SELECT video_id,name,role FROM people"):
        if r["video_id"] in byid and r["name"]:
            d = pp[r["name"].strip()]; d["vids"][r["video_id"]] = byid[r["video_id"]]; d["roles"][(r["role"] or "").strip()] += 1
    prow = sorted(pp.items(), key=lambda kv: (-len(kv[1]["vids"]), kv[0]))
    if prow:
        mx = len(prow[0][1]["vids"]); t = "<tr><th>#<th>인물<th>나온 영상 수<th>대표 직함·소속<th>주로 나온 채널</tr>"
        for i, (name, d) in enumerate(prow[:TOP], 1):
            lst = list(d["vids"].values()); role = max(d["roles"], key=d["roles"].get)
            chs = defaultdict(int)
            for x in lst: chs[x["channel"] or "-"] += 1
            top_ch = ", ".join(f"{c}({k})" for c, k in sorted(chs.items(), key=lambda kv: -kv[1])[:2])
            t += (f"<tr><td>{i}<td><details><summary><b>{e(name)}</b></summary><ul>{''.join('<li>' + link(x) + '</li>' for x in sorted(lst, key=lambda x: (x["upload_date"] or "", x["id"])))}</ul></details>"
                  f"<td>{bar(len(lst), mx)} {len(lst)}<td class=meta>{e(role[:60])}<td class=meta>{e(top_ch)}</tr>")
        body += f"<h2>🧑 자주 나오는 인물 TOP {min(TOP, len(prow))} <span class=meta>(전체 {len(prow)}명 — 진행자·출연자·인용 인물 모두 포함)</span></h2><table>{t}</table>"

    # 카테고리·저장한 사람·월별
    def count_table(title, key, fmt=lambda k: e(str(k))):
        c = defaultdict(int)
        for v in vs: c[v[key]] += 1
        m = max(c.values()); r = "".join(f"<tr><td>{fmt(k)}<td>{bar(c[k], m)} {c[k]}</tr>" for k in sorted(c, key=lambda k: -c[k]))
        return f"<h2>{title}</h2><table>{r}</table>"
    body += count_table("🗂️ 카테고리별", "category", lambda k: f"{R.CAT_ICON.get(k, '📌')} {e(k or '-')}")
    body += count_table("👤 저장한 사람별", "owner", lambda k: e(k or "-"))
    mon = defaultdict(int)
    for v in vs: mon[(v["upload_date"] or "알 수 없음")[:7]] += 1
    m = max(mon.values()); body += "<h2>🗓️ 영상 업로드 월별</h2><table>" + "".join(f"<tr><td>{e(k)}<td>{bar(mon[k], m)} {mon[k]}</tr>" for k in sorted(mon, reverse=True)[:18]) + "</table>"
    body += "<p class=meta>‘많이 본다’는 재생목록에 저장해 둔 영상 수 기준입니다(시청 기록은 일부만 있음). 인물은 LLM이 영상에서 뽑은 이름이라 표기가 다르면 다른 사람으로 셉니다.</p>"
    (R.OUT / "stats.html").write_text(R.page("시청 성향", body, "📈"), encoding="utf-8")
