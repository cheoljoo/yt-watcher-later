"""재생목록 수집. 공개/일부공개 재생목록은 쿠키 없이 읽는다(cookies 지정 시에만 사용)."""
import json, subprocess
from cookiejar import cookie_copy

def fetch_playlist(url, cookies=""):
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--extractor-args", "youtube:lang=ko", url]
    if cookies: cmd[1:1] = ["--cookies", cookie_copy(cookies)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError("재생목록 조회 실패: " + r.stderr[-300:])
    return [
        {"id": e["id"], "title": e.get("title"), "channel": e.get("channel") or e.get("uploader"),
         "url": f"https://www.youtube.com/watch?v={e['id']}"}
        for e in json.loads(r.stdout)["entries"] if e
    ]
