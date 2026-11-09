---
name: yt-daily
description: yt-watcher-later 의 일일 Claude 작업(영상 요약·분류, 지표 설명·출처 매핑·의미 해설, 매크로 위치, 확인 항목 판정)을 한 세션 안에서 모두 처리한다. cron 의 run_skill.sh 가 호출한다.
user-invocable: true
---

이 프로젝트(`~/code/yt-watcher-later`)의 DB 에 쌓인 **Claude 처리 대기 작업**을 이 세션 하나에서 끝까지 처리한다.
수집·시세 조회·DB 저장은 `work.py` 가 하고, 당신은 작업마다 JSON 한 개를 만들어 제출하는 일만 한다.

## 반복 절차

1. `uv run work.py next` 를 실행한다. 출력은 JSON 한 줄이다.
   - `"done": true` 이면 **즉시 종료**한다. 마지막에 한 줄로 "끝: 사유"만 출력한다.
   - 아니면 `task`, `kind`, `input_file`, `schema_file` 이 있다.
2. `input_file` 을 Read 로 읽는다 (`allow_large: true`). 파일에는 `# 지시`(무엇을 만들지)와 `# 입력`이 있다.
3. 지시대로 결과 JSON 을 만든다. 형식은 `schema_file` 의 JSON Schema 를 따른다.
   (같은 kind 의 스키마를 이미 읽었고 기억이 분명하면 다시 읽지 않아도 된다. 제출이 검증에서 실패하면 그때 읽는다.)
4. 결과 JSON 을 Write 로 `data/_work/out/TASK_ID.json` 에 저장한 뒤 제출한다:

   `uv run work.py submit TASK_ID --file data/_work/out/TASK_ID.json`

5. 출력이 `OK ...` 이면 1번으로 돌아간다. 스키마 검증 실패 메시지가 나오면 고쳐서 한 번만 다시 제출한다.
   그래도 실패하면 `uv run work.py skip TASK_ID --reason "이유"` 후 1번으로 간다.

## 규칙

- **허용된 명령 외에는 절대 실행하지 않는다.** `python3`, `grep`, `sqlite3` 등으로 DB·코드를 들여다보지 않는다(거부되면 세션이 멈춘다). 형식이 궁금하면 `schema_file` 만 Read 하고, 모르겠으면 `uv run work.py skip TASK_ID --reason "이유"` 후 다음 작업으로 간다. `done` 이 나올 때까지 계속한다.

- **모든 명령은 포그라운드로 실행하고 결과가 나올 때까지 기다린다.** 백그라운드로 돌리거나 "확인 중"이라고만 답하고 턴을 끝내지 않는다. `done` 이 나오기 전에는 응답을 끝내지 않는다.

- 작업 사이에 설명·요약·확인 질문을 하지 않는다. 도구 호출만 이어서 한다. (토큰 절약)
- 입력에 없는 사실을 지어내지 않는다. 지시문에 적힌 제약(날짜 형식, 열거값, name 은 입력 그대로 등)을 지킨다.
- 도구는 `uv run work.py ...`, Read, 그리고 `data/_work/out/` 아래에 결과를 쓰는 Write 만 쓴다. `claude` 를 다시 실행하거나 웹 검색·DB 직접 접근은 하지 않는다.
- 작업은 서로 독립이다. 앞 영상의 내용을 다음 영상 분석에 섞지 않는다.
- kind 별 요령:
  - `video`: 자막은 자동 음성인식이라 오인식이 있을 수 있다. 문맥으로 보정하되 확신 없는 고유명사는 피한다.
  - `enrich`/`map`/`meaning`/`phase`/`check`: 지시문의 항목 수와 name/id 를 입력과 정확히 일치시킨다. 입력의 모든 항목에 대해 결과를 낸다.
