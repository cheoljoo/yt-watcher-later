#!/usr/bin/env bash
# cron 진입점(스킬 모드): 수집(코드) -> AI 세션(yt-daily 스킬; 필요하면 여러 라운드) -> 리포트(코드).
# 역할(role.py): legacy=예전처럼 전부 한다 · dev=개발 서버(시작 때 서비스 서버 inbox 를 받아 DB 에 반영, 끝에 백업 push) · service=이 스크립트 대신 service_sync.py(백업 복원+웹)만 한다.
# 사용:  ./run_skill.sh [--claude | --agy] [--no-collect] [--no-finish] [--retry-failed]      (기본 --claude)
#   --claude  Claude Code(`claude -p /yt-daily`)로 처리      --agy  agy CLI(`agy -p /yt-daily`)로 처리
# 환경변수: ROUNDS(기본 4) BUDGET(세션 입력 상한, 기본 70만자) MAX_ANALYZE(영상 분석 상한) AGY_MODEL(agy 모델, 비우면 agy 기본값)
export PATH="/home/cheoljoo/.claude-wrapper/bin:/home/cheoljoo/.local/bin:/usr/bin:/bin"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
TOOL=claude; COLLECT=1; FINISH=1; RETRY=0
for a in "$@"; do case "$a" in
  --claude) TOOL=claude;; --agy) TOOL=agy;; --no-collect) COLLECT=0;; --no-finish) FINISH=0;; --retry-failed) RETRY=1;;
  *) echo "알 수 없는 옵션: $a (--claude | --agy | --no-collect | --no-finish | --retry-failed)"; exit 2;; esac; done
cd "$(dirname "$(readlink -f "$0")")" || exit 1
ROLE=$(uv run python role.py)
if [ "$ROLE" = service ]; then echo "$(date '+%F %T') 역할 service → 백업 복원만 수행"; exec uv run python service_sync.py; fi
if [ "$ROLE" = dev ] && ! uv run python -c "import role,sys; sys.exit(0 if role.ready() else 1)"; then echo "$(date '+%F %T') 역할 dev 이지만 분리 시작 시각 전 — 건너뜀 ($(uv run python role.py --why))"; exit 0; fi
exec 9>/tmp/yt-watcher-later.lock          # run_daily.sh 와 같은 락 — 동시에 돌지 않는다 (벤치마크 사본은 별도 락)
[ "$COLLECT" = 1 ] || [ "$RETRY" = 1 ] || exec 9>"/tmp/yt-bench-$TOOL.lock"   # --retry-failed 는 --no-collect 를 같이 줘도 본 락을 쓴다
flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중 — 건너뜀"; exit 0; }
MODEL=$(uv run python -c "import tomllib;print(tomllib.load(open('config.toml','rb')).get('model','sonnet'))")
if [ "$TOOL" = agy ]; then   # DB에 기록할 모델 이름: AGY_MODEL, 없으면 agy 설정의 기본 모델
  YT_MODEL=${AGY_MODEL:-$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.gemini/antigravity-cli/settings.json'))).get('model','agy-default'))")}
else YT_MODEL=$MODEL; fi
export YT_ENGINE=$TOOL YT_MODEL YT_RUN="$(date +%Y-%m-%d_%H%M)-$TOOL"   # YT_RUN: 이번 실행의 리포트 이름(날짜_시분-LLM)
ROUNDS=${ROUNDS:-4}; BUDGET=${BUDGET:-700000}
echo "===== $(date '+%F %T') 시작 (스킬 모드, 역할 $ROLE, 도구 $TOOL, 모델 $YT_MODEL) ====="
if [ "$ROLE" = dev ]; then   # 개발 서버: 서비스 서버의 inbox(의견·액션·별표)를 받아 DB 에 반영한 뒤 시작
  uv run inbox_apply.py; rc=$?
  if [ "$rc" = 2 ]; then echo "$(date '+%F %T') 개발 서버 설정 오류(.env 의 PSNCS_HOST·PSNCS_ID·PSNCS_YT_WATCH_DIR) — 실행을 멈춤"; exit 2; fi
  [ "$rc" = 0 ] || echo "inbox 가져오기 실패(계속 — 다음 실행에서 이어 받음)"
fi
if [ "$RETRY" = 1 ]; then   # 자막 추출 실패 영상만 다시 받고, 받은 영상만 LLM 분석 (YT_STAGES=video 로 다른 단계는 건너뜀)
  export YT_STAGES=video; [ "$COLLECT" = 1 ] && { uv run work.py collect --retry-failed || echo "자막 재시도 수집 실패"; }   # --no-collect 를 같이 주면 이미 받아 둔 것만 LLM 분석
elif [ "$COLLECT" = 1 ]; then uv run work.py collect || echo "수집 단계 실패"; fi
for i in $(seq 1 "$ROUNDS"); do
  uv run work.py start --budget "$BUDGET"
  echo "--- 라운드 $i: $TOOL 세션 시작 $(date '+%T')"
  if [ "$TOOL" = claude ]; then
    claude -p "/yt-daily" --model "$MODEL" --no-session-persistence \
           --allowedTools "Bash(uv run work.py:*)" "Read" "WebSearch" "WebFetch" --permission-mode acceptEdits 2>&1 | tail -n 5
  else
    mkdir -p logs; AL="logs/agy-session-$(date +%F-%H%M%S).jsonl"
    agy -p "/yt-daily" ${AGY_MODEL:+--model "$AGY_MODEL"} --mode accept-edits --output-format stream-json \
        --settings '{"permissions":{"allow":["command(uv run work.py)","command(ls)","command(cat)","command(head)","command(tail)","command(find)","command(grep)","command(wc)","search_web","read_url_content"]}}' > "$AL" 2>&1
    tail -n 1 "$AL" | cut -c1-600                      # 결과 요약(토큰 사용량·거부된 동작 포함). 전체 기록은 $AL
  fi
  uv run work.py status && continue        # more -> 다음 라운드
  break                                    # all_done 또는 stalled(진전 없음: 사용량 한도 등)
done
[ "$FINISH" = 1 ] && uv run work.py finish
# DB 백업: 덤프 → README/HISTORY 갱신 → ~/yt-watcher-later-backup 에 commit·push (실패해도 실행 결과에는 영향 없음)
[ "$FINISH" = 1 ] && { uv run dbbackup.py sync || echo "DB 백업 sync 실패(다음 실행 때 함께 push)"; }   # 개발 서버의 push 가 곧 서비스 서버에 전달되는 내용(서비스 서버는 pull 만)
echo "===== $(date '+%F %T') 종료 ====="
