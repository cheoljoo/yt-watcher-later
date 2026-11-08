"""자막/설명/댓글 -> 구조화 분석(JSON).  Claude 구독 계정: `claude -p --json-schema`"""
import json, subprocess

CATEGORIES = ["경제", "AI", "IT", "정치·사회", "과학·건강", "기타"]

SCHEMA = {
  "type": "object",
  "required": ["category", "subtag", "extra_tags", "one_liner", "summary_points", "keywords",
               "people", "links", "comments_insight", "lessons", "business", "macro", "checks"],
  "properties": {
    "category": {"type": "string", "enum": CATEGORIES},
    "subtag": {"type": "string"},
    "extra_tags": {"type": "array", "items": {"type": "string"}},
    "one_liner": {"type": "string"},
    "summary_points": {"type": "array", "items": {"type": "string"}},
    "keywords": {"type": "array", "items": {"type": "string"}},
    "people": {"type": "array", "items": {"type": "object", "required": ["name", "role"],
               "properties": {"name": {"type": "string"}, "role": {"type": "string"}}}},
    "links": {"type": "array", "items": {"type": "object", "required": ["url", "kind", "context"],
              "properties": {"url": {"type": "string"},
                             "kind": {"type": "string", "enum": ["git", "source", "paper", "site", "other"]},
                             "context": {"type": "string"}}}},
    "comments_insight": {"type": "string"},
    "lessons": {"type": "array", "items": {"type": "string"}},
    "business": {"type": "object", "required": ["possible", "idea", "how"],
                 "properties": {"possible": {"type": "string", "enum": ["가능", "조건부", "어려움"]},
                                "idea": {"type": "string"}, "how": {"type": "string"}}},
    "macro": {"type": ["object", "null"], "required": ["phase", "phase_reason", "indicators_to_watch"],
              "properties": {"phase": {"type": "string"}, "phase_reason": {"type": "string"},
                             "indicators_to_watch": {"type": "array", "items": {"type": "object",
                                "required": ["name", "why"],
                                "properties": {"name": {"type": "string"}, "why": {"type": "string"}}}}}},
    "checks": {"type": "array", "items": {"type": "object",
               "required": ["kind", "target", "what_to_check", "expectation", "check_date"],
               "properties": {"kind": {"type": "string", "enum": ["indicator", "stock", "event"]},
                              "target": {"type": "string"}, "what_to_check": {"type": "string"},
                              "expectation": {"type": "string"},
                              "check_date": {"type": "string", "description": "YYYY-MM-DD, 반드시 오늘 이후"}}}},
  },
}

