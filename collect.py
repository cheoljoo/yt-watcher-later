"""yt-dlp로 info.json + 댓글 + 자막을 받고 정리한다. 429(요청 과다)에 대비해 간격/재시도/언어 순차 요청."""
import json, pathlib, subprocess, time
from cookiejar import cookie_copy
from vtt_to_text import vtt_to_text

class RateLimited(RuntimeError): pass

def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return r, ("429" in r.stderr or "Too Many Requests" in r.stderr)

def _ytdlp(cfg, d, vid, extra, retries=3, log=None):
    base = ["yt-dlp", *(["--cookies", cookie_copy(cfg["cookies"])] if cfg.get("cookies") else []),
            "--skip-download", "--ignore-no-formats-error", "--ignore-errors",
            "--sleep-requests", "1", "--sleep-subtitles", "3",
            "-o", str(d / vid), *extra, f"https://www.youtube.com/watch?v={vid}"]
    for i in range(retries):
        r, limited = _run(base)
        if log is not None:
            log.extend(f"[{vid}] {l}" for l in r.stderr.splitlines() if l.startswith(("ERROR", "WARNING")))
            if limited: log.append(f"[{vid}] 429 -> {30 * 3 ** i}s 대기 후 재시도({i + 1}/{retries})")
        if not limited: return r
        time.sleep(30 * (3 ** i))                       # 30s, 90s, 270s
    raise RateLimited("HTTP 429 (재시도 후에도 요청 과다)")

def collect(video_id, cfg, data_dir="data", log=None):
    d = pathlib.Path(data_dir) / video_id; d.mkdir(parents=True, exist_ok=True)
    info_p, tr_p = d / f"{video_id}.info.json", d / "transcript.txt"
    langs = cfg["langs"]
    vtt = lambda l: d / f"{video_id}.{l}.vtt"
    if not info_p.exists():
        r = _ytdlp(cfg, d, video_id, ["--write-info-json", "--write-comments",
                   "--extractor-args", f"youtube:max_comments={cfg['max_comments']},all,0,0;comment_sort=top;lang=ko",
                   "--write-subs", "--write-auto-subs", "--sub-langs", langs[0], "--sub-format", "vtt"], log=log)
        if not info_p.exists():
            errs = [l for l in r.stderr.splitlines() if "ERROR" in l] or r.stderr.splitlines()[-3:]
            raise RuntimeError(f"yt-dlp 실패(code {r.returncode}): " + " | ".join(errs)[-400:])
    for l in langs[1:]:                                  # 우선 언어 자막이 없을 때만 다음 언어 요청
        if not any(vtt(x).exists() for x in langs):
            _ytdlp(cfg, d, video_id, ["--write-subs", "--write-auto-subs", "--sub-langs", l, "--sub-format", "vtt"], log=log)
    info = json.loads(info_p.read_text(encoding="utf-8"))
    lang = text = None
    for l in langs:
        if vtt(l).exists():
            lang, text = l, vtt_to_text(str(vtt(l))); tr_p.write_text(text, encoding="utf-8"); break
    ud = info.get("upload_date") or ""
    return {
        "info": info, "transcript": text, "lang": lang,
        "meta": {
            "upload_date": f"{ud[:4]}-{ud[4:6]}-{ud[6:]}" if len(ud) == 8 else None,
            "channel": info.get("channel"), "channel_id": info.get("channel_id"),
            "channel_url": info.get("channel_url"), "uploader_id": info.get("uploader_id"),
            "duration_sec": info.get("duration"), "view_count": info.get("view_count"),
            "like_count": info.get("like_count"), "comment_count": info.get("comment_count"),
            "yt_categories": json.dumps(info.get("categories") or [], ensure_ascii=False),
            "yt_tags": json.dumps(info.get("tags") or [], ensure_ascii=False),
            "description": info.get("description"), "thumbnail": info.get("thumbnail"),
            "live_status": info.get("live_status"),
        },
    }
