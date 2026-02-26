# 텍스트 청킹 모듈
# LLM 후처리를 위해 긴 텍스트를 문장 경계 기준으로 분할한다.
# 최대 문자 수를 초과하지 않으면서 overlap을 통해 문맥 연속성을 보장한다.
from __future__ import annotations

import re

# 문장 경계를 탐지하는 패턴
# 마침표+공백/줄바꿈, 물음표, 느낌표 뒤를 문장 종료 지점으로 인식한다
_SENTENCE_BOUNDARY: re.Pattern[str] = re.compile(
    r"(?<=[.?!])\s+|(?<=\n)\n"
)


def chunk_text_for_refinement(
    text: str,
    max_chars: int = 2000,
    overlap_chars: int = 100,
) -> list[str]:
    """텍스트를 LLM 후처리용 청크로 분할한다.

    문장 경계를 기준으로 분할하며, 각 청크가 max_chars를 초과하지 않도록 한다.
    청크 간 overlap_chars만큼 앞 청크의 끝을 다음 청크 앞에 붙여 문맥 연속성을 확보한다.
    텍스트가 max_chars 이하이면 원본 텍스트 하나를 리스트로 반환한다.

    Args:
        text: 분할 대상 텍스트
        max_chars: 청크당 최대 문자 수 (기본값 2000)
        overlap_chars: 청크 간 중첩 문자 수 (기본값 100)

    Returns:
        청크 문자열 목록. 입력이 비어 있으면 빈 리스트 반환.
    """
    # 빈 텍스트는 빈 목록으로 반환한다
    if not text or not text.strip():
        return []

    # 청크 분할이 불필요한 경우 — 원본 그대로 반환한다
    if len(text) <= max_chars:
        return [text]

    sentences = _split_into_sentences(text)
    return _build_chunks(sentences, max_chars, overlap_chars)


def _split_into_sentences(text: str) -> list[str]:
    """텍스트를 문장 단위 조각으로 분리한다.

    문장 경계 패턴으로 분리하되, 구분자(공백/줄바꿈)도 다음 조각 앞에 포함시켜
    원본 포맷을 최대한 보존한다.

    Args:
        text: 분리 대상 텍스트

    Returns:
        문장 조각 목록
    """
    # 문장 경계를 기준으로 분리하되 구분자도 포함하여 재결합 가능하게 한다
    parts = _SENTENCE_BOUNDARY.split(text)
    # 빈 조각 제거 후 반환한다
    return [p for p in parts if p]


def _build_chunks(
    sentences: list[str],
    max_chars: int,
    overlap_chars: int,
) -> list[str]:
    """문장 조각 목록을 최대 문자 수 기준으로 청크로 묶는다.

    각 청크는 max_chars를 초과하지 않으며,
    이전 청크의 마지막 overlap_chars 문자를 현재 청크 앞에 붙여 문맥을 연결한다.

    Args:
        sentences: 분리된 문장 조각 목록
        max_chars: 청크당 최대 문자 수
        overlap_chars: 청크 간 중첩 문자 수

    Returns:
        완성된 청크 목록
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len: int = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        # 현재 청크에 추가하면 max_chars를 초과하는 경우 — 청크를 확정하고 새 청크를 시작한다
        if current_len + sentence_len > max_chars and current_parts:
            chunk_text = "".join(current_parts)
            chunks.append(chunk_text)

            # 다음 청크는 이전 청크 끝 overlap_chars를 앞에 붙여 문맥을 연결한다
            overlap_prefix = chunk_text[-overlap_chars:] if len(chunk_text) > overlap_chars else chunk_text
            current_parts = [overlap_prefix, sentence]
            current_len = len(overlap_prefix) + sentence_len
        else:
            current_parts.append(sentence)
            current_len += sentence_len

    # 마지막 청크를 추가한다
    if current_parts:
        chunks.append("".join(current_parts))

    return chunks