PROMPT = """당신은 YouTube 영상 분석가입니다. 아래 입력(제목/채널/설명/댓글/자막)을 읽고 JSON 스키마대로만 답하세요.
자막은 자동 음성인식이라 오인식이 있을 수 있으니 문맥으로 보정해 이해하세요. 모든 값은 한국어(태그 영문 slug 가능).
오늘 날짜: {today}

규칙:
- category: {cats} 중 하나. subtag: 2단계 태그 1개. extra_tags: 추가 태그 0~5개.
  AI 예) skill, llm-wiki, agent, MCP, 모델-출시, RAG, 코딩에이전트 / IT 예) 개발도구, 인프라, 보안, 오픈소스 /
  경제 예) 거시, 금리, 환율, 미국주식, 한국주식, 부동산, 원자재, 산업분석.
  이미 쓰인 태그가 있으면 가급적 재사용(일관성): {vocab}
- summary_points: 핵심 5~8개. people: 영상에 등장/인용된 실명 인물과 직함·소속(진행자·출연자 포함).
- links: 설명·자막·댓글에 언급된 git 저장소/소스/논문/도구 URL (IT·AI 위주, 없으면 빈 배열). 자막에서 이름만 언급되고 URL이 불명확하면 만들어내지 말고 제외.
- comments_insight: 댓글 중 의미 있는 정보·반론·보완만 요약(광고·잡담 제외). 없으면 "없음".
- lessons: 이 동영상에서 시청자가 배울 점 2~5개. 요약의 반복이 아니라 "그래서 내가 무엇을 알게/해보게 되는가"를 구체적으로(개념·방법·주의점·적용해 볼 일).
- business: 이 영상의 내용으로 돈 버는 사업(제품·서비스·콘텐츠·투자 전략 등)을 만들 수 있는가.
  possible = 가능 | 조건부 | 어려움. idea = 어떤 사업인지 한두 문장(대상 고객과 수익 방식 포함), how = 시작하는 구체적 방법·단계·필요한 것·위험.
  어려우면 possible=어려움, idea="해당 없음", how 에 이유를 짧게. 영상 내용에 근거해 현실적으로, 수익을 보장하는 것처럼 쓰지 마세요.
- macro: category가 경제일 때만 채움(아니면 null).
  phase = 영상이 보는 현재 매크로 국면(예: 금리인하 사이클 초입, 경기 둔화, 유동성 확장 등)과 phase_reason(근거),
  indicators_to_watch = 이 영상 맥락에서 봐야 할 경제지표(이름, 왜 봐야 하는지).
- checks: 나중에 영상의 주장·전망이 맞았는지 검증할 항목. kind=indicator|stock|event, target(지표/종목/이벤트명),
  what_to_check(무엇을 확인), expectation(영상의 예상·주장), check_date(확인할 미래 날짜 YYYY-MM-DD, 오늘 이후 — 발표일·만기·실적일 등
  구체적 시점이 있으면 그 날짜, 없으면 합리적 시점). 경제 영상은 가능하면 2~6개, 그 외는 근거가 있을 때만.
- 영상에 없는 내용을 지어내지 마세요.
"""

class UsageLimit(RuntimeError): pass

def _limit(msg): m = msg.lower(); return "429" in m or "usage limit" in m or "rate limit" in m

def build_request(video, collected, vocab, today, max_chars=None):
    """-> (prompt, body). max_chars 가 있으면 자막이 그보다 길 때 앞·뒤만 남긴다(스킬 모드: 컨텍스트 보호)."""
    info, cm = collected["info"], collected["info"].get("comments") or []
    comments = "\n".join(f"- ({c.get('like_count',0)}👍) {c.get('text','')[:300]}" for c in cm[:40]) or "(없음)"
    tr = collected["transcript"]
    if tr and max_chars and len(tr) > max_chars:
        h = max_chars * 2 // 3; tr = tr[:h] + f"\n…(중간 {len(tr) - max_chars:,}자 생략)…\n" + tr[-(max_chars - h):]
    body = (f"[제목] {video['title']}\n[채널] {collected['meta']['channel']}\n[업로드] {collected['meta']['upload_date']}\n"
            f"[설명]\n{(info.get('description') or '')[:2500]}\n\n[댓글]\n{comments}\n\n"
            f"[자막]\n{tr or '(자막 없음 — 제목/설명/댓글만으로 분석, 불확실하면 명시)'}")
    prompt = PROMPT.format(today=today, cats=", ".join(CATEGORIES), vocab=", ".join(vocab) or "(없음)")
    return prompt, body

def analyze(video, collected, vocab, today, model="sonnet"):
    prompt, body = build_request(video, collected, vocab, today)
    r = subprocess.run(["claude", "-p", prompt, "--model", model, "--tools", "", "--no-session-persistence",
                        "--output-format", "json", "--json-schema", json.dumps(SCHEMA)],
                       input=body, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout)[-500:]
        raise (UsageLimit if _limit(msg) else RuntimeError)(msg)
    j = json.loads(r.stdout)
    if j.get("is_error"):
        msg = str(j.get("result"))[-500:] + str(j.get("api_error_status") or "")
        raise (UsageLimit if _limit(msg) or j.get("api_error_status") == 429 else RuntimeError)(msg)
    out = j.get("structured_output") or json.loads(j["result"])
    return out
