# OCR 후처리 정제 프롬프트 빌더
# 텍스트 LLM에 전달할 모델별 특화 교정 프롬프트를 생성한다
# 앙상블 파이프라인: Qwen3(일반 교정) → EXAONE(고유명사) → DeepSeek-R1(수학·코드)
# 순수 함수로 설계되어 부작용이 없다
from __future__ import annotations


# ── 1차 교정 프롬프트 (Qwen3용) ────────────────────────────────────────────
# 목적: OCR 인식 오류를 한국어·영어 문맥에서 교정한다
# 지시: 원본 구조(줄바꿈, 공백)를 보존하면서 오류만 수정한다
_KOREAN_REFINE_TEMPLATE: str = (
    "다음은 문서에서 OCR로 추출한 텍스트입니다.\n"
    "OCR 인식 오류를 문맥에 맞게 교정해 주세요.\n\n"
    "규칙:\n"
    "1. 한글 자모가 유사하여 오인식된 글자를 문맥에 맞는 올바른 단어로 교정하세요\n"
    "   예시: '빛데이터'→'빅데이터', '폴기'→'필기', '시대에뉴'→'시대에듀'\n"
    "   예시: '더이터'→'데이터', '곡내기'→'끝내기', '학심이론'→'핵심이론'\n"
    "2. 영어 단어의 오인식도 교정하세요 (예: 'BIG OATA'→'BIG DATA')\n"
    "3. 줄바꿈과 공백 구조를 그대로 유지하세요\n"
    "4. 원본에 없는 내용을 추가하거나 삭제하지 마세요\n"
    "5. 설명 없이 교정된 텍스트만 출력하세요\n\n"
    "OCR 텍스트:\n"
    "---\n"
    "{text}\n"
    "---\n\n"
    "교정된 텍스트:\n"
)

# ── 2차 고유명사·문맥 검증 프롬프트 (EXAONE용) ─────────────────────────────
# 목적: 한국어 고유명사, 기관명, 인명, 전문 용어의 정확성을 검증한다
# EXAONE은 한국어 네이티브 모델로 고유명사 인식에 강점이 있다
_PROPER_NOUN_TEMPLATE: str = (
    "다음은 OCR로 추출한 뒤 1차 교정을 거친 한국어 텍스트입니다.\n"
    "고유명사, 기관명, 인명, 전문 용어의 정확성을 검증하고 교정해 주세요.\n\n"
    "검증 규칙:\n"
    "1. 기관명을 정확히 교정하세요\n"
    "   예시: '한국네이터산업진황원'→'한국데이터산업진흥원'\n"
    "   예시: '시대에든'→'시대에듀', '시대에 듣기'→'시대에듀'\n"
    "2. 인명의 한글 철자를 문맥에 맞게 교정하세요\n"
    "   예시: '정화신'→'장희선', '장혁수'→'장희수', '운송일'→'윤승일'\n"
    "3. 전문 용어·자격증명을 정확히 교정하세요\n"
    "   예시: '빅데이터 분석기사', '정보처리기사', '머신러닝', '딥러닝'\n"
    "4. 한국어 조사·어미의 자연스러움을 확인하세요\n"
    "5. 줄바꿈과 공백 구조를 그대로 유지하세요\n"
    "6. 원본에 없는 내용을 추가하거나 삭제하지 마세요\n"
    "7. 설명 없이 교정된 텍스트만 출력하세요\n\n"
    "OCR 텍스트:\n"
    "---\n"
    "{text}\n"
    "---\n\n"
    "교정된 텍스트:\n"
)

# ── 3차 수학·코드·표 검증 프롬프트 (DeepSeek-R1용) ──────────────────────────
# 목적: 수식, 코드, 표 구조, 기술 용어의 논리적 정합성을 검증한다
# DeepSeek-R1은 추론·논리 특화 모델로 구조적 검증에 강점이 있다
_REASONING_VERIFY_TEMPLATE: str = (
    "다음은 OCR로 추출한 뒤 교정을 거친 텍스트입니다.\n"
    "수학 수식, 프로그래밍 코드, 표 구조, 기술 용어의 정확성을 검증하고 교정해 주세요.\n\n"
    "검증 규칙:\n"
    "1. LaTeX 수식의 문법 오류를 교정하세요 (미닫힌 중괄호, 잘못된 첨자 등)\n"
    "2. 프로그래밍 코드의 문법 오류를 교정하세요 (함수명, 키워드, 연산자 등)\n"
    "3. 숫자와 통계 값의 논리적 일관성을 확인하세요\n"
    "4. 표 구조의 행/열 정렬을 검증하세요\n"
    "5. 기술 용어(영어)의 정확한 철자를 확인하세요\n"
    "   예시: 'Machne Learnng'→'Machine Learning'\n"
    "6. 줄바꿈과 공백 구조를 그대로 유지하세요\n"
    "7. 원본에 없는 내용을 추가하거나 삭제하지 마세요\n"
    "8. 설명 없이 교정된 텍스트만 출력하세요\n\n"
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
