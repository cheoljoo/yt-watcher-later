#!/usr/bin/env bash
# cron 진입점(스킬 모드): 수집(코드) -> AI 세션(yt-daily 스킬; 필요하면 여러 라운드) -> 리포트(코드).
# 사용:  ./run_skill.sh [--claude | --agy] [--no-collect] [--no-finish]      (기본 --claude)
#   --claude  Claude Code(`claude -p /yt-daily`)로 처리      --agy  agy CLI(`agy -p /yt-daily`)로 처리
# 환경변수: ROUNDS(기본 2) BUDGET(세션 입력 상한, 기본 70만자) MAX_ANALYZE(영상 분석 상한) AGY_MODEL(agy 모델, 비우면 agy 기본값)
export PATH="/home/cheoljoo/.claude-wrapper/bin:/home/cheoljoo/.local/bin:/usr/bin:/bin"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
TOOL=claude; COLLECT=1; FINISH=1
for a in "$@"; do case "$a" in
  --claude) TOOL=claude;; --agy) TOOL=agy;; --no-collect) COLLECT=0;; --no-finish) FINISH=0;;
  *) echo "알 수 없는 옵션: $a (--claude | --agy | --no-collect | --no-finish)"; exit 2;; esac; done
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec 9>/tmp/yt-watcher-later.lock          # run_daily.sh 와 같은 락 — 동시에 돌지 않는다 (벤치마크 사본은 별도 락)
[ "$COLLECT" = 1 ] || exec 9>"/tmp/yt-bench-$TOOL.lock"
flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중 — 건너뜀"; exit 0; }
MODEL=$(uv run python -c "import tomllib;print(tomllib.load(open('config.toml','rb')).get('model','sonnet'))")
if [ "$TOOL" = agy ]; then   # DB에 기록할 모델 이름: AGY_MODEL, 없으면 agy 설정의 기본 모델
  YT_MODEL=${AGY_MODEL:-$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.gemini/antigravity-cli/settings.json'))).get('model','agy-default'))")}
else YT_MODEL=$MODEL; fi
export YT_ENGINE=$TOOL YT_MODEL YT_RUN="$(date +%Y-%m-%d_%H%M)-$TOOL"   # YT_RUN: 이번 실행의 리포트 이름(날짜_시분-LLM)
ROUNDS=${ROUNDS:-2}; BUDGET=${BUDGET:-700000}
echo "===== $(date '+%F %T') 시작 (스킬 모드, 도구 $TOOL, 모델 $YT_MODEL) ====="
[ "$COLLECT" = 1 ] && { uv run work.py collect || echo "수집 단계 실패"; }
for i in $(seq 1 "$ROUNDS"); do
  uv run work.py start --budget "$BUDGET"
  echo "--- 라운드 $i: $TOOL 세션 시작 $(date '+%T')"
  if [ "$TOOL" = claude ]; then
    claude -p "/yt-daily" --model "$MODEL" --no-session-persistence \
           --allowedTools "Bash(uv run work.py:*)" "Read" --permission-mode acceptEdits 2>&1 | tail -n 5
  else
    mkdir -p logs; AL="logs/agy-session-$(date +%F-%H%M%S).jsonl"
    agy -p "/yt-daily" ${AGY_MODEL:+--model "$AGY_MODEL"} --mode accept-edits --output-format stream-json \
        --settings '{"permissions":{"allow":["command(uv run work.py)","command(ls)","command(cat)","command(head)","command(tail)","command(find)"]}}' > "$AL" 2>&1
    tail -n 1 "$AL" | cut -c1-600                      # 결과 요약(토큰 사용량·거부된 동작 포함). 전체 기록은 $AL
  fi
  uv run work.py status && continue        # more -> 다음 라운드
  break                                    # all_done 또는 stalled(진전 없음: 사용량 한도 등)
done
[ "$FINISH" = 1 ] && uv run work.py finish
echo "===== $(date '+%F %T') 종료 ====="
