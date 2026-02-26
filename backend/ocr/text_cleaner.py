# OCR 후처리 텍스트 정제 모듈
# 모델 출력에 섞이는 프롬프트 누출 패턴과 마크다운 기호를 제거한다
# 혼동 문자 보정(correct_confusable_chars)도 이 파이프라인에서 수행한다
from __future__ import annotations

import re

# ── 프롬프트 누출 패턴 ─────────────────────────────────────────────────────────
# 모델이 지시문을 그대로 반복 출력하는 줄의 시작 패턴 목록
_LEAKAGE_LINE_PATTERN: re.Pattern[str] = re.compile(
    r"^\s*\.?\s*("
    r"from the image"
    r"|output only"
    r"|output the"
    r"|print only"
    r"|read (all )?text"
    r"|text block"
    r"|do not (use|write|repeat|include|mention)"
    r"|preserve line"
    r"|the (text|document) may"
    r"|the image (shows|contains|depicts)"
    r"|extract all text"
    r"|OCR with grounding"
    r"|bounding box"
    r")",
    re.IGNORECASE,
)

# ── 전문 프롬프트 누출 탐지 패턴 ──────────────────────────────────────────────
# 전체 텍스트가 프롬프트 누출인지 판정하기 위한 키워드 목록
_FULL_TEXT_LEAKAGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"do not use", re.IGNORECASE),
    re.compile(r"do not write", re.IGNORECASE),
    re.compile(r"do not repeat", re.IGNORECASE),
    re.compile(r"extract all text", re.IGNORECASE),
    re.compile(r"bounding box", re.IGNORECASE),
    re.compile(r"OCR with grounding", re.IGNORECASE),
    re.compile(r"from the image", re.IGNORECASE),
    re.compile(r"print only", re.IGNORECASE),
    re.compile(r"output only", re.IGNORECASE),
    re.compile(r"\\#\s*\\#\s*\\#"),  # \# \# \# 반복 — 마크다운 이스케이프 반복
]

# 한글 문자 패턴 (가~힣)
_KOREAN_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[가-힣]")

# ── 마크다운 전용 구분선 패턴 ──────────────────────────────────────────────────
# 줄 전체가 구분선 기호로만 이루어진 경우 제거한다 (예: ---, ===, ***)
_SEPARATOR_LINE_PATTERN: re.Pattern[str] = re.compile(
    r"^\s*[-=*]{3,}\s*$"
)

# ── 줄 앞머리 마크다운 기호 패턴 ──────────────────────────────────────────────
# 제목(#), 강조(**), 인용(>), 목록(-), 코드블록(```) 기호를 제거한다
_LEADING_MARKDOWN_PATTERN: re.Pattern[str] = re.compile(
    r"^(\s*)(#{1,6}\s+|`{3}|>\s*|-\s+)"
)

# ── 인라인 마크다운 기호 패턴 ─────────────────────────────────────────────────
# 볼드(**text** 또는 __text__), 이탤릭(*text* 또는 _text_), 인라인 코드(`text`)
_INLINE_MARKDOWN_PATTERN: re.Pattern[str] = re.compile(
    r"(\*{1,2}|_{1,2}|`)(.*?)\1"
)

# ── 테이블 행 패턴 ────────────────────────────────────────────────────────────
# | 로 시작하거나 끝나는 마크다운 테이블 행의 파이프 기호를 제거한다
_TABLE_PIPE_PATTERN: re.Pattern[str] = re.compile(r"^\s*\||\|\s*$")

# ── HTML 테이블 태그 패턴 ─────────────────────────────────────────────────────
# <table>...</table> 에서 텍스트만 추출한다
_HTML_TAG_PATTERN: re.Pattern[str] = re.compile(r"<[^>]+>")

# ── grounding 특수 토큰 잔여 패턴 ────────────────────────────────────────────
# 모델 출력에 남은 <|ref|>, <|det|> 등의 태그를 제거한다
_GROUNDING_TAG_PATTERN: re.Pattern[str] = re.compile(
    r"<\|(?:ref|/ref|det|/det|grounding|User|Assistant)\|>:?"
)

