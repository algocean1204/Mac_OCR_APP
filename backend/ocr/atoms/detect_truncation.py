# 토큰 한도 초과로 인한 출력 잘림(truncation) 감지 모듈
# 모델 출력이 max_tokens 한도에 도달했는지 여러 휴리스틱으로 판별한다
from __future__ import annotations

import re

# 잘림 판단에 사용할 문장 종결 문자 집합 (한국어 및 영어 포함)
# 한국어 종결어미: 다(평서), 요(경어), 음/함(명사화), 됨/임(상태),
# 등(열거), 것(의존), 수(가능), )(괄호 닫기), ](대괄호 닫기),
# 숫자(목록 번호), 원문자(①~⑨)
_SENTENCE_TERMINATORS: frozenset[str] = frozenset(
    ".?!다요음함됨임것수등"
    "0123456789"
    "①②③④⑤⑥⑦⑧⑨⑩"
    ")]\""
)

# 미완성 grounding 태그 패턴 — 열렸지만 닫히지 않은 태그를 탐지한다
_INCOMPLETE_TAG_PATTERN: re.Pattern[str] = re.compile(
    r"(<\|ref\|>[^<]*$)|(<\|det\|>[^<]*$)"
)

# 한국어 문자는 평균 약 2~3 바이트/토큰이므로, 이 비율을 초과하면 한도에 근접한 것으로 판정
_KOREAN_CHARS_PER_TOKEN: float = 2.5


def detect_truncation(raw_output: str, max_tokens: int) -> bool:
    """grounding 출력이 토큰 한도로 인해 잘렸는지 감지한다.

    판별 기준:
    1) 미완성 grounding 태그로 출력이 끊김 → 즉시 잘림 확정
    2) 문자 수 기반 휴리스틱 — 한국어 환산 토큰 추정량이 한도를 초과
    3) 출력 길이가 한도의 60% 이상이면서 문장 종결 문자로 끝나지 않음
       (짧은 출력에서 목록/수식 등이 문장 종결 없이 끝나는 정상 경우를 제외하기 위해
        길이 조건을 함께 검사한다)

    Args:
        raw_output: 모델의 원시 grounding 출력 문자열
        max_tokens: 모델에 설정된 최대 토큰 수

    Returns:
        출력이 잘린 것으로 판단되면 True, 그렇지 않으면 False
    """
    if not raw_output:
        return False

    # 기준 1: 미완성 태그 — 가장 확실한 잘림 신호
    if _has_incomplete_tag(raw_output):
        return True

    # 기준 2: 문자 수 기반 토큰 한도 초과
    if _exceeds_char_heuristic(raw_output, max_tokens):
        return True

    # 기준 3: 출력이 충분히 길면서 문장 종결 없이 끊김
    # — 짧은 출력(목록 번호, 수식, 표 셀 등)은 문장 종결 없이 끝나는 것이 정상이므로
    #   길이 조건을 결합하여 오탐을 방지한다
    char_threshold = max_tokens * _KOREAN_CHARS_PER_TOKEN
    is_long_enough = len(raw_output) > char_threshold * 0.6
    if is_long_enough and _ends_without_terminator(raw_output):
        return True

    return False


def _has_incomplete_tag(raw_output: str) -> bool:
    """출력이 닫히지 않은 grounding 태그로 끝나는지 확인한다.

    <|ref|> 또는 <|det|> 태그가 열렸으나 대응하는 닫기 태그 없이
    출력이 종료된 경우를 탐지한다.
    """
    stripped = raw_output.rstrip()
    return bool(_INCOMPLETE_TAG_PATTERN.search(stripped))


def _ends_without_terminator(raw_output: str) -> bool:
    """마지막 완성 블록의 텍스트가 문장 종결 문자로 끝나지 않는지 확인한다.

    완성 블록이 3개 이하인 짧은 페이지에서는 오탐을 방지하기 위해 검사를 건너뛴다.
    """
    # 완성된 </det> 닫기 태그 이후의 텍스트(블록 본문)를 추출한다
    parts = raw_output.split("<|/det|>")

    # 마지막 split 조각은 미완성일 수 있으므로, 완성된 블록 수를 센다
    completed_blocks = len(parts) - 1
    if completed_blocks <= 3:
        # 짧은 페이지는 오탐 가능성이 높으므로 검사를 생략한다
        return False

    # 마지막으로 완성된 블록 이후 텍스트를 추출한다
    last_block_text = parts[-1].strip()
    if not last_block_text:
        # 텍스트가 없으면 판정 불가 — 잘림 아님으로 처리한다
        return False

    return last_block_text[-1] not in _SENTENCE_TERMINATORS


def _exceeds_char_heuristic(raw_output: str, max_tokens: int) -> bool:
    """문자 수 기반으로 토큰 한도에 도달했는지 추정한다.

    한국어는 평균 2~3 문자/토큰이므로, 출력 문자 수가
    max_tokens * 2.5를 초과하면 한도에 근접한 것으로 판정한다.
    """
    char_threshold = max_tokens * _KOREAN_CHARS_PER_TOKEN
    return len(raw_output) > char_threshold
