# LaTeX 후처리 정제 모듈
# DeepSeek-OCR-2 모델이 출력한 수식 문자열의 일반적인 오류를 교정한다
# 모든 함수는 순수 함수(Pure Function)로 설계되어 부작용이 없다
from __future__ import annotations

import re

# 수식 환경 구분자 패턴 — $...$, $$...$$, \\(...\\), \\[...\\] 를 탐지한다
_INLINE_MATH_PATTERN: re.Pattern[str] = re.compile(
    r"(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])"
)

# 닫히지 않은 중괄호를 탐지하기 위한 이스케이프 제거 패턴
# \\{ 와 \\} 는 이스케이프된 리터럴이므로 카운트에서 제외한다
_ESCAPED_BRACE_PATTERN: re.Pattern[str] = re.compile(r"\\[{}]")

# multi-char 첨자 탐지 — _10, _ab 같이 중괄호 없이 두 자 이상 이어진 첨자를 찾는다
_SUBSCRIPT_MULTI_CHAR: re.Pattern[str] = re.compile(
    r"(?<![\\])_([A-Za-z0-9]{2,})(?![A-Za-z0-9{])"
)
_SUPERSCRIPT_MULTI_CHAR: re.Pattern[str] = re.compile(
    r"(?<![\\])\^([A-Za-z0-9]{2,})(?![A-Za-z0-9{])"
)

# 식 끝에 단독으로 남겨진 _ 또는 ^ 를 탐지한다
_LONELY_SUBSCRIPT: re.Pattern[str] = re.compile(r"[_^]\s*$")

# \\frac 뒤에 중괄호 인수가 없는 패턴을 탐지한다
_FRAC_NO_ARGS: re.Pattern[str] = re.compile(r"\\frac(?!\s*\{)")

# \\sqrt 뒤에 중괄호가 없는 패턴 — \\sqrt 다음에 바로 숫자/문자가 오는 경우
_SQRT_NO_BRACE: re.Pattern[str] = re.compile(r"\\sqrt(?!\s*[\[{])([A-Za-z0-9])")

# 연산자 주변의 과도한 공백을 정규화하기 위한 패턴
_MULTI_SPACE: re.Pattern[str] = re.compile(r"[ \t]{2,}")

# 이중 역슬래시 LaTeX 명령어 패턴 — \\\\frac, \\\\sum 처럼 잘못 이중화된 패턴을 감지한다
_DOUBLE_BACKSLASH_CMD: re.Pattern[str] = re.compile(
    r"\\\\(frac|sum|int|prod|sqrt|alpha|beta|gamma|delta|theta"
    r"|pi|sigma|lambda|mu|infty|lim|log|sin|cos|tan)"
)

# 이중 역슬래시 교정에 사용할 단일 역슬래시 상수
_SINGLE_BACKSLASH: str = chr(92)

# ── 누락된 첨자 마커 탐지 패턴 ────────────────────────────────────────────────
# 수식 명령어 뒤에 _ 없이 바로 {가 오는 경우를 탐지한다
# 예: \sum{i=1} → \sum_{i=1}, \prod{k=1} → \prod_{k=1}
_MATH_CMD_MISSING_SUB: re.Pattern[str] = re.compile(
    r"\\(sum|prod|int|lim|min|max|inf|sup|bigcup|bigcap|bigoplus)\{"
)

# 단일 대문자/소문자 변수 뒤에 _ 없이 {가 오는 경우를 탐지한다
# 예: A{i} → A_{i}, x{n} → x_{n}
# 단, 수식 명령어(\alpha{} 등)나 이미 _ 가 앞에 있는 경우는 제외한다
_VAR_MISSING_SUB: re.Pattern[str] = re.compile(
    r"(?<!\\)(?<!_)(?<!^)([A-Za-z])\{([A-Za-z0-9,\s]+)\}"
)


def clean_latex(text: str) -> str:
    """LaTeX 문자열에서 일반적인 오류를 교정하는 메인 진입점.

    아래 순서로 교정을 순차 적용한다:
    1) 잘못된 이중 역슬래시 명령어를 단일로 교정
    2) 누락된 첨자 마커(_) 복구 — \\sum{}, 단순 변수{}
    3) 단독 첨자 기호 및 multi-char 첨자에 중괄호 추가
    4) frac, sqrt 등 불완전한 명령어 교정
    5) 닫히지 않은 중괄호 보충
    6) 수학 수식 내 공백 정규화

    보수적으로 교정하며, 명확한 오류만 수정한다.

    Args:
        text: 모델이 출력한 원시 LaTeX 포함 문자열

    Returns:
        교정이 적용된 문자열
    """
    if not text:
        return text

    text = _fix_common_latex_errors(text)
    text = _fix_missing_subscripts(text)
    text = _fix_subscript_superscript(text)
    text = _close_unclosed_braces(text)
    text = _normalize_whitespace_in_math(text)

    return text


