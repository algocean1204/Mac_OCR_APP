# 반복 출력 감지 및 제거 모듈
# 모델이 환각 상태에서 동일 토큰/줄을 수만 번 반복 출력하는 현상을 감지하고
# 반복 구간을 제거하여 유효 텍스트만 보존한다
from __future__ import annotations

import re

# ── 연속 동일 줄 반복 패턴 ──────────────────────────────────────────────────
# 같은 줄이 3회 이상 연속으로 나타나면 반복 시작점으로 판정한다
_MIN_LINE_REPEATS: int = 3

# ── 연속 동일 문자 반복 패턴 ────────────────────────────────────────────────
# 같은 문자가 30자 이상 연속으로 나타나면 환각으로 판정한다
_CHAR_REPEAT_PATTERN: re.Pattern[str] = re.compile(r"(.)\1{29,}")

# ── 짧은 토큰 반복 패턴 ─────────────────────────────────────────────────────
# 1~5글자 토큰이 10회 이상 연속 반복되면 환각으로 판정한다
_TOKEN_REPEAT_PATTERN: re.Pattern[str] = re.compile(r"(.{1,5})\1{9,}")

# ── 페이지 예상 최대 텍스트 길이 ────────────────────────────────────────────
# A4 페이지 기준 한국어 텍스트 최대량: 약 2,000~3,000자
# 안전 마진을 포함하여 5,000자를 정상 상한으로 설정한다
_MAX_REASONABLE_CHARS: int = 5000


def detect_line_repetition_start(text: str) -> int | None:
    """연속 동일 줄 반복이 시작되는 위치(문자 인덱스)를 반환한다.

    같은 줄이 _MIN_LINE_REPEATS회 이상 연속으로 나타나는
    첫 번째 반복 구간의 시작 인덱스를 반환한다.
    반복이 없으면 None을 반환한다.

    Args:
        text: 검사할 텍스트

    Returns:
        반복 시작 위치(문자 인덱스) 또는 None
    """
    lines = text.split("\n")
    if len(lines) < _MIN_LINE_REPEATS:
        return None

    char_offset = 0
    consecutive = 1

    for i in range(1, len(lines)):
        if lines[i] == lines[i - 1] and lines[i].strip():
            consecutive += 1
            if consecutive >= _MIN_LINE_REPEATS:
                # 반복 시작점 = 첫 번째 반복 줄의 시작 위치
                start_line_idx = i - _MIN_LINE_REPEATS + 1
                offset = sum(len(lines[j]) + 1 for j in range(start_line_idx))
                return offset
        else:
            consecutive = 1

    return None


def remove_repetitive_output(text: str) -> str:
    """환각으로 인한 반복 출력을 감지하고 제거한다.

    세 가지 수준의 반복을 순차적으로 검사한다:
    1. 연속 동일 줄 반복 (3회+) — 반복 시작점에서 텍스트 절단
    2. 짧은 토큰 반복 (1~5자 토큰 10회+) — 반복 구간 제거
    3. 단일 문자 반복 (30자+) — 반복 구간 제거

    Args:
        text: OCR 원시 출력 텍스트

    Returns:
        반복이 제거된 정제 텍스트
    """
    if not text or len(text) < 100:
        return text

    # 1단계: 연속 동일 줄 반복 감지 — 반복 시작점에서 절단
    repeat_start = detect_line_repetition_start(text)
    if repeat_start is not None and repeat_start > 0:
        # 반복 시작 직전까지만 보존한다
        text = text[:repeat_start].rstrip()

    # 2단계: 짧은 토큰 반복 제거 (1~5자 토큰이 10회+ 연속)
    text = _TOKEN_REPEAT_PATTERN.sub(r"\1", text)

    # 3단계: 단일 문자 반복 제거 (30자+ 연속)
    text = _CHAR_REPEAT_PATTERN.sub(r"\1", text)

    return text.strip()


def is_output_anomalous(text: str) -> bool:
    """출력 텍스트가 비정상적으로 긴지 판정한다.

    페이지 예상 최대 텍스트량(_MAX_REASONABLE_CHARS)을 초과하면
    환각 출력 가능성이 높다고 판정한다.

    Args:
        text: 검사할 텍스트

    Returns:
        True이면 비정상 (환각 의심), False이면 정상
    """
    return len(text) > _MAX_REASONABLE_CHARS
