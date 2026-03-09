# 문장 단위 블록 병합 모듈
# 인접 블록들을 문장 연속성 기준으로 병합한다
# 블럭 → 글씨확인 → 문장확인 → 문장 연속 확인 → 문장 단위 블럭
from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

from backend.pdf.atoms.detect_text_blocks import BlockSize, TextBlock

logger = logging.getLogger(__name__)


@dataclass
class SentenceBlock:
    """문장 단위로 병합된 블록. OCR 입력 단위가 된다."""
    x: int
    y: int
    x2: int
    y2: int
    size: BlockSize
    char_height: int
    source_blocks: list[TextBlock]  # 병합 전 원본 블록들


def merge_into_sentence_blocks(
    blocks: list[TextBlock],
    image: Image.Image,
) -> list[SentenceBlock]:
    """텍스트 블록을 문장 단위로 병합한다.

    1. 블록 내 글씨 존재 여부를 확인한다 (크기 기반 필터링)
    2. 같은 크기·같은 행의 블록을 하나의 문장 블록으로 묶는다
    3. 수직으로 연속된 같은 크기 블록을 단락 단위로 병합한다
    """
    if not blocks:
        return []

    img_w, img_h = image.size

    # 1단계: 너무 작은 블록 제거 (글씨 없는 노이즈)
    valid_blocks = _filter_noise_blocks(blocks, img_w, img_h)
    if not valid_blocks:
        return []

    # 2단계: 같은 행·같은 크기의 블록을 수평 병합
    row_merged = _merge_horizontal(valid_blocks)

    # 수직 병합 비활성화 — 한 줄 = 한 블록을 유지하여
    # 글씨 크기가 정확히 매칭되도록 한다.
    # 수직 병합하면 여러 줄이 하나의 블록이 되어 글씨가 작아진다.

    # Y 위치 → X 위치 순으로 정렬 (읽기 순서)
    row_merged.sort(key=lambda b: (b.y, b.x))
    return row_merged


def _filter_noise_blocks(
    blocks: list[TextBlock],
    img_w: int,
    img_h: int,
) -> list[TextBlock]:
    """너무 작거나 비정상적인 블록을 필터링한다."""
    min_block_w = img_w * 0.008
    min_block_h = img_h * 0.004
    filtered: list[TextBlock] = []

    for b in blocks:
        bw = b.x2 - b.x
        bh = b.y2 - b.y
        if bw < min_block_w or bh < min_block_h:
            continue
        # 가로세로 비율이 극단적이면 노이즈로 판단
        if bw > 0 and bh / bw > 10:
            continue
        filtered.append(b)

    return filtered


def _merge_horizontal(blocks: list[TextBlock]) -> list[SentenceBlock]:
    """같은 행·같은 크기의 블록을 수평으로 병합한다.

    X 갭이 글자 높이의 3배 이내이면 같은 문장으로 판단한다.
    표 셀(SMALL)은 병합하지 않고 개별 유지한다.
    """
    if not blocks:
        return []

    # Y 위치 → X 위치 순으로 정렬
    sorted_blocks = sorted(blocks, key=lambda b: (b.y, b.x))

    # 행 그룹화 (Y 중심이 가까운 블록 = 같은 행)
    rows: list[list[TextBlock]] = [[sorted_blocks[0]]]
    for b in sorted_blocks[1:]:
        last_row = rows[-1]
        row_cy = sum((r.y + r.y2) / 2 for r in last_row) / len(last_row)
        b_cy = (b.y + b.y2) / 2
        row_avg_h = sum(r.char_height for r in last_row) / len(last_row)

        if abs(b_cy - row_cy) <= row_avg_h * 0.7:
            last_row.append(b)
        else:
            rows.append([b])

    result: list[SentenceBlock] = []
    for row in rows:
        # 같은 크기끼리 분리
        by_size: dict[BlockSize, list[TextBlock]] = {}
        for b in row:
            by_size.setdefault(b.size, []).append(b)

        for size, size_blocks in by_size.items():
            size_blocks.sort(key=lambda b: b.x)

            # SMALL 블록(표 셀)은 개별 유지
            if size == BlockSize.SMALL:
                for b in size_blocks:
                    result.append(SentenceBlock(
                        x=b.x, y=b.y, x2=b.x2, y2=b.y2,
                        size=b.size, char_height=b.char_height,
                        source_blocks=[b],
                    ))
                continue

            # MEDIUM/LARGE 블록은 X 갭 기반으로 연속 문장 병합
            gap_threshold = size_blocks[0].char_height * 3.0
            groups: list[list[TextBlock]] = [[size_blocks[0]]]

            for b in size_blocks[1:]:
                prev = groups[-1][-1]
                gap = b.x - prev.x2
                if gap <= gap_threshold:
                    groups[-1].append(b)
                else:
                    groups.append([b])

            for group in groups:
                x = min(b.x for b in group)
                y = min(b.y for b in group)
                x2 = max(b.x2 for b in group)
                y2 = max(b.y2 for b in group)
                avg_h = int(sum(b.char_height for b in group) / len(group))
                result.append(SentenceBlock(
                    x=x, y=y, x2=x2, y2=y2,
                    size=size, char_height=avg_h,
                    source_blocks=list(group),
                ))

    return result


def _merge_vertical(blocks: list[SentenceBlock]) -> list[SentenceBlock]:
    """수직으로 연속된 같은 크기·같은 X 범위의 블록을 단락으로 병합한다.

    같은 컬럼(X 범위 겹침 70% 이상)에서 Y 갭이 글자 높이의 1.5배 이내이면
    같은 단락으로 판단하여 병합한다.
    SMALL 블록은 병합하지 않는다.
    """
    if len(blocks) <= 1:
        return blocks

    # Y 위치 → X 위치 순으로 정렬
    sorted_blocks = sorted(blocks, key=lambda b: (b.y, b.x))

    merged: list[SentenceBlock] = []
    current = sorted_blocks[0]

    for b in sorted_blocks[1:]:
        if current.size == BlockSize.SMALL or b.size == BlockSize.SMALL:
            merged.append(current)
            current = b
            continue

        if current.size != b.size:
            merged.append(current)
            current = b
            continue

        # X 범위 겹침 비율 계산
        overlap_x = max(0, min(current.x2, b.x2) - max(current.x, b.x))
        current_w = current.x2 - current.x
        b_w = b.x2 - b.x
        min_w = min(current_w, b_w)
        overlap_ratio = overlap_x / max(min_w, 1)

        # Y 갭 계산
        y_gap = b.y - current.y2

        # 같은 컬럼(70%+ 겹침)이고 Y 갭이 작으면 병합
        if overlap_ratio >= 0.7 and y_gap <= current.char_height * 1.5:
            # 현재 블록을 확장
            current = SentenceBlock(
                x=min(current.x, b.x),
                y=current.y,
                x2=max(current.x2, b.x2),
                y2=b.y2,
                size=current.size,
                char_height=int((current.char_height + b.char_height) / 2),
                source_blocks=current.source_blocks + b.source_blocks,
            )
        else:
            merged.append(current)
            current = b

    merged.append(current)
    return merged
