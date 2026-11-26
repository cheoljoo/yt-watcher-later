"""이 프로젝트가 돌고 있는 '역할' 판단.

  uv run role.py            # 역할 이름만 출력: legacy | service | dev
  uv run role.py --why      # 왜 그렇게 판단했는지까지

역할
  dev     개발자 서버 — 수집·AI 분석·DB 갱신·리포트·백업 push 를 모두 한다(DB 원본). 시작할 때 서비스 서버에서 inbox 를 받아 DB 에 반영한다.
  service 서비스 서버(psncs) — 백업 저장소를 pull 해 DB 를 다시 만들고 web 서비스만 한다. 사용자가 누른 입력(의견·액션·별표)은 inbox 에 모은다.
  legacy  분리 전 — 한 서버가 전부 한다(예전 동작 그대로). 서비스 서버로 정해진 곳도 config.toml 의 split_from 시각 전에는 legacy 다.

판단 순서: 환경변수 YT_ROLE → 파일 ~/.config/yt-watcher-later/role → config.toml 의 service_hostnames 에 이 컴퓨터 이름이 있으면 service, 없으면 dev.
service 로 정해졌더라도 split_from(분리 시작 시각) 이전이면 legacy 로 동작한다. dev 는 split_from 이전에는 실행하지 않는다(ready() 가 거짓)."""
import datetime, os, pathlib, socket, sys, tomllib

ROOT = pathlib.Path(__file__).resolve().parent
ROLE_FILE = pathlib.Path.home() / ".config" / "yt-watcher-later" / "role"


def _cfg():
    try: return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    except Exception: return {}


def split_from():
    s = _cfg().get("split_from")
    try: return datetime.datetime.fromisoformat(str(s)) if s else None
    except ValueError: return None


def raw_role():
    """분리 시각을 따지기 전의 역할(service|dev|legacy)과 이유."""
    e = os.environ.get("YT_ROLE", "").strip().lower()
    if e in ("service", "dev", "legacy"): return e, f"환경변수 YT_ROLE={e}"
    try:
        f = ROLE_FILE.read_text(encoding="utf-8").strip().lower()
        if f in ("service", "dev", "legacy"): return f, f"파일 {ROLE_FILE}"
    except OSError: pass
    host = socket.gethostname()
    if host in _cfg().get("service_hostnames", []): return "service", f"컴퓨터 이름 {host} 이(가) config.toml service_hostnames 에 있음"
    return "dev", f"컴퓨터 이름 {host} 이(가) service_hostnames 에 없음"


def split_started(now=None):
    sf = split_from()
    return sf is None or (now or datetime.datetime.now()) >= sf


def role(now=None):
    r, _ = raw_role()
    if r == "service" and not split_started(now): return "legacy"
    return r


def ready(now=None):
    """dev 가 지금 일을 시작해도 되는가(분리 시작 시각 이후인가)."""
    return role(now) != "dev" or split_started(now)


def why():
    r, reason = raw_role(); sf = split_from()
    out = f"역할 {role()}  ← {reason}"
    if r == "service" and role() == "legacy": out += f" · 분리 시작 시각({sf}) 전이라 legacy"
    if r == "dev" and not split_started(): out += f" · 분리 시작 시각({sf}) 전이라 아직 실행하지 않음"
    return out


if __name__ == "__main__":
    print(why() if "--why" in sys.argv else role())
