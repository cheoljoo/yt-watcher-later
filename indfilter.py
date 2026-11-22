"""지표 페이지(indicators.html, indicator_trends.html) 공용: 지표의 국가 분류(한국/미국/글로벌·기타)와 국가·분류 선택 UI.
국가는 DB 컬럼이 아니라 출처·심볼·이름으로 매번 판정한다(규칙은 아래 상수). 틀린 것은 OVERRIDE 에 이름으로 고정한다."""
import re
from html import escape as e

COUNTRIES = [("kr", "🇰🇷 한국"), ("us", "🇺🇸 미국"), ("gl", "🌐 글로벌·기타")]
CNAME = dict(COUNTRIES)
OVERRIDE = {}      # {지표 이름: "kr"|"us"|"gl"}

KR_SRC = {"ecos", "rone", "kofia", "krx"}
KR_KW = ("한국", "국내", "코스피", "코스닥", "서울", "한은", "한국은행", "금통위", "원/달러", "원달러", "삼성", "하이닉스", "현대", "기아", "LG", "SK", "네이버", "카카오", "POSCO", "포스코",
         "한화", "HD", "두산", "효성", "에코프로", "셀트리온", "한미", "KB", "신한", "하나금융", "우리금융", "KRX", "KOFIA", "한국부동산원", "전국", "수도권", "강남", "경기도", "통계청", "국고채",
         "공정거래위원회", "산업통상", "외국인", "개인 투자자", "신용융자", "예탁금", "KAIDA", "원화", "K-", "대한민국", "아파트", "전세", "주택담보", "가계대출", "코스피200", "K200",
         "증권사", "생활물가", "관세청", "시중은행", "국민연금", "상속", "증여", "피부양", "분양", "청약", "국산화", "건강보험", "금융위", "금감원", "정기예금", "국세청", "부동산", "재건축", "재개발", "입주", "건보", "연금저축", "IRP", "기초연금", "코픽스", "주담대", "신용거래융자", "금융투자협회", "증시안정", "주가누르기", "기업가치 제고", "철도망", "소상공인", "백화점", "와이지", "JYP", "반도체 벨트", "정비사업", "강방천", "서울")
US_KW = ("미국", "S&P", "나스닥", "NASDAQ", "다우", "연준", "Fed", "FOMC", "연방", "엔비디아", "알파벳", "구글", "애플", "마이크로소프트", "아마존", "메타", "테슬라", "브로드컴", "팔란티어",
         "오라클", "코어위브", "CoreWeave", "AMD", "인텔", "TSMC", "마벨", "아스테라", "월마트", "TIC", "국채 10년물", "달러 인덱스", "DXY", "러셀", "VIX", "버크셔", "BRK", "GE ", "블랙록", "JP모건",
         "앤트로픽", "Anthropic", "엔트로픽", "오픈AI", "OpenAI", "스페이스X", "버티브", "블랙스톤", "유튜브", "네오클라우드", "엔스케일", "넷플릭스", "젠슨 황", "미 의회", "미 상무부", "미시간", "CME", "페드워치", "필라델피아", "FINRA", "버핏지수", "ADP", "텍사스", "ERCOT", "하이퍼스케일러", "빅테크", "빅 테크", "ISM", "PCE", "비농업", "실업수당", "소비자심리", "건축허가", "주택착공", "재무부", "월가", "트럼프", "AI 인프라")
GL_KW = ("글로벌", "세계", "국제", "OECD", "IMF", "유가", "WTI", "브렌트", "두바이", "금 가격", "구리", "비트코인", "이더리움", "스테이블코인", "중국", "일본", "유럽", "독일", "인도", "신흥국", "엔화", "엔/달러")
KR_STRONG = ("한국", "국내", "코스피", "코스닥", "한은", "한국은행", "금통위", "원/달러", "원달러")
US_STRONG = ("미국", "S&P", "나스닥", "NASDAQ", "연준", "FOMC", "Fed", "연방")
KR_SYM = re.compile(r"(\.KS|\.KQ|^\^KS|^\^KQ|KRW=X)$|^\^K")
FRED_GL = ("POILDUBUSDM", "POILWTIUSDM", "DCOILWTICO", "DCOILBRENTEU")

def _has(name, kws):
    """짧은 영문 키워드(SK·KB·Fed 등)는 대소문자·단어 경계까지 맞춰야 'risk' 같은 단어에 걸리지 않는다."""
    for k in kws:
        if k.isascii() and k.strip().isalnum() and len(k.strip()) <= 4:
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(k.strip()) + r"(?![A-Za-z])", name): return True
        elif k.lower() in name.lower(): return True
    return False