# ── 대괄호 좌표 잔여 패턴 ─────────────────────────────────────────────────────
# [[숫자,숫자,숫자,숫자]] 형태의 좌표 잔여를 제거한다
_BRACKET_COORDS_PATTERN: re.Pattern[str] = re.compile(
    r"\[\[\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\]\]"
)

# ── 폰트 미지원 유니코드 기호 패턴 ──────────────────────────────────────────
# AppleGothic 폰트가 렌더링할 수 없는 기하학 도형, 화살표 등의 특수 기호를 제거한다
# 범위: Geometric Shapes(25A0-25FF), Dingbats(2700-27BF), Arrows(2190-21FF),
#       Misc Symbols(2600-26FF), Box Drawing(2500-257F) 등
_UNSUPPORTED_SYMBOL_PATTERN: re.Pattern[str] = re.compile(
    r"[\u2190-\u21FF\u2500-\u257F\u25A0-\u25FF\u2600-\u26FF\u2700-\u27BF]"
)

# ── HTML 테이블 셀 구분자 패턴 ────────────────────────────────────────────────
# </td> 바로 뒤에 <td 가 오는 경우 — 같은 행의 셀 경계를 탭으로 대체한다
_TD_BOUNDARY_PATTERN: re.Pattern[str] = re.compile(r"</td>\s*<td[^>]*>", re.IGNORECASE)

# 행 종료 태그 패턴 — </tr> 를 줄바꿈으로 대체한다
_TR_END_PATTERN: re.Pattern[str] = re.compile(r"</tr>", re.IGNORECASE)

# 나머지 테이블 골격 태그 패턴 — 구조 변환 후 남은 <table>, <tr>, <td> 태그를 제거한다
_TABLE_SKELETON_PATTERN: re.Pattern[str] = re.compile(
    r"</?(?:table|tr|td|tbody|thead|th)[^>]*>", re.IGNORECASE
)

# ── 연속 빈 줄 패턴 ──────────────────────────────────────────────────────────
# 2개 이상의 연속 빈 줄을 단일 빈 줄로 축약한다
_MULTI_BLANK_PATTERN: re.Pattern[str] = re.compile(r"\n{3,}")

# ── 수학 수식 영역 보호 패턴 ──────────────────────────────────────────────────
# $...$, $$...$$, \(...\), \[...\] 형태의 수식 구간을 탐지한다
# 혼동 문자 보정 적용 전에 수식 영역을 플레이스홀더로 치환하여 보정에서 제외한다
_MATH_REGION_PATTERN: re.Pattern[str] = re.compile(
    r"(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])"
)

# 수식 영역 플레이스홀더 형식 — 원본 수식 복원 시 사용한다
_MATH_PLACEHOLDER: str = "\x00MATH_{index}\x00"

# ── 도메인 사전 + 혼동 문자 보정 (지연 초기화) ────────────────────────────────
# 사전 로드 실패 시에도 파이프라인이 중단되지 않도록 선택적으로 적용한다
_domain_dict: frozenset[str] | None = None
_domain_dict_loaded: bool = False


def _get_domain_dict() -> frozenset[str]:
    """도메인 사전을 지연 초기화하여 반환한다.

    최초 호출 시 한 번만 파일을 읽고 이후 캐시된 결과를 반환한다.
    로드 실패 시 빈 frozenset을 반환하여 파이프라인을 보호한다.
    """
    global _domain_dict, _domain_dict_loaded
    if not _domain_dict_loaded:
        try:
            from backend.ocr.atoms.domain_dictionary import load_domain_dictionary
            _domain_dict = load_domain_dictionary()
        except Exception:
            # 사전 로드 실패 — 보정 비활성화로 안전 처리
            _domain_dict = frozenset()
        _domain_dict_loaded = True
    # 타입 좁히기: _domain_dict_loaded=True 이후 반드시 frozenset임
    return _domain_dict if _domain_dict is not None else frozenset()


