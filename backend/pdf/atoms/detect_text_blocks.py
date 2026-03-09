# 텍스트 블록 감지 모듈
# Tesseract 단어 박스를 기반으로 글자 크기별 텍스트 블록을 감지한다
# 큰 제목, 중간 본문, 작은 표 셀을 각각 별도 블록으로 분리한다
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from PIL import Image

logger = logging.getLogger(__name__)


class BlockSize(Enum):
    """블록의 글자 크기 카테고리."""
    LARGE = "large"      # 제목, 헤더 (h > median * 1.4)
    MEDIUM = "medium"    # 본문 텍스트 (median 근처)
    SMALL = "small"      # 표 셀, 각주 (h < median * 0.7)


@dataclass
class TextBlock:
    """감지된 텍스트 블록의 위치와 크기 정보."""
    x: int
    y: int
    x2: int
    y2: int
    size: BlockSize
    char_height: int  # 평균 글자 높이 (px)


def detect_text_blocks(image: Image.Image) -> list[TextBlock]:
    """이미지에서 글자 크기별 텍스트 블록을 감지한다.

    Tesseract 단어 박스를 기반으로:
    1. 모든 단어 위치를 수집한다
    2. 글자 높이 기준으로 크기를 분류한다
    3. 같은 행·같은 크기의 단어를 하나의 블록으로 묶는다
    4. 인접 블록을 행 단위로 병합한다
    """
    try:
        import pytesseract
    except ImportError:
        logger.warning("pytesseract 미설치")
        return []

    words = _get_word_boxes(image, pytesseract)
    if len(words) < 2:
        return []

    # 글자 높이 중앙값으로 크기 분류 기준 결정
    heights = sorted(w["h"] for w in words)
    median_h = heights[len(heights) // 2]

    # 각 단어에 크기 카테고리 부여
    for w in words:
        if w["h"] > median_h * 1.4:
            w["size"] = BlockSize.LARGE
        elif w["h"] < median_h * 0.7:
            w["size"] = BlockSize.SMALL
        else:
            w["size"] = BlockSize.MEDIUM

    # 같은 행·같은 크기의 단어를 블록으로 그룹화
    blocks = _group_words_into_blocks(words, median_h)

    # 너무 작은 블록 필터링
    img_w, img_h = image.size
    min_w = img_w * 0.01
    min_h = img_h * 0.003
    blocks = [b for b in blocks if (b.x2 - b.x) >= min_w and (b.y2 - b.y) >= min_h]

    # Y 위치, X 위치 순으로 정렬 (읽기 순서)
    blocks.sort(key=lambda b: (b.y, b.x))
    return blocks


def _get_word_boxes(
    image: Image.Image, pytesseract: object,
) -> list[dict]:
    """Tesseract에서 단어 수준 바운딩 박스를 추출한다."""
    for psm in [6, 11, 3]:
        try:
            data = pytesseract.image_to_data(  # type: ignore[union-attr]
                image, lang="kor+eng", config=f"--psm {psm}",
                output_type=pytesseract.Output.DICT,  # type: ignore[union-attr]
            )
        except Exception:
            continue

        words: list[dict] = []
        for i in range(len(data["text"])):
            conf = int(data["conf"][i])
            if conf < 10:
                continue
            text = data["text"][i].strip()
            if not text:
                continue
            w = data["width"][i]
            h = data["height"][i]
            if w < 3 or h < 3:
                continue
            words.append({
                "x": data["left"][i],
                "y": data["top"][i],
                "x2": data["left"][i] + w,
                "y2": data["top"][i] + h,
                "h": h,
                "text": text,
            })

        if len(words) >= 5:
            return words

    return words if words else []


def _group_words_into_blocks(
    words: list[dict], median_h: float,
) -> list[TextBlock]:
    """같은 행·같은 크기의 단어를 하나의 블록으로 묶는다.

    행 내에서 큰 X 갭이 있으면 별도 블록으로 분리한다 (표 셀).
    """
    if not words:
        return []

    # Y 위치로 정렬
    words.sort(key=lambda w: (w["y"], w["x"]))

    # 행 그룹화 (Y 중심이 가까운 단어 = 같은 행)
    rows: list[list[dict]] = [[words[0]]]
    for w in words[1:]:
        last_row = rows[-1]
        row_cy = sum((r["y"] + r["y2"]) / 2 for r in last_row) / len(last_row)
        w_cy = (w["y"] + w["y2"]) / 2
        row_avg_h = sum(r["h"] for r in last_row) / len(last_row)

        if abs(w_cy - row_cy) <= row_avg_h * 0.6:
            last_row.append(w)
        else:
            rows.append([w])

    # 각 행 내에서 크기별·X갭 기준으로 블록 생성
    blocks: list[TextBlock] = []

    for row in rows:
        # 같은 크기끼리 분리
        by_size: dict[BlockSize, list[dict]] = {}
        for w in row:
            by_size.setdefault(w["size"], []).append(w)

        for size, size_words in by_size.items():
            size_words.sort(key=lambda w: w["x"])
            # X 갭이 크면 별도 블록으로 분리
            cell_groups = _split_by_x_gap(size_words, median_h)

            for group in cell_groups:
                x = min(w["x"] for w in group)
                y = min(w["y"] for w in group)
                x2 = max(w["x2"] for w in group)
                y2 = max(w["y2"] for w in group)
                avg_h = int(sum(w["h"] for w in group) / len(group))
                blocks.append(TextBlock(
                    x=x, y=y, x2=x2, y2=y2,
                    size=size, char_height=avg_h,
                ))

    return blocks


def _split_by_x_gap(
    words: list[dict], median_h: float,
) -> list[list[dict]]:
    """X 방향 갭이 큰 곳에서 단어 그룹을 분리한다."""
    if len(words) <= 1:
        return [words]

    # 갭 임계값: 중앙 높이의 1.5배 (표 셀 간 간격)
    gap_threshold = median_h * 1.5

    groups: list[list[dict]] = [[words[0]]]
    for w in words[1:]:
        prev = groups[-1][-1]
        gap = w["x"] - prev["x2"]
        if gap > gap_threshold:
            groups.append([w])
        else:
            groups[-1].append(w)

    return groups
