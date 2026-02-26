# LLM 후처리 출력 파서
# 텍스트 LLM의 응답에서 교정된 텍스트만 추출한다
# LLM이 지시를 무시하고 설명을 포함하는 경우를 처리한다
from __future__ import annotations

import re

# ── LLM 응답에서 교정 텍스트 추출 패턴 ─────────────────────────────────────
# 일부 LLM은 "교정된 텍스트:" 이후에 결과를 출력한다
_CORRECTED_HEADER_PATTERN: re.Pattern[str] = re.compile(
    r"^(교정된\s*텍스트|검증[·\s]*교정된\s*텍스트|corrected\s*text)\s*[:：]\s*\n?",
    re.IGNORECASE | re.MULTILINE,
)

# LLM이 사고 과정을 <think>...</think>로 감싸는 경우 (DeepSeek-R1 계열)
_THINKING_BLOCK_PATTERN: re.Pattern[str] = re.compile(
    r"<think>[\s\S]*?</think>\s*",
    re.IGNORECASE,
)

# 응답 구분선 패턴 — LLM이 --- 로 구분하는 경우
_SEPARATOR_PATTERN: re.Pattern[str] = re.compile(r"^-{3,}\s*$", re.MULTILINE)

# LLM이 추가하는 메타 설명 패턴 (교정 결과 앞뒤의 불필요한 설명)
_META_EXPLANATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(다음은|아래는|위 텍스트에서|교정\s*사항|변경\s*사항).*$", re.MULTILINE),
    re.compile(r"^(주요\s*교정|수정\s*내용|참고)[:：].*$", re.MULTILINE),
    re.compile(r"^\d+\.\s*(.*?→.*?)$", re.MULTILINE),  # "1. 둔 → 둡" 형태 설명
]


def parse_refined_output(raw_output: str, original_text: str) -> str:
    """LLM 응답에서 교정된 텍스트만 추출한다.

    LLM이 지시를 따르지 않고 설명을 추가하는 경우를 처리한다.
    교정 결과가 원본보다 지나치게 짧거나 길면 원본을 반환한다.

    Args:
        raw_output: LLM의 전체 응답 문자열
        original_text: OCR 원본 텍스트 (품질 검증용)

    Returns:
        교정된 텍스트, 또는 파싱 실패 시 원본 텍스트
    """
    if not raw_output or not raw_output.strip():
        return original_text

    cleaned = raw_output.strip()

    # 1단계: <think>...</think> 사고 블록 제거 (DeepSeek-R1 계열)
    cleaned = _THINKING_BLOCK_PATTERN.sub("", cleaned).strip()

    # 2단계: "교정된 텍스트:" 헤더가 있으면 그 이후만 추출
    header_match = _CORRECTED_HEADER_PATTERN.search(cleaned)
    if header_match:
        cleaned = cleaned[header_match.end():].strip()

    # 3단계: --- 구분선 이후의 텍스트만 추출 (구분선이 있는 경우)
    separator_parts = _SEPARATOR_PATTERN.split(cleaned)
    if len(separator_parts) >= 2:
        # 마지막 구분선 이후의 텍스트를 사용한다
        cleaned = separator_parts[-1].strip()

    # 4단계: 메타 설명 줄 제거
    for pattern in _META_EXPLANATION_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = cleaned.strip()

    # 5단계: 품질 검증 — 교정 결과가 비정상적이면 원본 반환
    if not _is_valid_refinement(cleaned, original_text):
        return original_text

    return cleaned


def _is_valid_refinement(refined: str, original: str) -> bool:
    """교정 결과의 품질을 검증한다.

    교정 결과가 비정상적으로 짧거나 길면 LLM이 오작동한 것으로 판단한다.

    Args:
        refined: 교정된 텍스트
        original: 원본 텍스트

    Returns:
        True이면 유효한 교정 결과
    """
    if not refined:
        return False

    original_len = len(original.strip())
    refined_len = len(refined.strip())

    # 원본이 비어 있으면 교정 결과도 빈 것이 정상
    if original_len == 0:
        return refined_len == 0

    # 교정 결과가 원본의 30% 미만이면 비정상 (과도한 삭제)
    if refined_len < original_len * 0.3:
        return False

    # 교정 결과가 원본의 200% 초과이면 비정상 (LLM이 설명을 추가한 것)
    if refined_len > original_len * 2.0:
        return False

    return True
