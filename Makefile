# yt-watcher-later 자주 쓰는 작업 모음
#
# 사용법:  make            → 이 도움말
#          make <대상>      → 해당 작업 실행   (예: make report, make backup)
#
# 이 프로젝트가 하는 일 (한 줄 요약)
#   내 YouTube '나중에 볼 동영상' 재생목록을 수집 → 자막·AI 분석 → SQLite(data/watchlater.db) 저장
#   → HTML 리포트(reports/) 생성 → nginx 로 공개(psncs.iptime.org/yt_watch_later/).
#   매일 01:00 cron 이 `run_skill.sh --agy` 를 실행한다 (crontab -l 로 확인). 역할(개발/서비스)은 아래 '두 역할' 절 참고.
#
# 규칙: Python 은 반드시 `uv` 로만 실행한다 (pip/venv 직접 사용 금지).
#       아래 모든 python 명령은 `uv run` 이다.
#
# 대상 이름 옆의 '##' 주석이 도움말에 그대로 표시된다.

UV      ?= uv run
# DB 백업을 둘 별도 저장소(비공개). dbbackup.py 와 같은 기본값 — YT_BACKUP_DIR 로 바꿀 수 있다.
BACKUP  ?= $(or $(YT_BACKUP_DIR),$(HOME)/yt-watcher-later-backup)
BACKUP_REMOTE ?= https://github.com/cheoljoo/yt-watcher-later-backup.git
PROJ    := $(CURDIR)

.DEFAULT_GOAL := help
.PHONY: help report daily daily-claude collect status finish check-due export retry-subs retry-subs-collect \
        opinion-status opinion-restart opinion-log cron-show \
        backup backup-verify backup-restore backup-push \
        role dev-init service-sync service-force inbox-status inbox-apply inbox-dry backup-status cron-dev cron-service

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

retry-subs-collect: ## 자막(Script) 추출에 실패한 영상만 다시 받기 (yt-dlp → youtube-transcript-api 폴백, LLM 분석은 안 함)
	$(UV) work.py collect --retry-failed

retry-subs: ## 자막 추출 실패 영상을 다시 받고, 받은 영상은 LLM(agy)으로 다시 분석 + 리포트·백업 (make retry-subs TOOL=claude 로 Claude 사용)
	./run_skill.sh --$(or $(TOOL),agy) --retry-failed

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

backup-push: ## 덤프 + README·HISTORY 갱신 + 백업 저장소 commit + push (매일 새벽 run_skill.sh 끝에서도 자동 실행)
	$(UV) dbbackup.py sync $(BACKUP)

# ── 두 역할(개발 서버 / 서비스 서버) ───────────────────────────────────────────
# 개발 서버(dev): 수집·AI·DB 원본·리포트·백업 push. 시작할 때 서비스 서버의 inbox 를 받아 DB 에 반영한다.
# 서비스 서버(service, psncs): 백업 저장소를 pull 해 BACKUP_TIME(백업이 끝난 시각)이 달라졌으면 DB 를 다시 만들고 web 서비스. 사용자 입력은 inbox 에 모은다.
# 역할은 이 컴퓨터 이름(config.toml service_hostnames)으로 자동 판단한다. config.toml 의 split_from 시각 전에는 서비스 서버도 예전처럼(legacy) 전부 한다.
role: ## 이 컴퓨터의 역할(legacy/service/dev)과 판단 이유
	$(UV) role.py --why

dev-init: ## (개발 서버, 처음 한 번) 백업 저장소를 받아 DB 를 복원한다. 이후 프로젝트 폴더 .env 에 PSNCS_HOST·PSNCS_ID·PSNCS_YT_WATCH_DIR 을 적는다
	@test -d $(BACKUP)/.git || git clone $(BACKUP_REMOTE) $(BACKUP)
	@test -f data/watchlater.db && echo "data/watchlater.db 가 이미 있어 복원하지 않음" || { mkdir -p data && $(UV) dbbackup.py restore $(BACKUP) data/watchlater.db; }
	@echo "다음: 프로젝트 폴더 .env 에  PSNCS_HOST=psncs.iptime.org  PSNCS_ID=<사용자>  PSNCS_YT_WATCH_DIR=~/code/yt-watcher-later  (비밀번호 접속이면 PSNCS_PASSWD, 포트는 PSNCS_PORT)  를 적고(없으면 daily 가 오류로 멈춤)  make inbox-dry  로 ssh 연결 확인, make cron-dev  로 cron 등록"

service-sync: ## (서비스 서버) 백업 pull → 백업 시각(BACKUP_TIME)이 달라졌으면 DB 복원·교체 + 리포트 다시 만들기 (cron 이 10분마다 자동으로도 함)
	$(UV) service_sync.py

service-force: ## (서비스 서버) 백업 시각이 같아도 다시 복원
	$(UV) service_sync.py --force

inbox-status: ## (서비스 서버) 개발 서버가 아직 안 가져간 입력(inbox) 개수
	$(UV) inbox.py

inbox-dry: ## (개발 서버) ssh 로 서비스 서버에 쌓인 입력 개수만 확인(.env 의 PSNCS_* 와 ssh 연결 확인용, 아무것도 가져오거나 지우지 않음)
	$(UV) inbox_apply.py --dry

inbox-apply: ## (개발 서버) ssh/scp 로 서비스 서버 inbox 를 가져와 DB 에 반영하고 서비스 서버의 파일 삭제 (daily 가 시작할 때 자동으로도 함)
	$(UV) inbox_apply.py

backup-status: ## 백업 저장소의 마지막 백업 시각(BACKUP_TIME)과 서비스 서버가 마지막으로 복원한 백업 시각
	@echo "백업 저장소의 마지막 백업 시각:        $$(head -1 $(BACKUP)/BACKUP_TIME 2>/dev/null || echo '없음')   (만든 컴퓨터: $$(sed -n 2p $(BACKUP)/BACKUP_TIME 2>/dev/null))"
	@echo "서비스 서버가 마지막으로 복원한 시각:  $$(head -1 data/_service/last_backup_time 2>/dev/null || echo '-')"

cron-dev: ## (개발 서버) 매일 01:00 run_skill.sh --agy 를 crontab 에 등록(이미 있으면 교체)
	@( crontab -l 2>/dev/null | grep -v '# yt-role:dev' ; echo "0 1 * * * $(PROJ)/run_skill.sh --agy >> $(PROJ)/logs/daily.log 2>&1  # yt-role:dev" ) | crontab -
	@crontab -l | grep 'yt-role:dev'

cron-service: ## (서비스 서버) 10분마다 service_sync.py 를 crontab 에 등록(기존 01:00 줄은 그대로 둠 — 분리 전에는 legacy 로 예전처럼 동작)
	@( crontab -l 2>/dev/null | grep -v '# yt-role:service' ; echo "*/10 * * * * cd $(PROJ) && PATH=$(HOME)/.local/bin:/usr/bin:/bin flock -n /tmp/yt-service-sync.lock uv run python service_sync.py >> $(PROJ)/logs/service.log 2>&1  # yt-role:service" ) | crontab -
	@crontab -l | grep 'yt-role:service'
