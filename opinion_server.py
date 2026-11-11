"""의견 저장 서버(로컬 127.0.0.1:8650). nginx 가 /yt_watch_later/api/ 를 여기로 프록시한다.
 POST /save {id,text}  (헤더 X-Token 필요)   GET /opinions -> 전체 의견 JSON
토큰: ~/.config/yt-watcher-later/token (프로젝트 밖, git 에 올리지 않음).   실행: uv run opinion_server.py"""
import hmac, json, os, pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import db as D, opinions as O

PORT = int(os.environ.get("OPINION_PORT", "8650"))
TOKEN_FILE = pathlib.Path.home() / ".config" / "yt-watcher-later" / "token"

def token():
    return TOKEN_FILE.read_text(encoding="utf-8").strip()

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.split("?")[0] != "/opinions": return self._send(404, {"ok": False, "message": "not found"})
        con = D.connect()
        try: self._send(200, O.all_json(con))
        finally: con.close()

    def do_POST(self):
        if self.path.split("?")[0] != "/save": return self._send(404, {"ok": False, "message": "not found"})
        if not hmac.compare_digest(self.headers.get("X-Token", ""), token()): return self._send(401, {"ok": False, "message": "토큰이 맞지 않습니다"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 20000: return self._send(413, {"ok": False, "message": "너무 깁니다"})
            d = json.loads(self.rfile.read(n) or b"{}")
            vid, text = str(d["id"]), str(d.get("text", ""))
        except Exception: return self._send(400, {"ok": False, "message": "요청 형식이 잘못됐습니다"})
        con = D.connect()
        try:
            ok, msg = O.save_mine(con, vid, text)
            if ok:
                try: O.build(con)          # '나와 AI 의견' 페이지 즉시 갱신
                except Exception as ex: print("opinions.html 갱신 실패:", ex, flush=True)
        finally: con.close()
        self._send(200 if ok else 409, {"ok": ok, "message": msg})

    def log_message(self, *a): pass

if __name__ == "__main__":
    if not TOKEN_FILE.exists(): raise SystemExit(f"토큰 파일이 없습니다: {TOKEN_FILE}")
    print(f"의견 저장 서버 127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
