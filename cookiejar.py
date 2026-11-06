"""yt-dlp는 종료 시 쿠키 파일을 덮어쓴다 -> 원본(cookies.txt)은 보존하고 임시 복사본을 쓴다."""
import shutil, tempfile, os, atexit
_tmp = None
def cookie_copy(src="cookies.txt"):
    global _tmp
    if _tmp is None:
        fd, _tmp = tempfile.mkstemp(prefix="ytcookies_", suffix=".txt"); os.close(fd); os.chmod(_tmp, 0o600)
        atexit.register(lambda: os.path.exists(_tmp) and os.remove(_tmp))
    shutil.copyfile(src, _tmp)          # 호출 때마다 원본으로 되돌려 사용
    return _tmp
