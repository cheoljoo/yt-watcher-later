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
        "SELECT id,title,channel,owner,category,subtag,duration_sec,view_count,upload_date,watched_at,run_id,processed_date FROM videos WHERE status='done'")]
    n = len(vs)
    if not n: return
    total = sum(v["duration_sec"] or 0 for v in vs); watched = sum(1 for v in vs if v["watched_at"])
    body = (f"<h1>📈 내 시청 성향</h1><p class=meta>저장해 둔 영상 {n}개 기준 (분석 완료분) · 총 길이 {hm(total)} · 본 날짜 기록 {watched}개 · "
            f"<a href='index.html'>🏠 홈</a></p>")

    byid = {v["id"]: v for v in vs}
    plist = [(r["video_id"], r["name"].strip(), (r["role"] or "").strip()) for r in con.execute("SELECT video_id,name,role FROM people")
             if r["video_id"] in byid and r["name"]]

    def chan_rows(sub):
        ch = defaultdict(list)
        for v in sub: ch[v["channel"] or "(알 수 없음)"].append(v)
        return sorted(ch.items(), key=lambda kv: (-len(kv[1]), -sum(x["duration_sec"] or 0 for x in kv[1])))

    def chan_table(rows, limit):
        mx = len(rows[0][1]); t = "<tr><th>#<th>채널<th>영상 수<th>총 길이<th>주 카테고리<th>저장한 사람</tr>"
        for i, (name, lst) in enumerate(rows[:limit], 1):
            cats = defaultdict(int)
            for x in lst: cats[x["category"]] += 1
            cat = max(cats, key=cats.get)
            owners = ", ".join(sorted({x["owner"] or "-" for x in lst}))
            t += (f"<tr><td>{i}<td><details><summary><b>{e(name)}</b></summary><ul>{''.join('<li>' + link(x) + '</li>' for x in sorted(lst, key=lambda x: (x["upload_date"] or "", x["id"])))}</ul></details>"
                  f"<td>{bar(len(lst), mx)} {len(lst)}<td>{hm(sum(x['duration_sec'] or 0 for x in lst))}<td>{R.CAT_ICON.get(cat, '📌')} {e(cat)}<td>👤 {e(owners)}</tr>")
        return f"<table>{t}</table>"

    def people_rows(sub):
        ids = {v["id"] for v in sub}; pp = defaultdict(lambda: {"vids": {}, "roles": defaultdict(int)})
        for vid, name, role in plist:
            if vid in ids: d = pp[name]; d["vids"][vid] = byid[vid]; d["roles"][role] += 1
        return sorted(pp.items(), key=lambda kv: (-len(kv[1]["vids"]), kv[0]))

    def people_table(prow, limit):
        mx = len(prow[0][1]["vids"]); t = "<tr><th>#<th>인물<th>나온 영상 수<th>대표 직함·소속<th>주로 나온 채널</tr>"
        for i, (name, d) in enumerate(prow[:limit], 1):
            lst = list(d["vids"].values()); role = max(d["roles"], key=d["roles"].get)
            chs = defaultdict(int)
            for x in lst: chs[x["channel"] or "-"] += 1
            top_ch = ", ".join(f"{c}({k})" for c, k in sorted(chs.items(), key=lambda kv: -kv[1])[:2])
            t += (f"<tr><td>{i}<td><details><summary><b>{e(name)}</b></summary><ul>{''.join('<li>' + link(x) + '</li>' for x in sorted(lst, key=lambda x: (x["upload_date"] or "", x["id"])))}</ul></details>"
                  f"<td>{bar(len(lst), mx)} {len(lst)}<td class=meta>{e(role[:60])}<td class=meta>{e(top_ch)}</tr>")
        return f"<table>{t}</table>"

    rows = chan_rows(vs)
    (R.OUT / "stats_channels.html").write_text(R.page("모든 채널", f"<h1>📺 모든 채널 ({len(rows)}개)</h1><p class=meta>영상 수 많은 순 · 같으면 총 길이 긴 순 · 채널 이름을 누르면 영상 목록 · <a href='stats.html'>‹ 시청 성향</a> · <a href='index.html'>🏠 홈</a></p>{chan_table(rows, len(rows))}", "📺"), encoding="utf-8")

    # 주제(browse.html 과 같은 분류: 카테고리 / 카테고리·소주제)별로 채널·인물 TOP 을 미리 만들어 두고 선택에 따라 보여 준다
    cats, subs = {}, {}
    for v in vs:
        c, sb = v["category"] or "기타", v["subtag"] or "기타"
        cats[c] = cats.get(c, 0) + 1; subs.setdefault(c, {})[sb] = subs.setdefault(c, {}).get(sb, 0) + 1
    order = sorted(cats, key=lambda c: R.CAT_ORDER.index(c) if c in R.CAT_ORDER else len(R.CAT_ORDER))
    topics = [("all", "모두", len(vs), vs)]
    for c in order:
        topics.append((f"c:{c}", f"{R.CAT_ICON.get(c, '📌')} {c}", cats[c], [v for v in vs if (v["category"] or "기타") == c]))
        for sb, k in sorted(subs[c].items(), key=lambda kv: (-kv[1], kv[0])):
            topics.append((f"s:{c}/{sb}", f"\u00a0\u00a0└ {sb}", k, [v for v in vs if (v["category"] or "기타") == c and (v["subtag"] or "기타") == sb]))
    opts, blocks = "", ""
    for i, (key, label, k, sub) in enumerate(topics):
        opts += f"<option value='{i}'>{e(label)} ({k})</option>"
        cr, pr = chan_rows(sub), people_rows(sub); one = sum(1 for _, l in cr if len(l) == 1)
        ph = (f"<h2>🧑 자주 나오는 인물 TOP {min(TOP, len(pr))} <span class=meta>(전체 {len(pr)}명 — 진행자·출연자·인용 인물 모두 포함)</span></h2>{people_table(pr, TOP)}"
              if pr else "<h2>🧑 자주 나오는 인물</h2><p class=meta>이 주제의 영상에서 뽑힌 인물이 없습니다.</p>")
        blocks += (f"<div class=tp id=tp-{i}{'' if i == 0 else ' hidden'}><h2>📺 많이 보는 채널 TOP {min(TOP, len(cr))} <span class=meta>(전체 {len(cr)}개 채널, 1개짜리 {one}개 · 영상 {k}개)</span></h2>"
                   f"{'<p><a href=stats_channels.html>📺 모든 채널 ' + str(len(cr)) + '개 보기 ›</a></p>' if i == 0 else ''}{chan_table(cr, TOP)}{ph}</div>")
    body += ("<div style='margin:14px 0'><label>🏷️ 주제 <select id=tp-sel style='font:inherit;padding:4px 8px'>" + opts + "</select></label> <span class=meta>고른 주제의 영상만으로 채널·인물 TOP 을 다시 셉니다 (browse.html 의 주제와 같은 분류)</span></div>"
             + blocks + "<script>(function(){var s=document.getElementById('tp-sel');s.onchange=function(){document.querySelectorAll('.tp').forEach(function(d){d.hidden=d.id!=='tp-'+s.value})}})()</script>")

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