def _extract_math_regions(text: str) -> tuple[str, dict[int, str]]:
    """텍스트에서 수학 수식 구간을 추출하고 플레이스홀더로 대체한다.

    혼동 문자 보정이 LaTeX 수식 내부를 잘못 변경하는 것을 방지하기 위해
    수식 영역을 임시 플레이스홀더로 치환하여 보정에서 제외한다.

    Args:
        text: 원본 텍스트

    Returns:
        (플레이스홀더로 치환된 텍스트, {인덱스: 원본 수식} 복원용 딕셔너리) 튜플
    """
    math_regions: dict[int, str] = {}
    index = 0

    def _replace_with_placeholder(match: re.Match[str]) -> str:
        nonlocal index
        # 원본 수식을 인덱스로 저장하고 플레이스홀더를 반환한다
        math_regions[index] = match.group(0)
        placeholder = _MATH_PLACEHOLDER.replace("{index}", str(index))
        index += 1
        return placeholder

    masked_text = _MATH_REGION_PATTERN.sub(_replace_with_placeholder, text)
    return masked_text, math_regions


def _restore_math_regions(text: str, regions: dict[int, str]) -> str:
    """플레이스홀더를 원본 수학 수식으로 복원한다.

    _extract_math_regions와 쌍으로 사용한다.
    플레이스홀더가 보정 과정에서 변형되어도 인덱스를 기반으로 복원한다.

    Args:
        text: 플레이스홀더가 포함된 텍스트
        regions: {인덱스: 원본 수식} 딕셔너리

    Returns:
        원본 수식이 복원된 텍스트
    """
    for index, original_math in regions.items():
        placeholder = _MATH_PLACEHOLDER.replace("{index}", str(index))
        # 플레이스홀더를 원본 수식으로 대체한다
        text = text.replace(placeholder, original_math)
    return text


def is_prompt_leakage(text: str) -> bool:
    """전체 텍스트가 프롬프트 누출인지 판정한다.

    누출 조건 (둘 다 충족해야 함):
    1. 프롬프트 누출 키워드가 1개 이상 존재
    2. 한글 문자가 전혀 없음 (한국어 교재에서 한글 0%는 비정상)

    한글이 포함된 텍스트는 실제 OCR 결과일 가능성이 높으므로 누출로 판정하지 않는다.
    """
    if not text or not text.strip():
        return False

    # 한글 문자가 있으면 누출이 아님
    if _KOREAN_CHAR_PATTERN.search(text):
        return False

    # 누출 키워드 매칭
    for pattern in _FULL_TEXT_LEAKAGE_PATTERNS:
        if pattern.search(text):
            return True

    return False


def _convert_html_tables(text: str) -> str:
    """HTML 테이블 마크업을 탭 구분 텍스트로 변환한다.

    _HTML_TAG_PATTERN 이 실행되기 전에 호출해야 셀 구조가 보존된다.
    변환 순서:
      1. 같은 행 내 셀 경계(</td><td>) → 탭(\t)
      2. 행 종료(</tr>)              → 줄바꿈(\n)
      3. 나머지 테이블 골격 태그      → 제거

    Examples:
        >>> _convert_html_tables("<table><tr><td>A</td><td>B</td></tr></table>")
        'A\tB'
    """
    # 같은 행의 인접 셀 경계를 탭으로 치환 — 열 구분자 확보
    text = _TD_BOUNDARY_PATTERN.sub("\t", text)
    # 행 종료를 줄바꿈으로 치환 — 행 구분자 확보
    text = _TR_END_PATTERN.sub("\n", text)
    # 나머지 테이블 골격 태그(<table>, <tr>, <td> 등) 제거
    text = _TABLE_SKELETON_PATTERN.sub("", text)
    return text


def _clean_line(line: str) -> str:
    """단일 줄에서 grounding 태그, HTML 태그, 마크다운 기호를 제거한다."""
    # grounding 특수 토큰 제거
    line = _GROUNDING_TAG_PATTERN.sub("", line)
    # 대괄호 좌표 잔여 제거
    line = _BRACKET_COORDS_PATTERN.sub("", line)
    # HTML 태그 제거 (텍스트만 보존)
    line = _HTML_TAG_PATTERN.sub("", line)
    # 줄 앞머리 마크다운 기호 제거 (들여쓰기는 보존)
    line = _LEADING_MARKDOWN_PATTERN.sub(r"\1", line)
    # 인라인 마크다운 기호 제거 (내부 텍스트만 보존)
    line = _INLINE_MARKDOWN_PATTERN.sub(r"\2", line)
    # 테이블 행의 앞뒤 파이프 기호 제거
    line = _TABLE_PIPE_PATTERN.sub("", line)
    # 폰트 미지원 유니코드 특수 기호 제거 (기하학 도형, 화살표 등)
    line = _UNSUPPORTED_SYMBOL_PATTERN.sub("", line)
    # 줄 앞뒤 공백 정리
    return line.strip()


