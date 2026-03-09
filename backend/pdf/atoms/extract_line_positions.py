# 텍스트 위치 추출 모듈 — Tesseract 단어 박스 + 수평 프로젝션
# GLM-OCR은 텍스트만 제공하므로, 위치 정보는 Tesseract 단어 박스에서 추출한다
# 표 페이지: 셀 단위 위치 감지 (열 인식)
# 텍스트 페이지: 줄 단위 위치 감지
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE: int = 10
_MIN_LINE_H_RATIO: float = 0.003
_MAX_LINE_H_RATIO: float = 0.06
_MIN_LINE_W_RATIO: float = 0.015


@dataclass
class LinePosition:
    """텍스트의 이미지 내 위치 (줄 또는 셀)."""
    x: int
    y: int
    x2: int
    y2: int
    text: str


@dataclass
class TextRegion:
    """텍스트 영역과 위치 목록."""
    top_y: int
    bottom_y: int
    left_x: int
    right_x: int
    lines: list[LinePosition]


@dataclass
class PlacedLine:
    """PDF에 배치할 텍스트와 좌표."""
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass
class PlacementResult:
    """OCR 텍스트의 PDF 배치 결과."""
    lines: list[PlacedLine]
    mode: str


# ── 공개 API ──────────────────────────────────────────────────────────────

def extract_text_region(image: Image.Image) -> TextRegion | None:
    """이미지에서 텍스트 위치를 추출한다.

    Tesseract 단어 박스 기반 셀/구절 감지를 우선 사용하고,
    수평 프로젝션 줄 감지를 보조로 활용한다.
    표 페이지에서는 셀 단위, 텍스트 페이지에서는 줄 단위 위치를 반환한다.
    """
    img_w, img_h = image.size

    # 1단계: Tesseract 단어 박스 → 구절(셀) 그룹
    word_groups = _detect_word_groups(image, img_w, img_h)

    # 2단계: 줄 단위 감지 (Tesseract + 프로젝션)
    line_positions = _detect_lines_combined(image, img_w, img_h)

    # 더 많은 위치를 제공하는 결과를 사용한다
    # 표 페이지는 단어 그룹이 훨씬 많고, 텍스트 페이지는 비슷하다
    best = word_groups if len(word_groups) >= len(line_positions) else line_positions

    if len(best) < 2:
        # 둘 다 부족하면 나머지 시도
        fallback = line_positions if best is word_groups else word_groups
        if len(fallback) >= 2:
            best = fallback
        else:
            return None

    return TextRegion(
        top_y=min(p.y for p in best),
        bottom_y=max(p.y2 for p in best),
        left_x=min(p.x for p in best),
        right_x=max(p.x2 for p in best),
        lines=best,
    )


def map_ocr_to_pdf_positions(
    region: TextRegion,
    ocr_lines: list[str],
    img_width: int,
    img_height: int,
    page_width_pt: float,
    page_height_pt: float,
) -> PlacementResult:
    """OCR 줄을 감지된 위치에 매핑하여 PDF 배치 결과를 생성한다."""
    x_scale = page_width_pt / img_width
    y_scale = page_height_pt / img_height
    n_ocr = len(ocr_lines)
    n_pos = len(region.lines)

    if n_pos == 0:
        return _distribute_fallback(
            ocr_lines, img_height,
            x_scale, y_scale, page_width_pt, page_height_pt,
        )

    ratio = n_ocr / n_pos

    if ratio <= 1.5:
        # OCR 줄 ≈ 위치 수 → 직접 매핑
        return _map_direct(
            region.lines, ocr_lines, x_scale, y_scale, page_height_pt,
        )
    else:
        # OCR 줄 >> 위치 수 → 각 위치 내에서 개별 배치
        return _map_distributed(
            region.lines, ocr_lines, x_scale, y_scale, page_height_pt,
        )


def region_to_pdf_line_coords(
    region: TextRegion,
    n_ocr_lines: int,
    img_width: int,
    img_height: int,
    page_width_pt: float,
    page_height_pt: float,
) -> list[tuple[float, float, float, float]]:
    """이전 API 호환용 래퍼."""
    dummy = [""] * n_ocr_lines
    result = map_ocr_to_pdf_positions(
        region, dummy, img_width, img_height, page_width_pt, page_height_pt,
    )
    return [(pl.x, pl.y, pl.width, pl.height) for pl in result.lines]


