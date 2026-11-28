"""실행 결과 메일: 이번에 바뀐 것을 HTML(라이트/다크)로 요약하고 로그를 첨부해 보낸다. (표준 라이브러리만 사용)

  uv run mailreport.py                       # 마지막 갱신분(data/watchlater.db.bak → watchlater.db)을 보냄
  uv run mailreport.py --dry /tmp/m.html     # 보내지 않고 HTML 만 저장
  uv run mailreport.py --since '2026-01-01 01:00:00' --log logs/run-x.log --exit 0    # run_skill.sh 가 호출하는 모양

보내는 곳은 역할에 따라 다르다. 설정은 프로젝트 폴더의 .env (KEY=VALUE, 심볼릭 링크도 됨, git 에 올리지 않음)
  개발 서버(dev)    : 사내 SMTP 릴레이(인증 없음)   SMTP_HOST, SMTP_PORT(기본 25), MAIL_FROM, MAIL_TO
  서비스 서버(service): Gmail(SSL 465)             GMAIL_SENDER, GMAIL_APP_PASSWORD, GMAIL_TO(없으면 GMAIL_SENDER). MAIL_TO 는 쓰지 않음
  공통(선택)        : REPORT_URL(메일의 '리포트 열기' 링크)
MAIL_TO 는 쉼표로 여러 명. 설정이 없으면 보내지 않고 넘어간다. 메일 실패는 실행 결과에 영향을 주지 않는다."""
import argparse, collections, datetime, gzip, html, pathlib, re, smtplib, sqlite3, subprocess, sys
from email.message import EmailMessage
import db as D, role

ROOT = pathlib.Path(__file__).resolve().parent
CONF_DIR = pathlib.Path.home() / ".config" / "yt-watcher-later"
ENV_FILE = ROOT / ".env"                                 # 메일 설정
LAST_HEAD = ROOT / "data" / "_mail" / "last_head"      # 지난 메일 때의 소스 커밋
LOG_LIMIT = 1024 * 1024                                  # 이보다 큰 첨부는 gzip
LIST_LIMIT = 30                                          # 본문의 목록 하나에 보여 줄 최대 건수
PROBLEM = re.compile(r"실패(?! 0)|오류|Traceback|Error\b|stalled|403 Forbidden|거부 [1-9]")


def read_env(path):
    out = {}
    try: text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError: return out
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_]\w*)\s*=(.*)", line)
        if m: out[m[1]] = m[2].strip().strip("'\"")
    return out


def secrets():
    """메일 본문·첨부에서 가려야 할 값들 (설정 파일의 키·비밀번호·토큰)."""
    values = set()
    for f in (ENV_FILE, CONF_DIR / "env"):
        values |= {v for k, v in read_env(f).items() if re.search(r"KEY|PASS|TOKEN|SECRET|_PW|PAT$", k, re.I)}
    try: values.add((CONF_DIR / "token").read_text(encoding="utf-8").strip())
    except OSError: pass
    return sorted((v for v in values if len(v) >= 6), key=len, reverse=True)


def redact(text, hide):
    for v in hide: text = text.replace(v, "***")
    return re.sub(r"(://[^/\s:@]+:)[^/\s@]+@", r"\1***@", text)


# ── DB 비교 ──
def table_rows(con, t):
    info = con.execute(f"PRAGMA table_info({t})").fetchall()
    cols = [r[1] for r in info]
    pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    rows = [dict(zip(cols, r)) for r in con.execute(f"SELECT * FROM {t}")]
    if pk: return {tuple(r[k] for k in pk): r for r in rows}, True
    return collections.Counter(tuple(r.values()) for r in rows), False


def same_row(old, new):
    """DB 에 칸만 새로 생긴 것(값이 비어 있음)은 변경으로 세지 않는다."""
    return all(old[k] == v if k in old else v in (None, 0) for k, v in new.items())


def diff_db(old, new):
    """{표: (새 행 목록, 바뀐 행 목록, 없어진 건수)}"""
    a, b = (sqlite3.connect(f"file:{p}?mode=ro", uri=True) for p in (old, new))
    names = lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    out = {}
    for t in sorted(names(b)):
        rows_b, keyed = table_rows(b, t)
        rows_a = table_rows(a, t)[0] if t in names(a) else ({} if keyed else collections.Counter())
        if keyed:
            added = [r for k, r in rows_b.items() if k not in rows_a]
            changed = [r for k, r in rows_b.items() if k in rows_a and not same_row(rows_a[k], r)]
            removed = sum(k not in rows_b for k in rows_a)
        else:
            added, changed, removed = list((rows_b - rows_a).elements()), [], sum((rows_a - rows_b).values())
        if added or changed or removed: out[t] = (added, changed, removed)
    a.close(); b.close()
    return out


