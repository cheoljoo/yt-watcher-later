"""의견 저장 서버(로컬 127.0.0.1:8650). nginx 가 /yt_watch_later/api/ 를 여기로 프록시한다.
 POST /save {id,text} · /action {id,on} · /action_comment {id,text} · /star {id,on} · /opinion_action {id,on} · /opinion_action_comment {id,text} · /action_done, /opinion_action_done {id,on}
 (POST 는 헤더 X-Token 필요)   GET /opinions, /actions, /opinion_actions, /stars -> JSON
 서비스 서버(role.py 가 service)에서는 저장이 성공할 때마다 inbox 에도 한 줄 쌓는다(개발 서버가 가져가 원본 DB 에 반영).
토큰: ~/.config/yt-watcher-later/token (프로젝트 밖, git 에 올리지 않음).   실행: uv run opinion_server.py"""
import hmac, json, os, pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import db as D, opinions as O, inbox, role

PORT = int(os.environ.get("OPINION_PORT", "8650"))
GETS = {"/opinions": O.all_json, "/actions": O.actions_json, "/opinion_actions": O.opinion_actions_json, "/stars": O.stars_json}
# 경로 -> (inbox 이벤트 종류, DB 에 반영하는 함수(con, id, text, on))
POSTS = {
    "/save": ("opinion", lambda c, v, t, on: O.save_mine(c, v, t)),
    "/action": ("action", lambda c, v, t, on: O.set_action(c, v, on)),
    "/action_comment": ("action_comment", lambda c, v, t, on: O.save_action_comment(c, v, t)),
    "/action_done": ("action_done", lambda c, v, t, on: O.set_done(c, v, on)),
    "/opinion_action": ("opinion_action", lambda c, v, t, on: O.set_opinion_action(c, v, on)),
    "/opinion_action_comment": ("opinion_action_comment", lambda c, v, t, on: O.save_action_comment(c, v, t, "opinion")),
    "/opinion_action_done": ("opinion_action_done", lambda c, v, t, on: O.set_done(c, v, on, "opinion")),
    "/star": ("star", lambda c, v, t, on: O.set_star(c, v, on)),
}
TOKEN_FILE = pathlib.Path.home() / ".config" / "yt-watcher-later" / "token"

def token():
    return TOKEN_FILE.read_text(encoding="utf-8").strip()

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p not in GETS: return self._send(404, {"ok": False, "message": "not found"})
        con = D.connect()
        try: self._send(200, GETS[p](con))
        finally: con.close()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in POSTS: return self._send(404, {"ok": False, "message": "not found"})
        if not hmac.compare_digest(self.headers.get("X-Token", ""), token()): return self._send(401, {"ok": False, "message": "토큰이 맞지 않습니다"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > 20000: return self._send(413, {"ok": False, "message": "너무 깁니다"})
            d = json.loads(self.rfile.read(n) or b"{}")
            vid, text, on = str(d["id"]), str(d.get("text", "")), bool(d.get("on", True))
        except Exception: return self._send(400, {"ok": False, "message": "요청 형식이 잘못됐습니다"})
        con = D.connect()
        try:
            etype, apply = POSTS[path]
            ok, msg = apply(con, vid, text, on)
            if ok and role.role() == "service":     # 개발 서버로 보낼 입력을 inbox 에 쌓는다(분리 전 legacy 에서는 쌓지 않음 — 이미 같은 DB 가 원본)
                try: inbox.append(etype, vid, text=text, on=on)
                except Exception as ex: print("inbox 기록 실패:", ex, flush=True)
            if ok:
                try:                       # 해당 페이지 즉시 갱신
                    if path == "/save": O.build(con)
                    if path == "/star":
                        import highlight; highlight.build(con)
                    else:                  # 액션 페이지는 의견 내용도 보여 주므로 의견 저장 때도 다시 만든다
                        import actions; actions.build(con)
                except Exception as ex: print("페이지 갱신 실패:", ex, flush=True)
        finally: con.close()
        self._send(200 if ok else 409, {"ok": ok, "message": msg})

    def log_message(self, *a): pass

if __name__ == "__main__":
    if not TOKEN_FILE.exists(): raise SystemExit(f"토큰 파일이 없습니다: {TOKEN_FILE}")
    print(f"의견 저장 서버 127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