def clean_text(raw_ocr: str) -> str:
    """OCR 원시 출력에서 프롬프트 누출 패턴과 마크다운 기호를 제거한다.

    Args:
        raw_ocr: 모델이 생성한 원시 OCR 텍스트

    Returns:
        정제된 텍스트 — 한국어/영어/숫자/기본 문장부호만 보존된다
    """
    # 환각 반복 출력 감지 및 제거 — 모든 정제 전에 먼저 수행한다
    # 모델이 동일 줄/토큰을 수만 번 반복하는 환각 출력을 절단한다
    try:
        from backend.ocr.atoms.detect_repetition import remove_repetitive_output
        raw_ocr = remove_repetitive_output(raw_ocr)
    except Exception:
        pass

    # HTML 테이블 구조를 탭 구분 텍스트로 변환 — 태그 일괄 제거 전에 수행해야 셀이 붙지 않는다
    raw_ocr = _convert_html_tables(raw_ocr)

    lines: list[str] = raw_ocr.splitlines()
    cleaned: list[str] = []

    for line in lines:
        # 프롬프트 누출 패턴으로 시작하는 줄 전체 제거
        if _LEAKAGE_LINE_PATTERN.match(line):
            continue
        # 마크다운 구분선만으로 이루어진 줄 제거
        if _SEPARATOR_LINE_PATTERN.match(line):
            continue
        # 줄 내 마크다운 기호 제거
        cleaned.append(_clean_line(line))

    result: str = "\n".join(cleaned)

    # 연속 빈 줄을 최대 1개로 축약
    result = _MULTI_BLANK_PATTERN.sub("\n\n", result)

    # 전체 앞뒤 공백 제거
    result = result.strip()

    # 최종 안전망 — 정제 후에도 전체가 프롬프트 누출이면 빈 문자열 반환
    if is_prompt_leakage(result):
        return ""

    # 수식 영역을 플레이스홀더로 보호 — 보정 과정에서 LaTeX가 손상되지 않도록 한다
    math_protected, math_regions = _extract_math_regions(result)

    # 단일 문자 혼동 보정 — 도메인 사전 기반으로 보수적으로 적용한다
    # 수식 영역은 플레이스홀더로 치환되어 있으므로 보정에서 제외된다
    try:
        from backend.ocr.atoms.correct_confusable_chars import correct_confusable_chars
        math_protected = correct_confusable_chars(math_protected, _get_domain_dict())
    except Exception:
        # 보정 실패 — 원본 텍스트를 그대로 유지
        pass

    # 자모 수준 다중 문자 혼동 보정 — 단일 자모 치환으로 교정 가능한 오인식을 처리한다
    try:
        from backend.ocr.atoms.correct_multichar_confusions import correct_multichar_confusions
        math_protected = correct_multichar_confusions(math_protected, _get_domain_dict())
    except Exception:
        # 자모 보정 실패 — 원본 텍스트를 그대로 유지
        pass

    # 수식 영역 복원 — 플레이스홀더를 원본 LaTeX로 되돌린다
    result = _restore_math_regions(math_protected, math_regions)

    # LaTeX 수식 후처리 — 미닫힌 중괄호, 첨자 오류, 불완전 명령어를 교정한다
    # 수식 영역이 복원된 후에 실행해야 수식 구조가 온전히 전달된다
    try:
        from backend.ocr.atoms.clean_latex import clean_latex
        result = clean_latex(result)
    except Exception:
        # LaTeX 교정 실패 — 원본 텍스트를 그대로 반환
        pass

    return result
