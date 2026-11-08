# yt-watcher-later

YouTube 재생목록(예: `my-watch-later`)에 저장해 둔 영상을 매일 새벽 자동으로 수집해
스크립트(자막 원문)를 저장하고, Claude로 요약·분류·분석한 뒤 SQLite와 일별 HTML/JSON
리포트로 정리하는 도구입니다.

## 하는 일

1. `config.toml`의 `[[playlists]]`(소유자 owner별 여러 개)에 적힌 공개/일부공개 재생목록을 읽어 아직 처리하지 않은 영상을 찾는다 (쿠키 불필요).
2. 영상마다 `yt-dlp`로 메타데이터(info.json), 댓글, 자막을 받아 스크립트 텍스트로 정리한다.
3. 영상마다 `claude -p`(Claude 구독 계정, API 키 불필요)를 한 번 호출해 구조화된 분석을 받는다.
   - 카테고리(경제/AI/IT/…)와 2단계 태그, 추가 태그
   - 요약, 키워드, 등장 인물, 언급된 소스·git 링크, 댓글 중 의미 있는 내용
   - 경제 영상: 매크로 국면과 근거, 봐야 할 지표, 나중에 확인할 항목(확인 예정일 포함)
4. 결과를 SQLite(`data/watchlater.db`)에 저장하고, 처리일별 HTML 리포트와 JSON을 만든다.
5. 생방송 출신이라 스크립트가 없던 영상은 7일 뒤 한 번만 다시 시도하고, 그래도 없으면 포기한다.

처리는 3단계다. (1) `fetcher.py`가 yt-dlp로 **병렬 수집**하며 429가 나면 병렬 수를 절반으로 줄이고 잠잠하면 다시 늘린다.
수집 로그는 `logs/collect-날짜.log`에 모은다. (2) 영상별로 Claude를 개별 호출해 분석한다(`parallel_analyze`개 병렬).
(3) 결과를 DB에 저장한다. 실패한 영상은 다음 실행에서 다시 시도하고, 구독 사용량 한도(429)가 나오면 남은 분석을 안전하게 미룬다.
각 영상에는 저장한 사람(`owner`)과 재생목록 이름이 기록되고 리포트에 표시된다.

## 구성

| 파일 | 역할 |
|---|---|
| `main.py` | 전체 흐름 (재생목록 → 수집 → 분석 → 저장 → 리포트) |
| `fetch_list.py` | 재생목록 조회 |
| `fetcher.py` | 병렬·적응형 수집 + 로그 모음 |
| `collect.py` | yt-dlp로 info.json·댓글·자막 수집 (429 재시도 포함) |
| `vtt_to_text.py` | VTT 자막 → 중복 제거한 텍스트 |
| `analyze.py` | `claude -p --json-schema`로 구조화 분석 |
| `db.py` | SQLite 스키마 (videos, people, links, tags, checks) |
| `report.py` | 일별 HTML 리포트 (카테고리 → 주제 → 업로드일 순) |
| `stats.py` | 시청 성향 분석 페이지(`stats.html`): 많이 보는 채널·자주 나오는 인물 (DB만 사용, 리포트 생성 끝에 실행) |
| `highlight.py` | 인상 깊은 영상 모음(`highlights.html`): `/yt-highlight URL` 스킬이 상세 분석을 만들어 `submit` |
| `export_json.py` | DB → 사람이 읽기 좋은 JSON |
| `check.py` | 확인 항목 결과 기록, 시청일 기록 |
| `run_daily.sh` | cron 진입점 — 항목마다 `claude -p` 를 호출하는 방식 (중복 실행 방지) |
| `run_skill.sh` | cron 진입점 — **스킬 모드**: 수집(코드) → Claude 세션 1개가 `yt-daily` 스킬로 모든 작업 처리 → 리포트(코드) |
| `work.py` | 스킬 모드 작업 관리자 (`collect`/`start`/`next`/`submit`/`skip`/`status`/`finish`) |
| `.claude/skills/yt-daily/` | 스킬 정의. `work.py next` 로 작업을 받아 JSON 을 만들어 제출하는 반복 절차 |
| `config.toml` | 재생목록 URL, 언어, 모델 등 설정 |

