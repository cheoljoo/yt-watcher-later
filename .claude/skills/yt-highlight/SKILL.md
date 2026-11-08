---
name: yt-highlight
description: 유튜브 영상 URL 하나를 받아 '제일 인상 깊었던 영상' 모음(reports/highlights.html)에 매우 상세한 분석으로 추가한다. 사용 예 /yt-highlight https://www.youtube.com/watch?v=... [왜 인상 깊었는지 메모]
user-invocable: true
---

프로젝트 `~/code/yt-watcher-later` 에서 영상 한 개를 상세히 분석해 '인상 깊은 영상' 페이지에 추가한다.
수집·검증·DB 저장·페이지 생성은 `highlight.py` 가 하고, 당신은 분석 JSON 한 개를 만드는 일만 한다. `claude -p`/`agy -p` 를 다시 호출하지 않는다.

## 절차

1. 인자에서 URL(또는 11자리 영상 ID)과, 남은 글이 있으면 그것을 사용자 메모로 삼는다. URL 이 없으면 한 번만 물어본다.
2. `uv run highlight.py prepare "URL" --note "메모"` 를 실행한다 (메모가 없으면 `--note` 생략). 출력 JSON 의 `id`, `input_file`, `schema_file`, `out_file` 을 쓴다.
3. `input_file` 을 Read 로 끝까지 읽는다 (`allow_large: true`; 길면 offset/limit 으로 나눠 **전부** 읽는다). 파일 앞부분의 `# 지시` 를 따른다.
4. `schema_file`(JSON Schema)에 맞춰 분석 JSON 을 만들어 Write 로 `out_file` 에 저장한다.
   - 매우 상세하게: outline(구간별 6~15개), key_points(8~15개, 각 3~5문장), evidence(주장·근거·한계), numbers, concepts, lessons(5개 이상), business(가능/조건부/어려움 + 아이디어 + 단계별 방법 + 위험), action_items, caveats, further_questions.
   - 영상에 없는 내용을 지어내지 않는다. 자막 오인식은 문맥으로 보정하되 caveats 에 밝힌다.
5. 제출한다: `uv run highlight.py submit ID --file OUT_FILE`
   - 사용 중인 도구에 맞게 환경변수를 붙인다: Claude Code 이면 `YT_ENGINE=claude YT_MODEL=<현재 모델 이름>`, agy 이면 `YT_ENGINE=agy YT_MODEL=<현재 모델 이름>`.
   - 스키마 검증 실패 메시지가 나오면 고쳐서 다시 제출한다.
6. `OK ... 저장` 이 나오면 한두 줄로 결과(제목, 페이지 경로 `reports/highlights.html`)만 알린다.

## 규칙

- 모든 명령은 포그라운드로 실행한다. 임의로 다른 영상을 분석하지 않는다.
- 이미 추가된 영상이면 같은 ID 로 덮어쓴다(새 분석으로 갱신).
- 목록 확인: `uv run highlight.py list`, 페이지만 다시 만들기: `uv run highlight.py build`.
