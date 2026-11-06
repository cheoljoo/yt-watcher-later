"""VTT 자막 -> 중복 제거한 순수 텍스트."""
import re, sys, html

def vtt_to_text(path: str) -> str:
    out, prev = [], None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in line or line.isdigit():
            continue
        line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()  # <c>, <00:00:01.000> 태그 제거
        if line and line != prev:                                     # 자동자막의 롤링 중복 제거
            out.append(line); prev = line
    return "\n".join(out)

if __name__ == "__main__":
    sys.stdout.write(vtt_to_text(sys.argv[1]))