def _fix_missing_subscripts(text: str) -> str:
    r"""수식 명령어와 단순 변수 뒤에 누락된 첨자 마커(_)를 복구한다.

    두 가지 경우를 처리한다:
    1) \sum{i=1} → \sum_{i=1} (수식 명령어 뒤 _ 누락)
    2) A{i} → A_{i} (단일 변수 뒤 _ 누락)

    수식 환경 내부에만 적용한다.

    Args:
        text: 교정 대상 문자열

    Returns:
        첨자 마커가 복구된 문자열
    """
    return _apply_to_math_regions(text, _fix_missing_subscripts_in_expr)


def _fix_missing_subscripts_in_expr(expr: str) -> str:
    r"""단일 수식 표현식에서 누락된 _ 마커를 복구한다.

    Args:
        expr: 수식 환경 내부 문자열 (구분자 제외)

    Returns:
        _ 마커가 복구된 수식 문자열
    """
    # 1) 수식 명령어(\sum, \prod 등) 뒤 _ 누락 복구
    # \sum{i=1} → \sum_{i=1}
    expr = _MATH_CMD_MISSING_SUB.sub(r"\\\1_{", expr)

    # 2) 단일 변수 뒤 _ 누락 복구
    # A{i} → A_{i} — 단, 이미 _ 또는 ^ 뒤에 오는 경우는 제외한다
    expr = _VAR_MISSING_SUB.sub(r"\1_{\2}", expr)

    return expr


def _close_unclosed_braces(text: str) -> str:
    r"""닫히지 않은 중괄호를 문자열 끝에 추가하여 균형을 맞춘다.

    이스케이프된 \{ 와 \} 는 리터럴 문자이므로 카운트에서 제외한다.
    열린 중괄호 수가 닫힌 중괄호 수보다 많으면 그 차이만큼 } 를 추가한다.

    Args:
        text: 교정 대상 문자열

    Returns:
        중괄호가 균형을 이루는 문자열
    """
    # 이스케이프된 \{ 와 \} 를 임시 플레이스홀더로 치환하여 카운트에서 제외한다
    sanitized = _ESCAPED_BRACE_PATTERN.sub("__ESC_BRACE__", text)

    open_count = sanitized.count("{")
    close_count = sanitized.count("}")
    deficit = open_count - close_count

    if deficit <= 0:
        # 이미 균형이 맞거나 닫는 중괄호가 더 많은 경우 — 수정하지 않는다
        return text

    # 최대 10개까지만 추가한다 — 너무 많은 추가는 오탐일 가능성이 높다
    safe_deficit = min(deficit, 10)
    return text + "}" * safe_deficit


def _fix_subscript_superscript(text: str) -> str:
    """첨자(subscript/superscript) 관련 일반적인 오류를 교정한다.

    두 가지 경우를 처리한다:
    1) 식 끝에 단독으로 남겨진 _ 또는 ^ 를 제거한다
    2) 중괄호 없이 두 자 이상 이어진 첨자에 중괄호를 추가한다
       예: x_10 -> x_{10}, E^mc -> E^{mc}

    Args:
        text: 교정 대상 문자열

    Returns:
        첨자 오류가 교정된 문자열
    """
    # 수식 환경 내부에만 적용하기 위해 수식 구간을 분리하여 처리한다
    result = _apply_to_math_regions(text, _fix_subscript_superscript_in_expr)
    return result


def _fix_subscript_superscript_in_expr(expr: str) -> str:
    """단일 수식 표현식 내의 첨자 오류를 교정한다.

    Args:
        expr: 수식 환경 내부 문자열 (구분자 제외)

    Returns:
        첨자 오류가 교정된 수식 문자열
    """
    # 1) 식 끝에 단독으로 남겨진 _ 또는 ^ 를 제거한다
    expr = _LONELY_SUBSCRIPT.sub("", expr)

    # 2) 중괄호 없이 두 자 이상인 subscript에 중괄호를 추가한다
    expr = _SUBSCRIPT_MULTI_CHAR.sub(r"_{\1}", expr)

    # 3) 중괄호 없이 두 자 이상인 superscript에 중괄호를 추가한다
    expr = _SUPERSCRIPT_MULTI_CHAR.sub(r"^{\1}", expr)

    return expr


def _fix_common_latex_errors(text: str) -> str:
    r"""자주 발생하는 LaTeX 명령어 오류를 교정한다.

    처리하는 오류 유형:
    - \\frac, \\sum 등 잘못 이중화된 역슬래시 명령어를 단일로 교정
    - \frac 뒤에 중괄호 인수가 없으면 빈 인수 {}{} 를 추가한다
    - \sqrt 뒤에 중괄호 없이 바로 피연산자가 오면 중괄호를 추가한다

    Args:
        text: 교정 대상 문자열

    Returns:
        공통 LaTeX 오류가 교정된 문자열
    """
    # 이중 역슬래시 명령어를 단일로 교정한다
    # 예: \\frac (두 역슬래시) → \frac (한 역슬래시)
    # lambda 치환으로 백레퍼런스 해석 문제를 회피한다
    text = _DOUBLE_BACKSLASH_CMD.sub(
        lambda m: _SINGLE_BACKSLASH + m.group(1), text
    )

    # \frac 뒤에 인수가 없으면 빈 중괄호 쌍을 추가한다
    # 단, 이미 중괄호가 있는 경우는 건드리지 않는다
    text = _FRAC_NO_ARGS.sub(r"\\frac{}{}", text)

    # \sqrt 뒤에 바로 피연산자가 오는 경우 중괄호로 감싼다
    # 예: \sqrt2 → \sqrt{2}
    text = _SQRT_NO_BRACE.sub(r"\\sqrt{\1}", text)

    return text


