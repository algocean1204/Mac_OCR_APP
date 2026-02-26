# 혼동 문자 보정 모듈
# DeepSeek-OCR-2-8bit 모델이 8비트 양자화로 인해 유사 한글 자모를
# 체계적으로 오인식하는 문제를 도메인 사전 기반으로 보정한다.
#
# 보정 조건 (세 가지 모두 충족해야 교정 수행):
#   1. 원본 단어가 도메인 사전에 없음
#   2. 혼동 맵으로 치환 시 사전에 있는 단어가 정확히 1개 생성됨
#   3. 치환 후보가 유일해야 함 (중의성 없음)
from __future__ import annotations

import re

# ── 혼동 문자 쌍 매핑 ─────────────────────────────────────────────────────────
# 키: 모델이 잘못 출력하는 문자 (오인식 결과)
# 값: 실제로 의도된 올바른 문자 (정답)
# 근거: 8비트 양자화된 DeepSeek-OCR-2 모델의 실측 오류 패턴
CONFUSION_MAP: dict[str, str] = {
    "둔": "둡",   # "하둡" → 모델이 "하둔"으로 출력 (77% 오류율)
    "둘": "둡",   # "하둡" → 모델이 "하둘"로 출력 (ㅂ→ㄹ 종성 혼동)
    "점": "첨",   # "첨도" → 모델이 "점도"로 출력 (49% 오류율)
    "충": "층",   # "층화" → 모델이 "충화"로 출력
    "홀": "풀",   # "풀이" → 모델이 "홀이"로 출력
    "각": "콕",   # "박스콕스" → 모델이 "박스각스"로 출력
    # ── 빅데이터 분석기사 시험 PDF OCR에서 추가 관측된 오인식 패턴 ──────────────
    "백": "빅",   # "빅데이터" → 모델이 "백데이터"로 출력 (ㅣ→ㅐ 모음 혼동)
    "핵": "과",   # "결과" → 모델이 "결핵"으로 출력 (과→핵 초성+모음 혼동)
    "작": "직",   # "직무" → 모델이 "작무"로 출력 (ㅣ→ㅏ 모음 혼동)
    # 주의: "정"과 "명"은 범용 고빈도 문자이므로 오탐 가능성이 있음.
    # 도메인 사전 기반의 단어 단위 검증이 필수이며, 사전 미등재 단어에 대해서는 교정하지 않음.
    "정": "명",   # "가명" → 모델이 "가정"으로 출력 (ㅁ→ㅈ 초성 혼동)
    # 주의: "직"→"확" 역시 "직접", "직관" 등 "직"이 포함된 정상 단어가 많으므로
    # 사전 기반 단어 단위 검증 없이는 적용 불가. 사전 등재를 통해 오탐을 방지한다.
    "직": "확",   # "확인" → 모델이 "직인"으로 출력 (ㅎ→ㄱ 초성, ㅘ→ㅣ 모음 혼동)
}

# 한글 단어 경계를 기준으로 토큰을 분리하는 패턴
# 공백, 줄바꿈, 문장부호, 하이픈, 슬래시, 중간점, 수식 기호로 단어를 분리한다
_WORD_SPLIT_PATTERN: re.Pattern[str] = re.compile(
    r"([\s\.,;:!?\(\)\[\]{}<>「」『』【】\"\'·\-/=+×÷→←])"
)

# 조사/어미 목록 — 가장 긴 것부터 순서대로 배치하여 탐욕적 매칭(greedy match)을 보장한다.
# 짧은 조사가 먼저 매칭되면 더 긴 조사가 무시될 수 있으므로 순서가 중요하다.
_KOREAN_PARTICLES: tuple[str, ...] = (
    # 3자 이상 조사/어미 (긴 것 우선)
    "에서는", "으로는", "에서의", "으로의", "에서도", "으로도",
    "이라는", "이라고", "이라면", "이었다", "이라서",
    # 2자 조사/어미
    "에서", "으로", "부터", "까지", "에게", "한테", "처럼", "보다",
    "라는", "라고", "라면", "이다", "이고", "이나", "이란",
    "에는", "에도", "에의", "와의", "과의", "의한",
    # 1자 조사/어미 — 오탐 가능성이 있으므로 마지막에 배치
    "의", "를", "을", "에", "와", "과", "도", "는", "은", "이", "가",
    "로", "서", "며", "고", "나", "만", "든", "등",
)


def correct_confusable_chars(
    text: str,
    dictionary: frozenset[str],
) -> str:
    """혼동 문자를 도메인 사전 기반으로 보수적으로 보정한다.

    각 단어에 대해 CONFUSION_MAP의 문자를 한 번씩 치환해보고,
    사전 매칭이 정확히 1개인 경우에만 교정을 수행한다.
    사전이 비어 있으면 원본 텍스트를 그대로 반환한다.

    Args:
        text: OCR로 인식된 원시 텍스트
        dictionary: 도메인 용어 집합 (frozenset, O(1) 검사)

    Returns:
        보정된 텍스트 — 사전 매칭이 확실한 경우에만 수정됨
    """
    # 사전이 비어 있으면 보정 불가 — 원본 반환
    if not dictionary:
        return text

    # 공백과 구분자로 분리하되 구분자 토큰도 보존한다
    tokens = _WORD_SPLIT_PATTERN.split(text)
    corrected_tokens = [_correct_token(token, dictionary) for token in tokens]
    return "".join(corrected_tokens)


