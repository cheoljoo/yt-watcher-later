"""수집 단계: 여러 영상을 yt-dlp로 병렬 수집. 429가 나면 병렬 수를 줄이고, 잠잠하면 다시 늘린다.
모든 yt-dlp 경고/오류 로그는 모아서 logs/collect-YYYY-MM-DD.log 에 남긴다."""
import pathlib, time
from concurrent.futures import ThreadPoolExecutor
from collect import collect, RateLimited
import db as D

def collect_many(videos, cfg):
    """-> ({video_id: col}, {video_id: 오류메시지}, 로그줄 리스트)"""
    top = max(1, cfg.get("parallel_collect", 3)); workers = top
    ok, bad, lines = {}, {}, []
    queue = list(videos); strikes = 0
    def one(v):
        log = []
        try: return v, collect(v["id"], cfg, log=log), None, log
        except Exception as ex: return v, None, ex, log
    while queue:
        batch, queue = queue[:workers * 2], queue[workers * 2:]
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(one, batch))
        limited = 0
        for v, col, err, log in results:
            lines += log
            if err is None: ok[v["id"]] = col; lines.append(f"[{v['id']}] 수집 성공 (자막 {col['lang'] or '없음'})")
            else:
                bad[v["id"]] = str(err); lines.append(f"[{v['id']}] 수집 실패: {str(err)[:200]}")
                limited += isinstance(err, RateLimited)
        if limited:
            strikes += 1; new = max(1, workers // 2)
            lines.append(f"## 429 발생 {limited}건 — 병렬 {workers} -> {new}, {cfg.get('cooldown_sec', 60)}초 쉼")
            print(f"   수집 429 {limited}건: 병렬 {workers} -> {new}", flush=True)
            workers = new
            if strikes >= 3 and workers == 1:
                lines.append("## 429 반복 — 남은 영상은 다음 실행으로 미룸")
                print("   429가 반복되어 수집을 중단합니다(남은 영상은 다음 실행).", flush=True); break
            time.sleep(cfg.get("cooldown_sec", 60))
        else:
            strikes = 0; workers = min(top, workers + 1)
        print(f"   수집 진행 {len(ok) + len(bad)}/{len(videos)} (병렬 {workers})", flush=True)
    return ok, bad, lines

def write_log(lines, name="collect"):
    p = pathlib.Path("logs"); p.mkdir(exist_ok=True)
    f = p / f"{name}-{D.today()}.log"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"===== {D.now()} =====\n" + "\n".join(lines) + "\n")
    return f
