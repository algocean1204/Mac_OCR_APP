# OCR 후처리 정제 프롬프트 빌더
# 텍스트 LLM에 전달할 모델별 특화 교정 프롬프트를 생성한다
# 앙상블 파이프라인: Qwen3(일반 교정) → EXAONE(고유명사) → DeepSeek-R1(수학·코드)
# 순수 함수로 설계되어 부작용이 없다
#
# 프롬프트 압축: 핵심 지시만 남겨 토큰 수를 줄인다 (300→80 토큰)
# 매 청크마다 반복되므로 프롬프트 길이가 총 처리 시간에 누적 영향을 준다
from __future__ import annotations

import re


# ── 1차 교정 프롬프트 (Qwen3용) ────────────────────────────────────────────
# 목적: OCR 인식 오류를 한국어·영어 문맥에서 교정한다
_KOREAN_REFINE_TEMPLATE: str = (
    "OCR 텍스트를 교정하세요. 오인식 글자만 수정, "
    "줄바꿈·공백 유지, 내용 추가/삭제 금지, 교정 텍스트만 출력.\n\n"
    "---\n{text}\n---\n\n교정된 텍스트:\n"
)

# ── 2차 고유명사·문맥 검증 프롬프트 (EXAONE용) ─────────────────────────────
# 목적: 한국어 고유명사, 기관명, 인명, 전문 용어의 정확성을 검증한다
_PROPER_NOUN_TEMPLATE: str = (
    "고유명사·기관명·인명·전문용어의 정확성을 검증 교정하세요. "
    "줄바꿈·공백 유지, 내용 추가/삭제 금지, 교정 텍스트만 출력.\n\n"
    "---\n{text}\n---\n\n교정된 텍스트:\n"
)

# ── 3차 수학·코드·표 검증 프롬프트 (DeepSeek-R1용) ──────────────────────────
# 목적: 수식, 코드, 표 구조, 기술 용어의 논리적 정합성을 검증한다
_REASONING_VERIFY_TEMPLATE: str = (
    "수학 수식·코드·표 구조·기술 용어의 정확성을 검증 교정하세요. "
    "줄바꿈·공백 유지, 내용 추가/삭제 금지, 교정 텍스트만 출력.\n\n"
    "---\n{text}\n---\n\n검증·교정된 텍스트:\n"
)

# ── 후처리 프롬프트의 최대 입력 길이 (문자 수) ─────────────────────────────
# 너무 긴 텍스트는 LLM의 품질이 저하되므로 청크 단위로 분할한다
MAX_REFINE_INPUT_CHARS: int = 2000

# ── should_refine 스킵 패턴 ─────────────────────────────────────────────
# 페이지 번호, 구분선 등 LLM 교정이 불필요한 패턴을 사전 필터링한다
_SKIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[\s\-–—]*\d+[\s\-–—]*$"),   # 페이지 번호 (예: - 42 -)
    re.compile(r"^[=\-_─━*]{3,}\s*$"),          # 구분선
]


def build_korean_refine_prompt(text: str) -> str:
    """1차 한국어·영어 OCR 교정 프롬프트를 생성한다 (Qwen3용).

    Args:
        text: OCR로 추출된 원시 텍스트

    Returns:
        LLM에 전달할 완성된 프롬프트 문자열
    """
    truncated = text[:MAX_REFINE_INPUT_CHARS] if len(text) > MAX_REFINE_INPUT_CHARS else text
    return _KOREAN_REFINE_TEMPLATE.format(text=truncated)


def build_proper_noun_prompt(text: str) -> str:
    """2차 고유명사·문맥 검증 프롬프트를 생성한다 (EXAONE용).

    Args:
        text: 1차 교정된 텍스트

    Returns:
        LLM에 전달할 완성된 프롬프트 문자열
    """
    truncated = text[:MAX_REFINE_INPUT_CHARS] if len(text) > MAX_REFINE_INPUT_CHARS else text
    return _PROPER_NOUN_TEMPLATE.format(text=truncated)


def build_reasoning_verify_prompt(text: str) -> str:
    """3차 수학·코드·표 검증 프롬프트를 생성한다 (DeepSeek-R1용).

    Args:
        text: 교정된 텍스트

    Returns:
        LLM에 전달할 완성된 프롬프트 문자열
    """
    truncated = text[:MAX_REFINE_INPUT_CHARS] if len(text) > MAX_REFINE_INPUT_CHARS else text
    return _REASONING_VERIFY_TEMPLATE.format(text=truncated)


def should_refine(text: str, min_length: int = 50) -> bool:
    """텍스트가 후처리 대상인지 판정한다.

    짧은 텍스트, 페이지 번호, 구분선 등은 LLM 교정 대상에서 제외한다.
    min_length=50으로 상향하여 헤더·각주 등 불필요한 LLM 호출을 방지한다.

    Args:
        text: 판정 대상 텍스트
        min_length: 최소 유효 문자 수 (기본값 50)

    Returns:
        True이면 후처리 대상
    """
    stripped = text.strip() if text else ""
    if not stripped or len(stripped) < min_length:
        return False
    for pat in _SKIP_PATTERNS:
        if pat.match(stripped):
            return False
    return True