## 요구 사항

- Linux, [uv](https://docs.astral.sh/uv/), Python 3.13
- `yt-dlp` (uv tool 등으로 설치)
- Claude Code CLI(`claude`)에 구독 계정으로 로그인되어 있을 것
- 대상 재생목록은 **공개 또는 일부 공개**여야 한다. ("나중에 볼 동영상(WL)"은 로그인 쿠키가
  필요하고 세션이 자주 무효화되어 자동화에 맞지 않는다.)

## 사용법

```bash
# config.toml 의 playlist_url 을 본인 재생목록으로 수정한 뒤
uv run main.py                 # 새 영상 전부 처리
uv run main.py --limit 3       # 최대 3개만
uv run main.py --only VIDEO_ID # 특정 영상만 (이미 처리했어도 다시)
uv run main.py --show-top 20   # 재생목록 상위 20개 보기

uv run export_json.py          # reports/watchlater.json (스크립트 원문 제외)
uv run export_json.py --full   # data/watchlater_full.json (원문 포함)

uv run check.py list --due     # 확인할 시점이 된 항목
uv run check.py set ID --status confirmed --result "..." --opinion "..." --reason "..."
uv run check.py watched VIDEO_ID [YYYY-MM-DD]
```

스킬 모드(권장 실험): 스킬 안에서는 `claude -p` 를 다시 호출하지 않는다. cron 이 `claude -p /yt-daily` 를 **한 번**
실행하면, 그 세션이 `work.py next`로 DB의 대기 작업(영상 분석·지표 설명·출처 매핑·의미 해설·매크로 위치·확인 판정)을
차례로 받아 `submit` 한다. 수집은 새 영상을 전부 하지만, **Claude 영상 분석은 한 번 실행에 최대 `max_analyze`(config.toml, 기본 30)개**이고 나머지는 다음 날로 넘어간다(재생목록 앞쪽부터). 아직 분석되지 않은 영상 수는 `reports/index.html`(과 오늘 리포트)에 표시된다. 입력이 세션 한도(`BUDGET`, 기본 70만자)를 넘으면 다음 라운드(`ROUNDS`, 기본 2)에서 이어간다.

매일 자동 실행 예 (crontab):

```
0 1 * * * /path/to/yt-watcher-later/run_daily.sh >> /path/to/yt-watcher-later/logs/daily.log 2>&1
```

`run_daily.sh`의 `cd` 경로와 `PATH`는 환경에 맞게 고쳐서 쓴다.

## 산출물

- `data/<영상ID>/` — `transcript.txt`, 자막 원본(`.vtt`), `info.json`, `analysis.json`, `summary.md`
- `data/watchlater.db` — SQLite (스크립트 원문 포함)
- `reports/YYYY-MM-DD.html`, `reports/index.html`, `reports/watchlater.json`

이 산출물에는 개인 시청 기록이 담기므로 저장소에는 올리지 않는다 (`.gitignore`).
리포트를 웹으로 공개할 때는 `reports/` 폴더만 노출하고, 접근 제한 여부를 스스로 판단할 것.

## 주의

- YouTube가 요청이 많으면 `HTTP 429`를 돌려준다. 한글 자막을 먼저 받고 없을 때만 영어를
  요청하며, 요청 간 대기와 재시도를 둔다.
- 요약·분류·전망은 모델의 해석이며 자막은 자동 음성인식이라 오인식이 있을 수 있다.
  투자 판단의 근거로 쓰기 전에 원문과 대조할 것.

## 라이선스

Apache License 2.0 — [LICENSE](LICENSE) 참고.
