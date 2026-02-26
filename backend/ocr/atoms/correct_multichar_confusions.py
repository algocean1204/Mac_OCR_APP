# 자모 수준 다중 문자 혼동 보정 모듈
# 단일 문자 치환이 아닌 초성/중성/종성 자모 하나씩을 교체하여
# 사전에 일치하는 후보가 정확히 1개인 경우에만 보정을 적용한다.
#
# 보정 조건 (세 가지 모두 충족해야 교정 수행):
#   1. 원본 단어가 도메인 사전에 없음
#   2. 자모 하나 치환 시 사전에 있는 단어가 정확히 1개 생성됨
#   3. 치환 후보가 유일해야 함 (중의성 없음)
from __future__ import annotations

import re

# correct_confusable_chars 모듈에서 단어 분리 패턴과 조사 분리 함수를 재사용한다
from backend.ocr.atoms.correct_confusable_chars import (
    _WORD_SPLIT_PATTERN,
    _strip_korean_particle,
)

# ── 한글 유니코드 범위 상수 ────────────────────────────────────────────────────
_SYLLABLE_BASE: int = 0xAC00   # '가'의 코드포인트
_SYLLABLE_END: int = 0xD7A3    # '힣'의 코드포인트

# 초성 수 (19자), 중성 수 (21자), 종성 수 (28자 — 없음 포함)
_CHO_COUNT: int = 19
_JUNG_COUNT: int = 21
_JONG_COUNT: int = 28

# ── 자모 혼동 맵 ─────────────────────────────────────────────────────────────
# 모델이 혼동하는 자모 쌍을 인덱스로 정의한다.
# 각 쌍은 양방향(A↔B)으로 치환을 시도한다.

# 중성(모음) 혼동 쌍 — 인덱스 기준
# ㅗ(8)↔ㅜ(13), ㅓ(4)↔ㅏ(0), ㅡ(18)↔ㅓ(4), ㅡ(18)↔ㅜ(13), ㅣ(20)↔ㅐ(1)
_JUNGSEONG_CONFUSIONS: list[tuple[int, int]] = [
    (8, 13),   # ㅗ ↔ ㅜ
    (4, 0),    # ㅓ ↔ ㅏ
    (18, 4),   # ㅡ ↔ ㅓ
    (18, 13),  # ㅡ ↔ ㅜ (증앙→중앙 혼동)
    (20, 1),   # ㅣ ↔ ㅐ
]

# 초성(자음) 혼동 쌍 — 인덱스 기준
# ㅎ(15)↔ㄱ(0), ㅁ(6)↔ㅈ(12)
_CHOSEONG_CONFUSIONS: list[tuple[int, int]] = [
    (15, 0),   # ㅎ ↔ ㄱ
    (6, 12),   # ㅁ ↔ ㅈ
]

# 종성(받침) 혼동 쌍 — 인덱스 기준 (0=없음)
# 종성 인덱스: ㄴ=4, ㄹ=8, ㅁ=16, ㅂ=17, ㅇ=21
# ㅂ(17)↔ㄹ(8), ㅂ(17)↔ㄴ(4), ㅁ(16)↔ㅇ(21)
_JONGSEONG_CONFUSIONS: list[tuple[int, int]] = [
    (17, 8),   # ㅂ ↔ ㄹ (하둡/하둘 혼동)
    (17, 4),   # ㅂ ↔ ㄴ (하둡/하둔 혼동)
    (16, 21),  # ㅁ ↔ ㅇ (점/정 혼동 — 점답→정답)
]


def decompose_syllable(char: str) -> tuple[int, int, int] | None:
    """한글 음절 하나를 초성/중성/종성 인덱스로 분해한다.

    Args:
        char: 단일 한글 음절 문자 (예: '빅')

    Returns:
        (초성, 중성, 종성) 인덱스 튜플.
        한글 음절이 아니면 None을 반환한다.
    """
    code = ord(char)
    # 한글 음절 범위 밖이면 분해 불가
    if code < _SYLLABLE_BASE or code > _SYLLABLE_END:
        return None

    offset = code - _SYLLABLE_BASE
    cho = offset // (_JUNG_COUNT * _JONG_COUNT)
    jung = (offset % (_JUNG_COUNT * _JONG_COUNT)) // _JONG_COUNT
    jong = offset % _JONG_COUNT
    return cho, jung, jong


def compose_syllable(cho: int, jung: int, jong: int) -> str:
    """초성/중성/종성 인덱스를 한글 음절 하나로 조합한다.

    Args:
        cho: 초성 인덱스 (0~18)
        jung: 중성 인덱스 (0~20)
        jong: 종성 인덱스 (0~27, 0=받침 없음)

    Returns:
        조합된 한글 음절 문자열.
        인덱스가 범위를 벗어나면 물음표('?')를 반환한다.
    """
    # 인덱스 범위 검증 — 잘못된 인덱스는 조합 불가
    if not (0 <= cho < _CHO_COUNT and 0 <= jung < _JUNG_COUNT and 0 <= jong < _JONG_COUNT):
        return "?"

    code = _SYLLABLE_BASE + cho * _JUNG_COUNT * _JONG_COUNT + jung * _JONG_COUNT + jong
    return chr(code)


