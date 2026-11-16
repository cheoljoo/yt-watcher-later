# yt-watcher-later 자주 쓰는 작업 모음
#
# 사용법:  make            → 이 도움말
#          make <대상>      → 해당 작업 실행   (예: make report, make backup)
#
# 이 프로젝트가 하는 일 (한 줄 요약)
#   내 YouTube '나중에 볼 동영상' 재생목록을 수집 → 자막·AI 분석 → SQLite(data/watchlater.db) 저장
#   → HTML 리포트(reports/) 생성 → nginx 로 공개(psncs.iptime.org/yt_watch_later/).
#   매일 01:00 cron 이 `run_skill.sh --agy` 를 실행한다 (crontab -l 로 확인).
#
# 규칙: Python 은 반드시 `uv` 로만 실행한다 (pip/venv 직접 사용 금지).
#       아래 모든 python 명령은 `uv run` 이다.
#
# 대상 이름 옆의 '##' 주석이 도움말에 그대로 표시된다.

UV      ?= uv run
# DB 백업을 둘 별도 저장소(비공개). dbbackup.py 와 같은 기본값 — YT_BACKUP_DIR 로 바꿀 수 있다.
BACKUP  ?= $(or $(YT_BACKUP_DIR),$(HOME)/yt-watcher-later-backup)

.DEFAULT_GOAL := help
.PHONY: help report daily daily-claude collect status finish check-due export \
        opinion-status opinion-restart opinion-log cron-show \
        backup backup-verify backup-restore backup-commit backup-push

help: ## 이 도움말 보기
	@echo "yt-watcher-later — 사용 가능한 make 대상"; echo
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z0-9_-]+:.*## /{printf "  \033[1m%-16s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)
	@echo; echo "값 지정 예:  make backup-restore DEST=/tmp/restored.db     (BACKUP=백업폴더 도 바꿀 수 있음)"

# ── 일일 실행 (평소엔 cron 이 알아서 한다. 손으로 돌릴 때만) ─────────────────────
daily: ## 수집→AI 분석(agy)→리포트 전체 실행 (cron 과 같은 동작, 오래 걸림)
	./run_skill.sh --agy

daily-claude: ## 위와 같되 AI 도구를 Claude 로 실행 (Claude 사용량을 씀)
	./run_skill.sh --claude

collect: ## 재생목록에서 새 영상만 수집 (AI 분석은 안 함)
	$(UV) work.py collect

status: ## 오늘 작업 큐 상태 (more/all_done/stalled 와 제출 건수)
	-$(UV) work.py status

finish: ## 지표 시세 반영 + 리포트·JSON 재생성 + (백업 폴더가 있으면) DB 백업
	$(UV) work.py finish

# ── 리포트 / 데이터 ─────────────────────────────────────────────────────────
report: ## DB 로부터 reports/*.html 전부 다시 만들기 (AI·네트워크 사용 안 함, 몇 초)
	$(UV) python -c "import db, report; report.build_all(db.connect())"

check-due: ## 확인할 시점이 된 '확인 항목' 목록 보기
	$(UV) check.py list --due

export: ## DB 를 JSON 으로 내보내기 (reports/watchlater.json, data/watchlater_full.json)
	$(UV) export_json.py
	$(UV) export_json.py --full

# ── 의견·액션 저장 서버 (리포트의 💬 저장 / 🎯 버튼이 호출) ───────────────────────
# systemd 사용자 서비스 yt-opinion (127.0.0.1:8650). nginx 가 /yt_watch_later/api/ 를 여기로 넘긴다.
# 코드(opinions.py, opinion_server.py, actions.py)를 고친 뒤에는 opinion-restart 가 필요하다.
opinion-status: ## 의견 저장 서버가 떠 있는지 확인
	systemctl --user status yt-opinion --no-pager | head -8
	@curl -s -m 5 http://127.0.0.1:8650/actions | head -c 120; echo

opinion-restart: ## 의견 저장 서버 재시작 (코드를 바꾼 뒤)
	systemctl --user restart yt-opinion
	@sleep 1; curl -s -m 5 http://127.0.0.1:8650/actions | head -c 120; echo

opinion-log: ## 의견 저장 서버 로그 (최근 30줄)
	journalctl --user -u yt-opinion -n 30 --no-pager

cron-show: ## 이 프로젝트의 cron 등록 내용과 최근 실행 로그 끝부분
	@crontab -l | grep -A1 yt-watcher-later || true
	@echo "--- logs/daily.log (끝 15줄)"; tail -n 15 logs/daily.log 2>/dev/null || true

# ── DB 백업 (git 에 올릴 수 있는 텍스트: schema.sql + 표별 .jsonl, 바뀐 줄만 diff) ──
# DB 는 이 저장소에 올라가지 않는다(.gitignore). 백업은 별도 비공개 저장소($(BACKUP))에 둔다.
# ※ 의견·시청 기록·자막이 들어 있으므로 공개 저장소에는 절대 올리지 말 것.
backup: ## DB → 백업 폴더(~/yt-watcher-later-backup)에 텍스트 덤프 (매일 새벽 finish 가 자동으로도 함)
	$(UV) dbbackup.py dump $(BACKUP)

backup-verify: ## 지금 DB 와 백업 내용이 같은지 비교 (다르면 오류 종료)
	$(UV) dbbackup.py verify $(BACKUP)

backup-restore: ## 백업 → 새 DB 파일로 복구:  make backup-restore DEST=/경로/새.db  (기존 파일은 덮어쓰지 않음)
	@test -n "$(DEST)" || { echo "DEST=새DB경로 를 지정하세요. 예: make backup-restore DEST=/tmp/restored.db"; exit 2; }
	$(UV) dbbackup.py restore $(BACKUP) $(DEST)
	@echo "복구본 확인 후, 실제 DB 로 쓰려면 서비스·cron 을 멈추고 직접 data/watchlater.db 와 교체하세요."

backup-commit: backup ## 백업을 새로 덤프하고 백업 저장소에 commit (변경 없으면 아무것도 안 함)
	cd $(BACKUP) && git add -A && { git diff --cached --quiet && echo "변경 없음" || git commit -q -m "DB 백업 $$(date +%F)" && git log --oneline -1; }

backup-push: backup-commit ## backup-commit 후 백업 비공개 저장소로 push
	cd $(BACKUP) && git push