def titles(new):
    con = sqlite3.connect(f"file:{new}?mode=ro", uri=True)
    out = {r[0]: (r[1] or r[0], r[2] or "") for r in con.execute("SELECT id, title, url FROM videos")}
    con.close()
    return out


# ── HTML ──
def esc(v, limit=300):
    s = " ".join(str(v or "").split())
    return html.escape(s[:limit] + ("…" if len(s) > limit else ""))


def link(url, text):
    return f'<a class="a" style="color:#1a5fd0" href="{html.escape(url)}">{text}</a>' if str(url).startswith(("http://", "https://")) else text


def small(text):
    return f'<div class="mut" style="color:#667085;font-size:13px">{text}</div>'


def section(title, items):
    if not items: return ""
    more = small(f"… 외 {len(items) - LIST_LIMIT}건") if len(items) > LIST_LIMIT else ""
    body = "".join(f'<div class="line" style="padding:8px 0;border-top:1px solid #e4e7ec">{i}</div>' for i in items[:LIST_LIMIT])
    return (f'<div class="card" style="background:#ffffff;border:1px solid #e4e7ec;border-radius:10px;padding:14px 16px;margin:0 0 12px">'
            f'<div style="font-weight:700;margin-bottom:6px">{html.escape(title)} ({len(items)})</div>{body}{more}</div>')


def build(diff, names, label, status, meta, problems, commits, report_url):
    added = lambda t: diff.get(t, ([], [], 0))[0]
    touched = lambda t: diff.get(t, ([], [], 0))[0] + diff.get(t, ([], [], 0))[1]
    name = lambda vid: link(names.get(vid, (vid, ""))[1], esc(names.get(vid, (vid, ""))[0], 120))

    new_videos = added("videos")
    new_ids = {v["id"] for v in new_videos}
    videos = [name(v["id"]) + small(" · ".join(x for x in (esc(v.get("channel")), esc(v.get("owner")), esc(v.get("category")), esc(v.get("status"))) if x))
              + (f"<div>{esc(v.get('one_liner'))}</div>" if v.get("one_liner") else "") for v in new_videos]
    analyses = [name(r["video_id"]) + small(f"{esc(r.get('engine'))} · {esc(r.get('model'))}") + f"<div>{esc(r.get('one_liner'))}</div>"
                for r in added("analysis_runs") if r["video_id"] not in new_ids]
    opinions = [name(r["video_id"]) + (f"<div><b>나</b> {esc(r.get('my_opinion'))}</div>" if r.get("my_opinion") else "")
                + (f"<div><b>AI</b> {esc(r.get('ai_reply'), 500)}</div>" if r.get("ai_reply") else "") for r in touched("opinions")]
    marks = [name(r["video_id"]) + small(f"🎯 직접 해보기 {'켬' if r.get('on_flag') else '끔'} {esc(r.get('comment'))}") for r in touched("actions")]
    marks = [m + small("✅ Action Done") if r.get("done") else m for m, r in zip(marks, touched("actions"))]
    marks += [name(r["video_id"]) + small(f"💬 의견 action {'켬' if r.get('on_flag') else '끔'}{' · ✅ Action Done' if r.get('done') else ''} {esc(r.get('comment'))}") for r in touched("opinion_actions")]
    marks += [name(r["video_id"]) + small(f"⭐ 인상 깊은 영상 {'켬' if r.get('on_flag') else '끔'}") for r in touched("stars")]
    inputs = [f"{'✅' if r.get('ok') else '❌'} {esc(r.get('type'))} · {name(r.get('vid'))}" + small(f"{esc(r.get('ts'))} {esc(r.get('msg'))}") for r in added("inbox_applied")]
    judged = [f"<b>{esc(r.get('status'))}</b> {esc(r.get('what_to_check'))}" + small(name(r.get("video_id"))) + f"<div>{esc(r.get('result'))}</div>"
              for r in touched("checks") if r.get("checked_at") and r.get("result")]
    marked = [name(r["video_id"]) + f"<div>{esc(r.get('note'))}</div>" for r in added("highlights")]

    counts = [("새 영상", len(videos)), ("분석", len(added("analysis_runs"))), ("입력 반영", len(inputs)), ("의견", len(opinions)), ("확인 판정", len(judged))]
    tiles = "".join(f'<td class="card" style="background:#ffffff;border:1px solid #e4e7ec;border-radius:10px;padding:10px;text-align:center">'
                    f'<div style="font-size:22px;font-weight:700">{n}</div>{small(k)}</td>' for k, n in counts)
    color = {"정상": "#067647", "확인 필요": "#b54708", "실패": "#b42318"}[status]
    table = "".join(f'<tr><td style="padding:2px 12px 2px 0">{html.escape(t)}</td><td style="padding:2px 10px;text-align:right">+{len(a)}</td>'
                    f'<td style="padding:2px 10px;text-align:right">~{len(c)}</td><td style="padding:2px 10px;text-align:right">-{r}</td></tr>' for t, (a, c, r) in diff.items())
    body = "".join([
        section("확인이 필요한 로그", [esc(p, 400) for p in problems]),
        section("새 영상", videos), section("다시 분석한 영상", analyses), section("서비스 서버에서 받은 입력", inputs),
        section("의견", opinions), section("버튼(직접 해보기·의견 action·인상 깊은 영상)", marks), section("인상 깊었던 영상 추가", marked),
        section("확인 항목 판정", judged), section("새로 등록한 지표", [esc(r.get("name")) + small(esc(r.get("category"))) for r in added("indicators")]), section("소스 변경(커밋)", [esc(c) for c in commits]),
    ])
    if table:
        body += (f'<div class="card" style="background:#ffffff;border:1px solid #e4e7ec;border-radius:10px;padding:14px 16px;margin:0 0 12px">'
                 f'<div style="font-weight:700;margin-bottom:6px">DB 표별 변화 (+추가 ~수정 -삭제)</div><table style="font-size:13px;border-collapse:collapse">{table}</table></div>')
    else: body += small("DB 에 바뀐 내용이 없습니다.")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<style>