def _generate_jamo_candidates(
    word: str,
    dictionary: frozenset[str],
) -> list[str]:
    """단어의 각 음절에서 자모 하나씩 치환하여 사전 매칭 후보를 생성한다.

    모든 음절 × 모든 혼동 자모 쌍을 탐색하고,
    치환 결과가 사전에 있으면 후보 목록에 추가한다.

    Args:
        word: 교정 대상 단어 (사전에 없는 단어)
        dictionary: 도메인 용어 집합

    Returns:
        사전에 존재하는 교정 후보 목록 (중복 제거)
    """
    unique_candidates: set[str] = set()
    chars = list(word)

    for idx, char in enumerate(chars):
        components = decompose_syllable(char)
        # 한글 음절이 아닌 문자는 자모 치환 대상에서 제외한다
        if components is None:
            continue
        cho, jung, jong = components

        # 중성(모음) 혼동 치환 시도
        for a, b in _JUNGSEONG_CONFUSIONS:
            target = b if jung == a else (a if jung == b else None)
            if target is None:
                continue
            candidate = _substitute_syllable(chars, idx, cho, target, jong)
            if candidate in dictionary:
                unique_candidates.add(candidate)

        # 초성(자음) 혼동 치환 시도
        for a, b in _CHOSEONG_CONFUSIONS:
            target = b if cho == a else (a if cho == b else None)
            if target is None:
                continue
            candidate = _substitute_syllable(chars, idx, target, jung, jong)
            if candidate in dictionary:
                unique_candidates.add(candidate)

        # 종성(받침) 혼동 치환 시도
        for a, b in _JONGSEONG_CONFUSIONS:
            target = b if jong == a else (a if jong == b else None)
            if target is None:
                continue
            candidate = _substitute_syllable(chars, idx, cho, jung, target)
            if candidate in dictionary:
                unique_candidates.add(candidate)

    return list(unique_candidates)


def _substitute_syllable(
    chars: list[str],
    idx: int,
    cho: int,
    jung: int,
    jong: int,
) -> str:
    """문자 목록의 특정 위치 음절을 새 자모 조합으로 치환한 단어를 반환한다.

    Args:
        chars: 원본 단어의 문자 목록
        idx: 치환할 음절의 인덱스
        cho: 새 초성 인덱스
        jung: 새 중성 인덱스
        jong: 새 종성 인덱스

    Returns:
        치환이 적용된 단어 문자열
    """
    new_char = compose_syllable(cho, jung, jong)
    # 조합 실패 시 ('?') 원본 문자를 유지하여 잘못된 교정을 방지한다
    if new_char == "?":
        return "".join(chars)
    return "".join(chars[:idx] + [new_char] + chars[idx + 1:])


def correct_multichar_confusions(
    text: str,
    dictionary: frozenset[str],
) -> str:
    """자모 수준 혼동 치환으로 다중 문자 오인식을 보정한다.

    correct_confusable_chars와 동일한 보수적 3-조건 규칙을 적용한다:
    사전 미등재 + 후보 1개 + 중의성 없음일 때만 교정한다.
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

    # 구분자로 분리하되 구분자 토큰도 보존한다
    tokens = _WORD_SPLIT_PATTERN.split(text)
    corrected_tokens = [_correct_multichar_token(token, dictionary) for token in tokens]
    return "".join(corrected_tokens)


def _correct_multichar_token(token: str, dictionary: frozenset[str]) -> str:
    """단일 토큰에 대해 자모 혼동 보정을 시도한다.

    1차: 전체 단어로 사전 기반 교정 시도.
    2차: 조사를 분리한 어간(stem)으로 재시도.

    Args:
        token: 분리된 단일 토큰 문자열
        dictionary: 도메인 용어 집합

    Returns:
        보정된 토큰 또는 원본 토큰
    """
    # 구분자 또는 공백 토큰은 보정 대상이 아님
    if not token.strip():
        return token

    # 이미 사전에 있는 단어는 보정 불필요
    if token in dictionary:
        return token

    # 1차: 전체 단어로 자모 교정 시도
    candidates = _generate_jamo_candidates(token, dictionary)
    if len(candidates) == 1:
        return candidates[0]

    # 2차: 조사 분리 후 어간만으로 자모 교정 시도
    stem, particle = _strip_korean_particle(token)
    if not particle or stem in dictionary:
        return token

    stem_candidates = _generate_jamo_candidates(stem, dictionary)
    if len(stem_candidates) == 1:
        # 교정된 어간에 원래 조사를 다시 붙여 반환
        return stem_candidates[0] + particle

    return token