def country_of(ind):
    """ind: indicators 행(name, source, symbol). -> 'kr' | 'us' | 'gl'"""
    name = ind["name"] or ""
    if name in OVERRIDE: return OVERRIDE[name]
    src, sym = ind["source"] or "none", ind["symbol"] or ""
    if src in KR_SRC: return "kr"
    if src == "multpl": return "us"
    if src == "fred":
        if sym in FRED_GL: return "gl"
        return "kr" if sym.startswith("KOR") or (_has(name, KR_STRONG) and not _has(name, US_STRONG)) else "us"   # FRED 에도 OECD 한국 계열이 있다
    if src == "yahoo":
        if KR_SYM.search(sym): return "kr"
        if sym.endswith(".T") or sym.endswith(".HK") or sym.endswith(".SS") or sym.endswith(".L") or sym.endswith(".DE") or sym.endswith(".PA") or sym.endswith(".AS"): return "gl"
        if "=F" in sym or sym.endswith("-USD") or "=X" in sym: return "gl"
        return "us"
    ks, us_ = _has(name, KR_STRONG), _has(name, US_STRONG)       # 나라를 직접 말한 단어
    if ks and us_: return "gl"       # 한국·미국을 함께 다루는 지표(예: 한·미 선행지수 비교)
    if ks: return "kr"
    if us_: return "us"
    k, u = _has(name, KR_KW), _has(name, US_KW)                     # 기업·기관 이름 같은 간접 단서
    if k and u: return "gl"
    return "kr" if k else "us" if u else "gl"

def sort_key(ind, cat_order=()):
    c = ind["category"] or "기타"
    return ([x[0] for x in COUNTRIES].index(country_of(ind)), cat_order.index(c) if c in cat_order else len(cat_order), c)

def head_country(k, n=None):
    return f"<h2 class='cat-h ind-grp' data-g='{k}'>{CNAME[k]}{'' if n is None else f' <span class=meta>({n})</span>'}</h2>"

def head_cat(k, c, icon, n):
    return f"<h3 class='sub-h ind-grp' data-g='{k}|{e(c)}' style='font-size:16px;margin:22px 0 -2px'>{icon} {e(c)} <span class=meta>({n})</span></h3>"

def row_head(g, text, cols=4):
    """표 안의 그룹 머리글 행. th 로 만들어 table.num 의 번호 매기기(td:first-child)에 걸리지 않게 한다."""
    return f"<tr class='ind-grp' data-g='{g}'><th colspan={cols} style='text-align:left;background:var(--chip,#eef)'>{text}</tr>"

def attrs(ind, count=True, cls=""):
    """목록 항목(행·카드)에 붙일 data 속성. count=False 는 같은 지표가 한 페이지에 두 번 나올 때 두 번째(개수 집계 제외)."""
    return f"class='{cls + ' ' if cls else ''}ind-it' data-k='{country_of(ind)}' data-c='{e(ind['category'] or '기타')}'" + (" data-n=1" if count else "")

BAR = ("<div style='margin:14px 0;display:flex;gap:14px;flex-wrap:wrap;align-items:center'>"
       "<label>🌏 국가 <select id=if-k style='font:inherit;padding:4px 8px'></select></label>"
       "<label>🏷️ 분류 <select id=if-c style='font:inherit;padding:4px 8px'></select></label>"
       "<span class=meta id=if-info></span></div>")

JS = """<script>(function(){
var KN=%s,kS=document.getElementById('if-k'),cS=document.getElementById('if-c'),info=document.getElementById('if-info'),
 its=[].slice.call(document.querySelectorAll('.ind-it')),gh=[].slice.call(document.querySelectorAll('.ind-grp')),
 cnt=[].slice.call(document.querySelectorAll('[data-count-of]')),order=[];
var base=its.filter(function(x){return x.dataset.n});
base.forEach(function(x){if(order.indexOf(x.dataset.c)<0)order.push(x.dataset.c)});
function inK(x,k){return k==='all'||x.dataset.k===k}
function fillK(){kS.innerHTML='<option value=all>모두 ('+base.length+')</option>';Object.keys(KN).forEach(function(k){var n=base.filter(function(x){return x.dataset.k===k}).length;if(n)kS.innerHTML+='<option value='+k+'>'+KN[k]+' ('+n+')</option>'})}
function fillC(){var k=kS.value,keep=cS.value,m={};base.forEach(function(x){if(inK(x,k))m[x.dataset.c]=(m[x.dataset.c]||0)+1});
 var tot=base.filter(function(x){return inK(x,k)}).length;cS.innerHTML='<option value=all>모두 ('+tot+')</option>';
 order.forEach(function(c){if(m[c])cS.innerHTML+='<option value="'+c+'">'+c+' ('+m[c]+')</option>'});cS.value=m[keep]?keep:'all'}
function apply(){var k=kS.value,c=cS.value;
 its.forEach(function(x){x.hidden=!(inK(x,k)&&(c==='all'||x.dataset.c===c))});
 gh.forEach(function(h){var g=h.dataset.g,any=its.some(function(x){return !x.hidden&&(g.indexOf('|')<0?x.dataset.k:x.dataset.k+'|'+x.dataset.c)===g});h.hidden=!any});
 cnt.forEach(function(s){var sc=document.getElementById(s.dataset.countOf);s.textContent=sc?[].slice.call(sc.querySelectorAll('.ind-it')).filter(function(x){return !x.hidden}).length:''});
 info.textContent=base.filter(function(x){return !x.hidden}).length+'개 표시'}
kS.onchange=function(){fillC();apply()};cS.onchange=apply;fillK();fillC();apply()})();
</script>"""

def js(): return JS % ("{" + ",".join(f"'{k}':'{v}'" for k, v in COUNTRIES) + "}")
