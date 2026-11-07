#!/usr/bin/env bash
# cron 진입점: 재생목록의 새 영상만 처리하고 HTML 리포트를 갱신한다. 중복 실행 방지(flock).
export PATH="/home/cheoljoo/.claude-wrapper/bin:/home/cheoljoo/.local/bin:/usr/bin:/bin"
# cron 에는 사용자 세션 환경이 없다 — claude 래퍼의 systemd-run --user 가 필요로 한다
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
cd /home/cheoljoo/code/yt-watcher-later || exit 1
exec 9>/tmp/yt-watcher-later.lock
flock -n 9 || { echo "$(date '+%F %T') 이미 실행 중 — 건너뜀"; exit 0; }
echo "===== $(date '+%F %T') 시작 ====="
uv run main.py; rc=$?
echo "===== $(date '+%F %T') 종료 (exit $rc) ====="
exit $rc
