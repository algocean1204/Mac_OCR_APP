# OCR 후처리 정제 프롬프트 빌더
# 텍스트 LLM에 전달할 한국어 교정 및 추론 검증 프롬프트를 생성한다
# 순수 함수로 설계되어 부작용이 없다
from __future__ import annotations


# ── 한국어 교정 프롬프트 템플릿 ─────────────────────────────────────────────
# 목적: OCR 인식 오류를 한국어 문맥에서 교정한다
# 지시: 원본 구조(줄바꿈, 공백)를 보존하면서 오류만 수정한다
# few-shot 예시: 모음/종성 혼동 패턴을 모델에 명시적으로 제시하여 교정 정확도를 높인다
_KOREAN_REFINE_TEMPLATE: str = (
    "이 문서는 IT/통계 분야 한국어 교재입니다.\n"
    "다음은 스캔된 한국어 문서에서 OCR로 추출한 텍스트입니다.\n"
    "OCR 인식 오류를 찾아 교정해 주세요.\n\n"
    "교정 규칙:\n"
    "1. 명확한 오인식만 수정하세요 (유사 한글 자모 혼동, 누락 글자, 깨진 문자)\n"
    "2. 원래 텍스트의 줄바꿈과 공백 구조를 그대로 유지하세요\n"
    "3. 전문 용어는 문맥에 맞게 교정하세요\n"
    "4. 확실하지 않은 부분은 원본을 유지하세요\n"
    "5. 설명이나 주석을 추가하지 마세요 — 교정된 텍스트만 출력하세요\n\n"
    "교정 예시:\n"
    "- 백데이터 → 빅데이터 (모음 혼동: ㅐ→ㅣ)\n"
    "- 본포 → 분포 (모음 혼동: ㅗ→ㅜ)\n"
    "- 점답 → 정답 (모음 혼동: ㅓ→ㅏ)\n"
    "- 하둔 → 하둡 (종성 혼동: ㄴ→ㅂ)\n"
    "- 충화 → 층화 (종성 혼동: ㅇ→없음)\n\n"
    "OCR 텍스트:\n"
    "---\n"
    "{text}\n"
    "---\n\n"
    "교정된 텍스트:\n"
)

# ── 추론 검증 프롬프트 템플릿 ──────────────────────────────────────────────
# 목적: 수식, 표 구조, 기술 용어의 논리적 정합성을 검증한다
# 지시: 사고 과정을 거쳐 오류를 찾고 교정한다
_REASONING_VERIFY_TEMPLATE: str = (
    "다음은 한국어 교재에서 OCR로 추출한 텍스트입니다.\n"
    "수학 수식, 표 구조, 기술 용어의 정확성을 검증하고 교정해 주세요.\n\n"
    "검증 규칙:\n"
    "1. LaTeX 수식의 문법 오류를 교정하세요 (미닫힌 중괄호, 잘못된 첨자 등)\n"
    "2. 숫자와 통계 값의 논리적 일관성을 확인하세요\n"
    "3. 기술 용어의 정확한 철자를 확인하세요\n"
    "4. 표 구조의 행/열 정렬을 검증하세요\n"
    "5. 설명 없이 교정된 텍스트만 출력하세요\n\n"
    "OCR 텍스트:\n"
    "---\n"
    "{text}\n"
    "---\n\n"
    "검증·교정된 텍스트:\n"
)

# ── 후처리 프롬프트의 최대 입력 길이 (문자 수) ─────────────────────────────
# 너무 긴 텍스트는 LLM의 품질이 저하되므로 청크 단위로 분할한다
MAX_REFINE_INPUT_CHARS: int = 2000


def build_korean_refine_prompt(text: str) -> str:
    """한국어 OCR 교정 프롬프트를 생성한다.

    Args:
        text: OCR로 추출된 원시 텍스트

    Returns:
        LLM에 전달할 완성된 프롬프트 문자열
    """
    # 입력이 최대 길이를 초과하면 앞부분만 사용한다
    truncated = text[:MAX_REFINE_INPUT_CHARS] if len(text) > MAX_REFINE_INPUT_CHARS else text
    return _KOREAN_REFINE_TEMPLATE.format(text=truncated)


def build_reasoning_verify_prompt(text: str) -> str:
    """추론 기반 검증 프롬프트를 생성한다.

    Args:
        text: OCR로 추출된 원시 텍스트

    Returns:
        LLM에 전달할 완성된 프롬프트 문자열
    """
    truncated = text[:MAX_REFINE_INPUT_CHARS] if len(text) > MAX_REFINE_INPUT_CHARS else text
    return _REASONING_VERIFY_TEMPLATE.format(text=truncated)


def should_refine(text: str, min_length: int = 10) -> bool:
    """텍스트가 후처리 대상인지 판정한다.

    너무 짧거나 빈 텍스트는 후처리할 필요가 없다.
    공백만으로 구성된 텍스트도 제외한다.

    Args:
        text: 판정 대상 텍스트
        min_length: 최소 유효 문자 수 (기본값 10)

    Returns:
        True이면 후처리 대상
    """
    if not text or not text.strip():
        return False
    return len(text.strip()) >= min_length