def _correct_token(token: str, dictionary: frozenset[str]) -> str:
    """단일 토큰에 대해 혼동 문자 보정을 시도한다.

    1차: 전체 단어 그대로 사전 기반 교정 시도.
    2차: 조사를 분리한 어간(stem)으로 재시도 — 조사가 붙은 복합 토큰 처리.

    Args:
        token: 분리된 단일 토큰 문자열
        dictionary: 도메인 용어 집합

    Returns:
        보정된 토큰 또는 원본 토큰
    """
    # 구분자 토큰은 보정 대상이 아님
    if not token.strip() or _is_delimiter(token):
        return token

    # 이미 사전에 있는 단어는 보정 불필요
    if token in dictionary:
        return token

    # 1차: 전체 단어로 교정 시도
    result = _find_and_apply_correction(token, dictionary)
    if result != token:
        return result

    # 2차: 조사 분리 후 어간만으로 교정 시도
    # 예: "백데이터의" → stem="백데이터", particle="의"
    stem, particle = _strip_korean_particle(token)
    if not particle:
        # 분리할 조사가 없으면 원본 유지
        return token

    # 어간이 이미 사전에 있으면 오인식이 아닌 정상 단어 — 교정 불필요
    if stem in dictionary:
        return token

    corrected_stem = _find_and_apply_correction(stem, dictionary)
    if corrected_stem != stem:
        # 교정된 어간에 원래 조사를 다시 붙여 반환
        return corrected_stem + particle

    return token


def _strip_korean_particle(word: str) -> tuple[str, str]:
    """단어 끝에서 한국어 조사/어미를 분리한다.

    _KOREAN_PARTICLES를 긴 것부터 순서대로 검사하여
    처음 매칭되는 조사를 분리한다 (탐욕적 매칭).
    분리 후 어간이 2자 미만이면 과잉 분리로 보고 분리하지 않는다.

    Args:
        word: 조사가 붙어 있을 수 있는 원본 단어

    Returns:
        (어간, 조사) 튜플.
        조사를 찾지 못하면 (word, "") 반환.
    """
    for particle in _KOREAN_PARTICLES:
        if not word.endswith(particle):
            continue
        stem = word[: len(word) - len(particle)]
        # 어간이 너무 짧으면 의미 없는 분리로 간주하여 무시
        if len(stem) < 2:
            continue
        return stem, particle

    # 매칭되는 조사 없음
    return word, ""


def _is_delimiter(token: str) -> bool:
    """토큰이 구분자(공백, 문장부호)인지 판별한다."""
    return bool(_WORD_SPLIT_PATTERN.fullmatch(token))


def _find_and_apply_correction(
    word: str,
    dictionary: frozenset[str],
) -> str:
    """단어에서 혼동 문자를 찾아 사전 기반으로 교정한다.

    CONFUSION_MAP의 각 혼동 문자를 단어 내 위치마다 치환해보고,
    사전 매칭 후보가 정확히 1개인 경우에만 교정을 적용한다.
    0개(사전 미매칭)이거나 2개 이상(중의성)인 경우 원본을 반환한다.

    Args:
        word: 사전에 없는 단어 토큰
        dictionary: 도메인 용어 집합

    Returns:
        교정된 단어 또는 원본 단어
    """
    candidates: list[str] = _generate_correction_candidates(word, dictionary)

    # 보정 조건 3: 후보가 정확히 1개여야 함 (중의성 없음)
    if len(candidates) == 1:
        return candidates[0]

    # 0개(사전 미매칭) 또는 2개 이상(중의성) — 원본 유지
    return word


def _generate_correction_candidates(
    word: str,
    dictionary: frozenset[str],
) -> list[str]:
    """단어에서 가능한 모든 혼동 문자 교정 후보를 생성한다.

    단어 내 각 위치에 대해 CONFUSION_MAP 치환을 시도하고,
    치환 결과가 사전에 있으면 후보 목록에 추가한다.
    동일 후보가 여러 경로로 생성되어도 중복 없이 반환한다.

    Args:
        word: 교정 대상 단어
        dictionary: 도메인 용어 집합

    Returns:
        사전에 존재하는 교정 후보 목록 (중복 제거)
    """
    unique_candidates: set[str] = set()

    for position, char in enumerate(word):
        # 현재 위치의 문자가 혼동 맵에 있는지 확인
        if char not in CONFUSION_MAP:
            continue

        corrected_char = CONFUSION_MAP[char]
        candidate = _substitute_char(word, position, corrected_char)

        # 보정 조건 2: 치환 결과가 사전에 있어야 함
        if candidate in dictionary:
            unique_candidates.add(candidate)

    return list(unique_candidates)


def _substitute_char(word: str, position: int, new_char: str) -> str:
    """단어의 특정 위치 문자를 새 문자로 치환한다.

    Args:
        word: 원본 단어
        position: 치환할 문자의 인덱스 (0-based)
        new_char: 치환할 새 문자

    Returns:
        해당 위치 문자가 교체된 새 문자열
    """
    return word[:position] + new_char + word[position + 1:]
