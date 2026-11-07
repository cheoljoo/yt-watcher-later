"""Claude 구조화 호출 공통 함수 (구독 계정 `claude -p`)."""
import json, subprocess
from analyze import UsageLimit, _limit

def claude_json(prompt, body, schema, model="sonnet", timeout=900):
    r = subprocess.run(["claude", "-p", prompt, "--model", model, "--tools", "", "--no-session-persistence",
                        "--output-format", "json", "--json-schema", json.dumps(schema)],
                       input=body, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout)[-500:]; raise (UsageLimit if _limit(msg) else RuntimeError)(msg)
    j = json.loads(r.stdout)
    if j.get("is_error"):
        msg = str(j.get("result"))[-500:] + str(j.get("api_error_status") or "")
        raise (UsageLimit if _limit(msg) or j.get("api_error_status") == 429 else RuntimeError)(msg)
    return j.get("structured_output") or json.loads(j["result"])