def _normalize_whitespace_in_math(text: str) -> str:
    r"""수학 수식 내의 과도한 공백을 단일 공백으로 정규화한다.

    수식 환경 내부의 연속된 공백/탭 문자를 하나의 공백으로 축소하여
    렌더링 품질과 파싱 안정성을 높인다.
    수식 밖의 일반 텍스트는 그대로 유지한다.

    지원 수식 환경: $...$, $$...$$, \(...\), \[...\]

    Args:
        text: 정규화 대상 문자열

    Returns:
        수식 내 공백이 정규화된 문자열
    """
    return _apply_to_math_regions(text, _normalize_spaces_in_expr)


def _normalize_spaces_in_expr(expr: str) -> str:
    """단일 수식 표현식 내의 연속 공백을 단일 공백으로 축소한다.

    Args:
        expr: 수식 환경 내부 문자열 (구분자 제외)

    Returns:
        공백이 정규화된 수식 문자열
    """
    return _MULTI_SPACE.sub(" ", expr).strip()


def _apply_to_math_regions(text: str, transform: object) -> str:
    r"""문자열에서 수식 환경 구간을 추출하고 transform 함수를 적용한다.

    $...$, $$...$$, \(...\), \[...\] 구간만 선택적으로 변환하며
    일반 텍스트 구간은 그대로 유지한다.

    수식 환경 구분자가 없는 문자열은 전체를 수식 표현식으로 간주하고
    변환을 적용한다 (grounding 파서가 수식 구간만 전달하는 경우 대비).

    Args:
        text: 처리 대상 문자열
        transform: 수식 내부 문자열을 받아 교정된 문자열을 반환하는 callable

    Returns:
        수식 구간에만 transform이 적용된 문자열
    """
    # 수식 환경 구분자가 하나도 없으면 전체를 수식으로 간주한다
    if not _INLINE_MATH_PATTERN.search(text):
        return transform(text)  # type: ignore[operator]

    parts: list[str] = []
    last_end: int = 0

    for match in _INLINE_MATH_PATTERN.finditer(text):
        start, end = match.start(), match.end()

        # 수식 앞 일반 텍스트는 그대로 보존한다
        parts.append(text[last_end:start])

        # 수식 구분자와 내부 표현식을 분리하여 내부에만 변환을 적용한다
        math_block = match.group(0)
        transformed = _transform_math_block(math_block, transform)  # type: ignore[arg-type]
        parts.append(transformed)

        last_end = end

    # 마지막 수식 이후의 일반 텍스트를 추가한다
    parts.append(text[last_end:])

    return "".join(parts)


def _transform_math_block(math_block: str, transform: object) -> str:
    r"""수식 블록에서 구분자를 유지하면서 내부 표현식에만 변환을 적용한다.

    지원하는 구분자 형식:
    - $...$    인라인 수식
    - $$...$$  디스플레이 수식
    - \(...\)  LaTeX 인라인 수식
    - \[...\]  LaTeX 디스플레이 수식

    Args:
        math_block: 구분자를 포함한 수식 블록 문자열
        transform: 수식 내부에 적용할 callable

    Returns:
        구분자는 유지되고 내부만 변환된 수식 블록 문자열
    """
    # $$ ... $$ 디스플레이 수식
    if math_block.startswith("$$") and math_block.endswith("$$"):
        inner = math_block[2:-2]
        return "$$" + transform(inner) + "$$"  # type: ignore[operator]

    # $ ... $ 인라인 수식
    if math_block.startswith("$") and math_block.endswith("$"):
        inner = math_block[1:-1]
        return "$" + transform(inner) + "$"  # type: ignore[operator]

    # \[ ... \] LaTeX 디스플레이 수식
    if math_block.startswith(r"\[") and math_block.endswith(r"\]"):
        inner = math_block[2:-2]
        return r"\[" + transform(inner) + r"\]"  # type: ignore[operator]

    # \( ... \) LaTeX 인라인 수식
    if math_block.startswith(r"\(") and math_block.endswith(r"\)"):
        inner = math_block[2:-2]
        return r"\(" + transform(inner) + r"\)"  # type: ignore[operator]

    # 알 수 없는 형식 — 변환 없이 원문을 반환한다
    return math_block
