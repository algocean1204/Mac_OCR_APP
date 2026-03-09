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
# DeepSeek-OCR 및 GLM-OCR 모델의 실측 오류 패턴을 반영한다.
CONFUSION_MAP: dict[str, str] = {
    # ── DeepSeek-OCR 패턴 ────────────────────────────────────────────────────
    "둔": "둡",   # "하둡" → "하둔" (종성 ㅂ→ㄴ)
    "둘": "둡",   # "하둡" → "하둘" (종성 ㅂ→ㄹ)
    "점": "첨",   # "첨도" → "점도" (초성 ㅊ→ㅈ)
    "충": "층",   # "층화" → "충화" (종성 혼동)
    "홀": "풀",   # "풀이" → "홀이" (초성 ㅍ→ㅎ)
    "각": "콕",   # "박스콕스" → "박스각스"
    "백": "빅",   # "빅데이터" → "백데이터" (모음 ㅣ→ㅐ)
    "핵": "과",   # "결과" → "결핵"
    "작": "직",   # "직무" → "작무" (모음 ㅣ→ㅏ)
    "정": "명",   # "가명" → "가정" (초성 ㅁ→ㅈ)
    "직": "확",   # "확인" → "직인" (초성 ㅎ→ㄱ, 모음 ㅘ→ㅣ)
    # ── GLM-OCR 패턴 ─────────────────────────────────────────────────────────
    # GLM-OCR은 한국어 자모를 형태적으로 유사한 글자로 혼동한다.
    # 초성+중성이 동시에 바뀌는 경우도 있어 직접 문자 매핑이 필요하다.
    "빵": "빅",   # "빅데이터" → "빵데이터" (초성 ㅂ→ㅃ, 모음 ㅣ→ㅏ)
    "빛": "빅",   # "빅데이터" → "빛데이터" (종성 ㄱ→ㅅ)
    # ── GLM-OCR 다중 자모 혼동 (2개 자모 동시 변경) ────────────────────────────
    # 단일 자모 치환으로 교정 불가한 패턴 — 직접 문자 매핑이 필요하다
    "맥": "망",   # "전망" → "전맥" (중성 ㅏ→ㅐ + 종성 ㅇ→ㄱ)
    "결": "검",   # "검토" → "결토" (중성 ㅓ→ㅕ + 종성 ㅁ→ㄹ)
    # ── GLM-OCR 실측 빈번 오인식 패턴 (빅데이터 분석기사 PDF 기준) ─────────────
    "뉴": "듀",   # "시대에듀" → "시대에뉴" (초성 ㄷ→ㄴ)
    "폴": "필",   # "필기" → "폴기" (중성 ㅣ→ㅗ)
    "곡": "끝",   # "끝내기" → "곡내기"
    "든": "듀",   # "시대에듀" → "시대에든" (종성 추가 혼동)
    "문": "온",   # "온라인" → "문라인" (초성 ㅇ→ㅁ)
    "혁": "험",   # "시험" → "시혁" (중성 ㅕ→ㅓ + 종성 ㄱ→ㅁ)
    "운": "윤",   # "윤승일" → "운승일", "윤아영" → "운아영" (종성 ㄴ 누락)
    "화": "희",   # "김희주" → "김화주" (중성 ㅢ→ㅘ)
    "황": "흥",   # "진흥원" → "진황원" (중성 ㅡ→ㅘ + 종성 ㅇ→ㅇ)
    "포": "필",   # "필기" → "포기" (중성 ㅣ→ㅗ, 종성 ㄹ 탈락)
    "풀": "총",   # "총 8회분" → "풀 8회분"
    "학": "핵",   # "핵심" → "학심" (중성 ㅐ→ㅏ)
    "네": "데",   # "데이터" → "네이터" (초성 ㄷ→ㄴ)
    # ── GLM-OCR 블록 OCR 다중 자모 혼동 ────────────────────────────────────────
    "텍": "데",   # "빅데이터" → "빅텍이터" (초성 ㄷ→ㅌ + 종성 ㄱ 추가)
    "텐": "데",   # "빅데이터" → "빅텐이터" (초성 ㄷ→ㅌ + 종성 ㄴ 추가)
    "택": "데",   # "빅데이터" → "빅택이터" (초성 ㄷ→ㅌ + 종성 ㄱ 추가)
    # ── GLM-OCR CRAFT 파이프라인 추가 패턴 ─────────────────────────────────────
    "떼": "듀",   # "시대에듀" → "시대에떼" (초성 ㄸ→ㄷ, 중성 ㅔ→ㅠ)
    "꼭": "끝",   # "끝내기" → "꼭내기" (초성 ㄲ→ㄱ, 중성 ㅗ→ㅡ, 종성 ㄱ→ㅌ)
}

# ── 빈출 전체 단어 오인식 직접 교정 ────────────────────────────────────────────
# CONFUSION_MAP으로 교정 불가능한 다중 문자 동시 오인식 패턴.
# 사전 매칭 없이 무조건 치환한다 — 사전에 없는 오인식 조합이므로 안전하다.
DIRECT_WORD_MAP: dict[str, str] = {
    "빵테이터": "빅데이터",
    "빵데이터": "빅데이터",
    "빅테이터": "빅데이터",
    "빛테이터": "빅데이터",
    "빅택이터": "빅데이터",
    "빅텍이터": "빅데이터",
    "빅텐이터": "빅데이터",
    "과내기": "끝내기",
    "신업": "산업",
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

    # 0단계: 빈출 전체 단어 오인식 직접 교정 (사전 매칭 불필요)
    for wrong, correct in DIRECT_WORD_MAP.items():
        if wrong in text:
            text = text.replace(wrong, correct)

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
