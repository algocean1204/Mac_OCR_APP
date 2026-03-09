# 콘텐츠 타입 분류 모듈
# OCR 텍스트의 각 블록을 한국어/영어/수학/코드/표로 분류한다
# 규칙 기반(정규식)으로 동작하여 모델 로드가 불필요하다
from __future__ import annotations

import re
from enum import Enum


class ContentType(Enum):
    """텍스트 블록의 콘텐츠 유형을 정의한다."""
    KOREAN = "korean"       # 한국어 산문
    ENGLISH = "english"     # 영어 텍스트
    MATH = "math"           # 수학 수식 (LaTeX 포함)
    CODE = "code"           # 프로그래밍 코드
    TABLE = "table"         # 표 구조
    MIXED = "mixed"         # 혼합 콘텐츠


# ── 분류 패턴 ──────────────────────────────────────────────────────────────

# 한글 문자 범위 (자모 + 완성형)
_KOREAN_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

# 영문자 패턴
_ENGLISH_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[a-zA-Z]")

# LaTeX 수식 패턴 — \frac, \sum, \int, ^{}, _{} 등
_MATH_PATTERN: re.Pattern[str] = re.compile(
    r"\\(?:frac|sum|int|sqrt|lim|prod|partial|infty|alpha|beta|gamma|delta|sigma|theta|lambda|mu|pi|omega)"
    r"|[_^]\{[^}]*\}"
    r"|\$[^$]+\$"
    r"|\\(?:left|right|begin|end)\{"
    r"|[≤≥≠±∑∫∏√∞∂∇×÷∈∉⊂⊃∪∩]"
)

# 코드 패턴 — 함수 정의, import, 변수 할당, 중괄호 블록 등
_CODE_PATTERN: re.Pattern[str] = re.compile(
    r"(?:^|\s)(?:def|class|import|from|return|elif|yield|async|await)\s+"
    r"|(?:function|const|let|var|=>|===|!==)\s*"
    r"|(?:public|private|protected|static|void)\s+"
    r"|^\s{4,}(?:return|if|for|while|try|except|raise)\s+"  # 들여쓰기된 제어 구문
    r"|[{}();]\s*$"
    r"|^\s*#\s*(?:include|define|ifdef|ifndef|pragma)"
    r"|(?:print|println|console\.log|System\.out)\s*\("
    r"|(?:SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|CREATE|ALTER|DROP)\s+"
    r"|^\s*(?:self\.|cls\.|this\.)"  # 객체 참조
    r"|(?:__init__|__main__|__name__)"  # 파이썬 특수 속성
    , re.MULTILINE,
)

# 표 구조 패턴 — 탭 구분, 파이프 구분, 연속 공백 정렬
_TABLE_PATTERN: re.Pattern[str] = re.compile(
    r"\t[^\t]+\t"              # 탭으로 구분된 열 (최소 2개 탭)
    r"|\|[^|]+\|[^|]+\|"      # 파이프 구분 표 (최소 3개 파이프)
    r"|[-─━]{3,}\s*[-─━]{3,}"  # 수평 구분선
    r"|^\s*\d+\s{3,}\S+\s{3,}" # 숫자 + 여러 공백 + 텍스트 (정렬된 표)
    , re.MULTILINE,
)

# 한국어 고유명사 패턴 — 기관명, 자격증명, 대학명 등
_PROPER_NOUN_INDICATORS: re.Pattern[str] = re.compile(
    r"(?:주식회사|재단법인|사단법인|한국|대한민국|서울|부산|대구|인천|광주|대전|울산|세종)"
    r"|(?:대학교|고등학교|중학교|초등학교|연구원|연구소|진흥원|진흥원)"
    r"|(?:기사|기능사|산업기사|기술사|자격증)"
    r"|(?:교수|박사|석사|학사)"
)