:root{{color-scheme:light dark}}
@media (prefers-color-scheme: dark){{
 body,.page{{background:#101214!important;color:#e6e8eb!important}}
 .card{{background:#1a1d21!important;border-color:#30353b!important;color:#e6e8eb!important}}
 .line{{border-color:#30353b!important}} .mut{{color:#9aa4b2!important}} .a{{color:#7fb0ff!important}}
}}
</style></head>
<body class="page" style="margin:0;background:#f4f5f7;color:#1d2939;font:15px/1.55 -apple-system,'Malgun Gothic',sans-serif">
<div style="max-width:720px;margin:0 auto;padding:16px">
<div style="font-size:20px;font-weight:700">▶️ {html.escape(label)} YouTube 리포트 <span style="background:{color};color:#fff;border-radius:6px;padding:2px 8px;font-size:14px">{status}</span></div>
{small(html.escape(meta))}
{('<div style="margin:6px 0">' + link(report_url, '리포트 열기 →') + '</div>') if report_url else ''}
<table role="presentation" style="width:100%;border-spacing:6px;margin:8px -6px"><tr>{tiles}</tr></table>
{body}
{small('실행 로그는 첨부 파일에 있습니다.')}
</div></body></html>""", counts


# ── 모으기 / 보내기 ──
def new_commits():
    """지난 메일 이후의 커밋. 반환 (목록, 지금 HEAD)."""
    git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, timeout=30).stdout.strip()
    head = git("rev-parse", "HEAD")
    old = LAST_HEAD.read_text(encoding="utf-8").strip() if LAST_HEAD.exists() else ""
    log = git("log", "--format=%h %ad %s", "--date=short", f"{old}..{head}") if old else git("log", "-1", "--format=%h %ad %s", "--date=short")
    return log.splitlines(), head


def attachments(log, since, hide, tail=None):
    files = []
    if log: files.append((pathlib.Path(log), tail))
    if since:
        files += [(f, None) for f in sorted((ROOT / "logs").glob("*")) if f.name.startswith(("collect-", "agy-session-")) and f.stat().st_mtime >= since.timestamp()]
    out = []
    for f, n in files:
        try: text = f.read_text(encoding="utf-8", errors="replace")
        except OSError: continue
        if n: text = "\n".join(text.splitlines()[-n:]) + "\n"
        data = redact(text, hide).encode()
        name = f.name if f.suffix in (".log", ".txt") else f.name + ".txt"
        if len(data) > LOG_LIMIT: data, name = gzip.compress(data), name + ".gz"
        out.append((name, data))
    return out


def send(conf, service, subject, page, files):
    sender = conf.get("GMAIL_SENDER") if service else conf.get("MAIL_FROM")
    # 받는 곳은 역할마다 다르다: 개발 서버 MAIL_TO(회사), 서비스 서버 GMAIL_TO 없으면 GMAIL_SENDER(개인 Gmail). 두 서버가 같은 .env 를 써도 섞이지 않게 서비스 서버는 MAIL_TO 를 보지 않는다
    to = [x.strip() for x in ((conf.get("GMAIL_TO") or sender if service else conf.get("MAIL_TO")) or "").split(",") if x.strip()]
    need = ("GMAIL_SENDER", "GMAIL_APP_PASSWORD") if service else ("SMTP_HOST", "MAIL_FROM", "MAIL_TO")
    missing = [k for k in need if not conf.get(k)]
    if missing: print(f"메일 설정 없음({', '.join(missing)} — {ENV_FILE}) → 보내지 않음"); return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(to)
    msg.set_content("HTML 을 볼 수 있는 메일 프로그램으로 열어 주세요.")
    msg.add_alternative(page, subtype="html")
    for name, data in files:
        sub = "gzip" if name.endswith(".gz") else "octet-stream"
        if sub == "gzip": msg.add_attachment(data, maintype="application", subtype=sub, filename=name)
        else: msg.add_attachment(data.decode("utf-8", "replace"), subtype="plain", filename=name)
    if service:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(sender, conf["GMAIL_APP_PASSWORD"].replace(" ", "")); s.send_message(msg)
    else:
        with smtplib.SMTP(conf["SMTP_HOST"], int(conf.get("SMTP_PORT") or 25), timeout=60) as s: s.send_message(msg)
    print(f"메일 보냄: 받는 사람 {len(to)}명 · 첨부 {len(files)}개 · {subject}")
    return True


def report(since=None, log=None, exit_code=0, dry=None, note=None, tail=None):
    """메일 하나를 만들어 보낸다. note: 로그 대신 문제 줄을 찾을 글(서비스 서버의 이번 결과). 반환: 보냈는지."""
    service = role.raw_role()[0] == "service"
    conf, hide = read_env(ENV_FILE), secrets()
    start = datetime.datetime.fromisoformat(since) if since else None
    new, old = pathlib.Path(D.DB_PATH), pathlib.Path(str(D.DB_PATH) + ".bak")
    diff = diff_db(old, new) if old.exists() and new.exists() else {}
    text = note if note is not None else (pathlib.Path(log).read_text(encoding="utf-8", errors="replace") if log and pathlib.Path(log).exists() else "")
    problems = [redact(l, hide) for l in text.splitlines() if (l.startswith('{"event":"result"') and '"status":"SUCCESS"' not in l) or (PROBLEM.search(l) and not l.startswith('{"'))]
    status = "실패" if exit_code else ("확인 필요" if problems else "정상")
    now = datetime.datetime.now()
    meta = f"{now:%Y-%m-%d %H:%M} 기준"
    if start: meta = f"{start:%Y-%m-%d %H:%M} 시작 · {int((now - start).total_seconds() // 60)}분 · 종료코드 {exit_code}"
    commits, head = new_commits()
    page, counts = build(diff, titles(new) if new.exists() else {}, role.label(), status, meta, problems, commits, conf.get("REPORT_URL", ""))
    page = redact(page, hide)
    summary = " · ".join(f"{k} {n}" for k, n in counts if n) or "새 내용 없음"
    subject = f"[yt-watcher-later][{role.label()}] {status} · {summary} ({now:%Y-%m-%d})"
    if dry:
        pathlib.Path(dry).write_text(page, encoding="utf-8")
        print(f"[dry] {dry} 저장 · 제목: {subject} · 첨부 {[n for n, _ in attachments(log, start, hide, tail)]}"); return False
    sent = send(conf, service, subject, page, attachments(log, start, hide, tail))
    if sent:
        LAST_HEAD.parent.mkdir(parents=True, exist_ok=True); LAST_HEAD.write_text(head + "\n", encoding="utf-8")
    return sent


def safe_report(**kw):
    try: return report(**kw)
    except Exception as e:
        print(f"메일 발송 실패(실행 결과와는 무관): {e!r}"); return False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--since"); p.add_argument("--log"); p.add_argument("--exit", type=int, default=0, dest="exit_code"); p.add_argument("--dry")
    safe_report(**vars(p.parse_args()))