# ── 단어 그룹 감지 (셀 단위) ──────────────────────────────────────────

def _detect_word_groups(
    image: Image.Image, img_w: int, img_h: int,
) -> list[LinePosition]:
    """Tesseract 단어 박스를 구절(셀) 단위로 그룹화한다.

    같은 행의 가까운 단어 → 하나의 구절. 떨어진 단어 → 별도 구절.
    표 셀을 자연스럽게 분리하여 올바른 X 위치를 제공한다.
    """
    try:
        import pytesseract
    except ImportError:
        return []

    words = _get_tesseract_words(image, pytesseract)
    if len(words) < 2:
        return []

    # Y 기준으로 행 그룹화
    rows = _group_words_into_rows(words)

    # 각 행 내에서 X 갭 기준으로 구절(셀) 분리
    groups: list[LinePosition] = []
    for row_words in rows:
        cells = _split_row_into_cells(row_words, img_w)
        groups.extend(cells)

    # 필터링
    filtered = _filter_positions(groups, img_w, img_h)
    return _remove_overlapping(filtered)


def _get_tesseract_words(
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
            if conf < _MIN_CONFIDENCE:
                continue
            text = data["text"][i].strip()
            if not text:
                continue
            w = data["width"][i]
            h = data["height"][i]
            if w < 5 or h < 5:
                continue
            words.append({
                "x": data["left"][i],
                "y": data["top"][i],
                "x2": data["left"][i] + w,
                "y2": data["top"][i] + h,
                "text": text,
            })

        if len(words) >= 5:
            return words

    return words if words else []


def _group_words_into_rows(words: list[dict]) -> list[list[dict]]:
    """단어를 Y 위치 기준으로 행별로 그룹화한다."""
    if not words:
        return []

    words_sorted = sorted(words, key=lambda w: (w["y"], w["x"]))
    rows: list[list[dict]] = [[words_sorted[0]]]

    for w in words_sorted[1:]:
        last_row = rows[-1]
        # 마지막 행의 Y 중심과 비교
        row_cy = sum((r["y"] + r["y2"]) / 2 for r in last_row) / len(last_row)
        w_cy = (w["y"] + w["y2"]) / 2
        row_avg_h = sum(r["y2"] - r["y"] for r in last_row) / len(last_row)

        if abs(w_cy - row_cy) <= row_avg_h * 0.6:
            last_row.append(w)
        else:
            rows.append([w])

    return rows


def _split_row_into_cells(
    row_words: list[dict], img_w: int,
) -> list[LinePosition]:
    """행 내 단어를 X 갭 기준으로 셀(구절)로 분리한다.

    큰 수평 갭 = 다른 열/셀. 작은 갭 = 같은 구절 내 단어 간격.
    """
    if not row_words:
        return []

    row_words.sort(key=lambda w: w["x"])

    # 행 내 단어 간 갭 계산
    gaps: list[float] = []
    for i in range(1, len(row_words)):
        gap = row_words[i]["x"] - row_words[i - 1]["x2"]
        gaps.append(gap)

    # 갭 임계값: 행 내 평균 단어 높이의 1.2배 또는 이미지 너비의 3%
    avg_h = sum(w["y2"] - w["y"] for w in row_words) / len(row_words)
    gap_threshold = max(avg_h * 1.2, img_w * 0.03)

    # 갭이 큰 곳에서 분리
    cells: list[list[dict]] = [[row_words[0]]]
    for i, gap in enumerate(gaps):
        if gap > gap_threshold:
            cells.append([row_words[i + 1]])
        else:
            cells[-1].append(row_words[i + 1])

    # 각 셀을 LinePosition으로 변환
    positions: list[LinePosition] = []
    for cell_words in cells:
        x = min(w["x"] for w in cell_words)
        y = min(w["y"] for w in cell_words)
        x2 = max(w["x2"] for w in cell_words)
        y2 = max(w["y2"] for w in cell_words)
        text = " ".join(w["text"] for w in cell_words)
        positions.append(LinePosition(x=x, y=y, x2=x2, y2=y2, text=text))

    return positions


# ── 줄 단위 감지 (기존 방식) ───────────────────────────────────────────

def _detect_lines_combined(
    image: Image.Image, img_w: int, img_h: int,
) -> list[LinePosition]:
    """Tesseract 줄 감지 + 프로젝션 감지를 결합한다."""
    tess = _detect_lines_tesseract(image)
    tess_f = _filter_positions(tess, img_w, img_h)

    proj = _detect_lines_projection(image)
    proj_f = _filter_positions(proj, img_w, img_h)

    merged = _merge_detections(tess_f, proj_f)
    return _remove_overlapping(merged)


def _detect_lines_tesseract(image: Image.Image) -> list[LinePosition]:
    """Tesseract 줄 단위 위치 감지."""
    try:
        import pytesseract
    except ImportError:
        return []

    for psm in [6, 11]:
        positions = _run_tesseract_lines(image, psm, pytesseract)
        if len(positions) >= 3:
            return positions

    return positions if positions else []


def _run_tesseract_lines(
    image: Image.Image, psm: int, pytesseract: object,
) -> list[LinePosition]:
    """Tesseract 줄 단위 바운딩 박스 추출."""
    try:
        data = pytesseract.image_to_data(  # type: ignore[union-attr]
            image, lang="kor+eng", config=f"--psm {psm}",
            output_type=pytesseract.Output.DICT,  # type: ignore[union-attr]
        )
    except Exception:
        return []

    line_groups: dict[tuple[int, int, int], list[dict]] = {}
    for i in range(len(data["text"])):
        conf = int(data["conf"][i])
        if conf < 0 or conf < _MIN_CONFIDENCE:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line_groups.setdefault(key, []).append({
            "left": data["left"][i], "top": data["top"][i],
            "width": data["width"][i], "height": data["height"][i],
            "text": data["text"][i].strip(),
        })

    positions: list[LinePosition] = []
    for words in line_groups.values():
        text_words = [w for w in words if w["text"]]
        if not text_words:
            continue
        x = min(w["left"] for w in words)
        y = min(w["top"] for w in words)
        x2 = max(w["left"] + w["width"] for w in words)
        y2 = max(w["top"] + w["height"] for w in words)
        text = " ".join(w["text"] for w in text_words)
        positions.append(LinePosition(x=x, y=y, x2=x2, y2=y2, text=text))

    positions.sort(key=lambda p: (p.y, p.x))
    return positions


def _detect_lines_projection(image: Image.Image) -> list[LinePosition]:
    """수평 프로젝션으로 텍스트 줄 위치를 감지한다."""
    gray = np.array(image.convert("L"), dtype=np.float32)
    h, w = gray.shape

    block_size = max(100, h // 20)
    binary = np.zeros_like(gray)
    for start in range(0, h, block_size):
        end = min(start + block_size, h)
        block = gray[start:end, :]
        block_mean = block.mean()
        block_std = block.std()
        if block_std < 10:
            continue
        thresh = block_mean - block_std * 0.8
        thresh = max(thresh, 80)
        binary[start:end, :] = (block < thresh).astype(np.float32)

    h_proj = binary.sum(axis=1)
    kernel = np.ones(3) / 3
    h_proj = np.convolve(h_proj, kernel, mode="same")

    min_proj = w * 0.005
    in_line = False
    line_start = 0
    raw_lines: list[tuple[int, int]] = []

    for y_idx in range(len(h_proj)):
        if h_proj[y_idx] > min_proj:
            if not in_line:
                line_start = y_idx
                in_line = True
        else:
            if in_line:
                raw_lines.append((line_start, y_idx))
                in_line = False
    if in_line:
        raw_lines.append((line_start, len(h_proj)))

    positions: list[LinePosition] = []
    for y1, y2 in raw_lines:
        line_data = binary[y1:y2, :]
        v_proj = line_data.sum(axis=0)
        nonzero = np.where(v_proj > 0)[0]
        if len(nonzero) < w * 0.015:
            continue
        x1 = int(nonzero[0])
        x2_val = int(nonzero[-1])
        line_h = y2 - y1
        line_w = x2_val - x1
        if line_h <= 5 and line_w > w * 0.7:
            continue
        positions.append(LinePosition(x=x1, y=y1, x2=x2_val, y2=y2, text=""))

    positions.sort(key=lambda p: (p.y, p.x))
    return positions


# ── 필터링·병합 유틸리티 ──────────────────────────────────────────────

def _filter_positions(
    positions: list[LinePosition], img_w: int, img_h: int,
) -> list[LinePosition]:
    """비정상 위치를 필터링한다."""
    min_h = max(8, int(img_h * _MIN_LINE_H_RATIO))
    max_h = int(img_h * _MAX_LINE_H_RATIO)
    min_w = int(img_w * _MIN_LINE_W_RATIO)

    filtered: list[LinePosition] = []
    for pos in positions:
        h = pos.y2 - pos.y
        w = pos.x2 - pos.x
        if h < min_h or h > max_h:
            continue
        if w < min_w:
            continue
        filtered.append(pos)

    return _merge_close_positions(filtered)


def _merge_close_positions(positions: list[LinePosition]) -> list[LinePosition]:
    """Y와 X가 모두 가까운 위치를 병합한다."""
    if len(positions) <= 1:
        return positions

    positions.sort(key=lambda p: ((p.y + p.y2) / 2, (p.x + p.x2) / 2))
    merged: list[LinePosition] = [positions[0]]

    for pos in positions[1:]:
        prev = merged[-1]
        prev_cy = (prev.y + prev.y2) / 2
        curr_cy = (pos.y + pos.y2) / 2
        max_h = max(prev.y2 - prev.y, pos.y2 - pos.y)

        # Y가 가깝고 X도 겹치면 병합
        y_close = abs(curr_cy - prev_cy) <= max_h * 0.35
        x_overlap = pos.x < prev.x2 + max_h * 0.3

        if y_close and x_overlap:
            prev.x = min(prev.x, pos.x)
            prev.y = min(prev.y, pos.y)
            prev.x2 = max(prev.x2, pos.x2)
            prev.y2 = max(prev.y2, pos.y2)
        else:
            merged.append(pos)

    return merged


def _remove_overlapping(positions: list[LinePosition]) -> list[LinePosition]:
    """완전히 겹치는 위치를 제거한다."""
    if len(positions) <= 1:
        return positions

    positions.sort(key=lambda p: (p.y, p.x))
    result: list[LinePosition] = [positions[0]]

    for pos in positions[1:]:
        prev = result[-1]
        # 이전 위치에 완전히 포함되면 건너뜀
        if (pos.x >= prev.x and pos.x2 <= prev.x2 and
                pos.y >= prev.y and pos.y2 <= prev.y2):
            continue
        result.append(pos)

    return result


def _merge_detections(
    lines_a: list[LinePosition],
    lines_b: list[LinePosition],
) -> list[LinePosition]:
    """두 감지 결과의 합집합을 생성한다."""
    if not lines_a:
        return lines_b
    if not lines_b:
        return lines_a

    combined = list(lines_a)
    for lb in lines_b:
        lb_cy = (lb.y + lb.y2) / 2
        lb_h = lb.y2 - lb.y
        has_match = False
        for la in combined:
            la_cy = (la.y + la.y2) / 2
            max_h = max(la.y2 - la.y, lb_h)
            if abs(la_cy - lb_cy) < max_h * 0.5:
                la.x = min(la.x, lb.x)
                la.x2 = max(la.x2, lb.x2)
                has_match = True
                break
        if not has_match:
            combined.append(lb)

    combined.sort(key=lambda p: (p.y, p.x))
    return _merge_close_positions(combined)


# ── OCR→PDF 매핑 ──────────────────────────────────────────────────────

def _map_direct(
    positions: list[LinePosition],
    ocr_lines: list[str],
    x_scale: float,
    y_scale: float,
    page_height_pt: float,
) -> PlacementResult:
    """OCR 줄을 감지 위치에 직접 매핑한다.

    위치가 OCR보다 많으면 최적 서브셋을 선택한다.
    """
    n_pos = len(positions)
    n_ocr = len(ocr_lines)

    if n_pos > n_ocr * 1.5 and n_ocr >= 2:
        selected = _select_best_n(positions, n_ocr)
    else:
        selected = positions

    n_sel = len(selected)
    placed: list[PlacedLine] = []

    for i in range(n_ocr):
        idx = min(int(i * n_sel / n_ocr), n_sel - 1)
        pos = selected[idx]
        placed.append(_pos_to_placed(pos, ocr_lines[i], x_scale, y_scale, page_height_pt))

    return PlacementResult(lines=placed, mode="direct")


def _map_distributed(
    positions: list[LinePosition],
    ocr_lines: list[str],
    x_scale: float,
    y_scale: float,
    page_height_pt: float,
) -> PlacementResult:
    """OCR 줄이 많을 때, 각 위치 내에서 개별 배치한다."""
    n_pos = len(positions)
    n_ocr = len(ocr_lines)

    heights = [max(p.y2 - p.y, 1) for p in positions]
    total_h = sum(heights)

    groups: list[list[int]] = [[] for _ in range(n_pos)]
    ocr_idx = 0

    for pos_idx in range(n_pos):
        proportion = heights[pos_idx] / total_h
        n_assign = max(1, round(proportion * n_ocr))

        remaining_pos = n_pos - pos_idx - 1
        remaining_ocr = n_ocr - ocr_idx
        if remaining_pos > 0:
            n_assign = min(n_assign, remaining_ocr - remaining_pos)
        else:
            n_assign = remaining_ocr
        n_assign = max(0, n_assign)

        for _ in range(n_assign):
            if ocr_idx < n_ocr:
                groups[pos_idx].append(ocr_idx)
                ocr_idx += 1

    placed: list[PlacedLine] = []
    for pos_idx, ocr_indices in enumerate(groups):
        if not ocr_indices:
            continue

        pos = positions[pos_idx]
        x_pdf = pos.x * x_scale
        w_pdf = (pos.x2 - pos.x) * x_scale
        total_h_pdf = (pos.y2 - pos.y) * y_scale
        base_y_pdf = page_height_pt - (pos.y2 * y_scale)

        n_lines = len(ocr_indices)
        sub_h = total_h_pdf / n_lines

        for j, idx in enumerate(ocr_indices):
            placed.append(PlacedLine(
                text=ocr_lines[idx],
                x=x_pdf,
                y=base_y_pdf + j * sub_h,
                width=w_pdf,
                height=sub_h,
            ))

    return PlacementResult(lines=placed, mode="distributed")


def _select_best_n(
    positions: list[LinePosition], n_target: int,
) -> list[LinePosition]:
    """위치 중에서 n_target개의 최적 위치를 선택한다."""
    if len(positions) <= n_target:
        return positions

    scored = []
    for i, pos in enumerate(positions):
        h = pos.y2 - pos.y
        w = pos.x2 - pos.x
        scored.append((h * w, i))

    scored.sort(key=lambda x: x[0], reverse=True)
    n_cand = min(int(n_target * 1.5), len(scored))
    cand_indices = sorted([idx for _, idx in scored[:n_cand]])

    if len(cand_indices) <= n_target:
        return [positions[i] for i in cand_indices]

    selected: list[int] = []
    n_c = len(cand_indices)
    for i in range(n_target):
        c_idx = min(int(i * n_c / n_target), n_c - 1)
        selected.append(cand_indices[c_idx])

    return [positions[i] for i in selected]


def _pos_to_placed(
    pos: LinePosition,
    text: str,
    x_scale: float,
    y_scale: float,
    page_height_pt: float,
) -> PlacedLine:
    """LinePosition을 PlacedLine으로 변환한다."""
    return PlacedLine(
        text=text,
        x=pos.x * x_scale,
        y=page_height_pt - (pos.y2 * y_scale),
        width=(pos.x2 - pos.x) * x_scale,
        height=(pos.y2 - pos.y) * y_scale,
    )


def _distribute_fallback(
    ocr_lines: list[str],
    img_height: int,
    x_scale: float,
    y_scale: float,
    page_width_pt: float,
    page_height_pt: float,
) -> PlacementResult:
    """감지 실패 시 페이지 전체에 균등 분배한다."""
    n = len(ocr_lines)
    top = int(img_height * 0.08)
    bottom = int(img_height * 0.92)
    total_h = bottom - top
    spacing = total_h / max(n, 1)
    line_h = min(spacing * 0.8, 80)

    placed: list[PlacedLine] = []
    for i in range(n):
        y_img = top + i * spacing
        y2_img = y_img + line_h
        placed.append(PlacedLine(
            text=ocr_lines[i],
            x=page_width_pt * 0.05,
            y=page_height_pt - (y2_img * y_scale),
            width=page_width_pt * 0.9,
            height=line_h * y_scale,
        ))

    return PlacementResult(lines=placed, mode="fallback")