def classify_text(text: str) -> ContentType:
    """텍스트 전체의 주요 콘텐츠 타입을 분류한다.

    각 타입별 신호 강도를 점수화하고 가장 높은 타입을 반환한다.
    복수 타입이 혼재하면 MIXED를 반환한다.

    Args:
        text: 분류할 텍스트 문자열

    Returns:
        가장 지배적인 콘텐츠 타입
    """
    if not text or not text.strip():
        return ContentType.KOREAN  # 기본값

    scores = _calculate_type_scores(text)

    # 최고 점수 타입 결정
    max_score = max(scores.values())
    if max_score == 0:
        return ContentType.KOREAN

    top_types = [t for t, s in scores.items() if s == max_score]

    # 동점이면 MIXED
    if len(top_types) > 1:
        return ContentType.MIXED

    return top_types[0]


def classify_lines(text: str) -> list[tuple[str, ContentType]]:
    """텍스트를 줄 단위로 분류한다.

    연속된 동일 타입 줄은 하나의 블록으로 그룹화하지 않고,
    각 줄의 타입을 개별적으로 반환한다.

    Args:
        text: 분류할 텍스트 문자열

    Returns:
        [(줄 텍스트, 콘텐츠 타입)] 리스트
    """
    result: list[tuple[str, ContentType]] = []

    for line in text.split("\n"):
        if not line.strip():
            result.append((line, ContentType.KOREAN))
            continue
        result.append((line, _classify_single_line(line)))

    return result


def has_proper_nouns(text: str) -> bool:
    """텍스트에 한국어 고유명사가 포함되어 있는지 판정한다.

    Args:
        text: 검사할 텍스트

    Returns:
        True이면 고유명사 포함
    """
    return bool(_PROPER_NOUN_INDICATORS.search(text))


def get_dominant_types(text: str, threshold: float = 0.2) -> list[ContentType]:
    """텍스트에서 임계값 이상의 비율을 차지하는 콘텐츠 타입들을 반환한다.

    Args:
        text: 분석할 텍스트
        threshold: 최소 비율 (0.0~1.0)

    Returns:
        임계값 이상인 콘텐츠 타입 리스트
    """
    scores = _calculate_type_scores(text)
    total = sum(scores.values())
    if total == 0:
        return [ContentType.KOREAN]

    return [t for t, s in scores.items() if s / total >= threshold]


def _calculate_type_scores(text: str) -> dict[ContentType, float]:
    """각 콘텐츠 타입의 신호 강도를 점수화한다."""
    total_chars = len(text)
    if total_chars == 0:
        return {t: 0.0 for t in ContentType}

    korean_chars = len(_KOREAN_CHAR_PATTERN.findall(text))
    english_chars = len(_ENGLISH_CHAR_PATTERN.findall(text))
    math_matches = len(_MATH_PATTERN.findall(text))
    code_matches = len(_CODE_PATTERN.findall(text))
    table_matches = len(_TABLE_PATTERN.findall(text))

    return {
        ContentType.KOREAN: korean_chars / total_chars,
        ContentType.ENGLISH: english_chars / total_chars,
        ContentType.MATH: min(math_matches * 0.15, 1.0),
        ContentType.CODE: min(code_matches * 0.15, 1.0),
        ContentType.TABLE: min(table_matches * 0.2, 1.0),
        ContentType.MIXED: 0.0,
    }


def _classify_single_line(line: str) -> ContentType:
    """단일 줄의 콘텐츠 타입을 분류한다."""
    stripped = line.strip()
    if not stripped:
        return ContentType.KOREAN

    # 표: 탭/파이프 구분
    if _TABLE_PATTERN.search(stripped):
        return ContentType.TABLE

    # 코드: 프로그래밍 키워드
    if _CODE_PATTERN.search(stripped):
        return ContentType.CODE

    # 수학: LaTeX/수식 기호
    if _MATH_PATTERN.search(stripped):
        return ContentType.MATH

    # 한국어 vs 영어: 문자 비율
    korean_count = len(_KOREAN_CHAR_PATTERN.findall(stripped))
    english_count = len(_ENGLISH_CHAR_PATTERN.findall(stripped))

    if korean_count > english_count:
        return ContentType.KOREAN
    if english_count > korean_count:
        return ContentType.ENGLISH

    return ContentType.KOREAN
