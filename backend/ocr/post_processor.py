# OCR 후처리 엔진 모듈
# mlx-lm 텍스트 모델을 로드하여 OCR 출력의 한국어 교정 및 추론 검증을 수행한다
# OcrEngine(비전 모델)과 분리된 독립 모듈로, 선택적으로 활성화한다
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from backend.ocr.atoms.build_refine_prompt import (
    build_korean_refine_prompt,
    build_reasoning_verify_prompt,
    should_refine,
)
from backend.ocr.atoms.chunk_text import chunk_text_for_refinement
from backend.ocr.atoms.parse_refined_text import parse_refined_output
from backend.ocr.grounding_parser import OcrBlock


# 후처리 LLM의 최대 생성 토큰 수 — 입력 텍스트와 비슷한 길이의 교정 결과를 기대한다
_POST_MAX_TOKENS: int = 4096

# 후처리 생성 온도 — 낮을수록 결정론적 출력 (교정 목적이므로 낮게 설정)
_POST_TEMPERATURE: float = 0.1

# 후처리 Top-P — 다양성을 최소화하여 원본에 가까운 출력을 유도한다
_POST_TOP_P: float = 0.9


class PostProcessor:
    """mlx-lm 텍스트 모델을 사용하여 OCR 출력을 후처리하는 엔진이다.

    OcrEngine(비전 모델)과 별도로 동작하며, OCR 추출 이후에
    텍스트 품질을 개선하는 역할만 담당한다.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._is_loaded: bool = False
        self._model_id: str = ""

    def load_model(self, model_id: str, model_dir: Path | None = None) -> None:
        """mlx-lm 텍스트 모델과 토크나이저를 메모리에 로드한다.

        Args:
            model_id: HuggingFace 모델 ID 또는 로컬 경로
            model_dir: 로컬 캐시 디렉토리 (None이면 model_id를 직접 사용)

        Raises:
            RuntimeError: 모델 로드 실패 시
        """
        try:
            from mlx_lm import load as mlx_lm_load
        except ImportError as exc:
            raise RuntimeError(
                "mlx-lm 패키지가 설치되지 않음 — pip install mlx-lm"
            ) from exc

        load_path = str(model_dir) if model_dir and model_dir.exists() else model_id

        try:
            self._model, self._tokenizer = mlx_lm_load(load_path)
            self._is_loaded = True
            self._model_id = model_id
        except Exception as exc:
            raise RuntimeError(f"후처리 모델 로드 실패: {exc}") from exc

    def refine_blocks(
        self,
        blocks: list[OcrBlock],
        mode: str = "korean",
    ) -> list[OcrBlock]:
        """OcrBlock 목록의 각 텍스트에 후처리를 적용한다.

        각 블록의 텍스트만 교정하고, bbox_norm, block_type, truncated 등
        다른 속성은 변경하지 않는다.

        Args:
            blocks: OCR 파싱된 블록 목록
            mode: 후처리 모드 — "korean" 또는 "reasoning"

        Returns:
            텍스트가 교정된 새 OcrBlock 목록
        """
        if not self._is_loaded or not blocks:
            return blocks

        # 전체 페이지 텍스트를 합쳐서 한 번에 교정한다 (블록별 호출보다 효율적)
        full_text = "\n".join(block.text for block in blocks)

        if not should_refine(full_text):
            return blocks

        refined_full = self._generate_refinement(full_text, mode)

        # 교정된 전체 텍스트를 다시 블록별로 분배한다
        return _redistribute_text_to_blocks(blocks, refined_full)

    def refine_text(self, text: str, mode: str = "korean") -> str:
        """단일 텍스트 문자열에 후처리를 적용한다.

        plain text 폴백 결과에 사용한다.

        Args:
            text: OCR로 추출된 텍스트
            mode: 후처리 모드 — "korean" 또는 "reasoning"

        Returns:
            교정된 텍스트, 실패 시 원본
        """
        if not self._is_loaded or not should_refine(text):
            return text

        return self._generate_refinement(text, mode)

    def _generate_refinement(self, text: str, mode: str) -> str:
        """LLM을 호출하여 텍스트 교정을 수행한다.

        텍스트가 긴 경우 chunk_text_for_refinement로 청크 분할 후
        각 청크를 개별 LLM 호출로 교정하고 결과를 합산한다.
        청크 분할로 인해 max_chars 초과 시 잘림 없이 전체 텍스트를 교정할 수 있다.

        Args:
            text: 교정 대상 텍스트
            mode: "korean" 또는 "reasoning"

        Returns:
            교정된 텍스트, 오류 시 원본
        """
        try:
            from mlx_lm import generate as mlx_lm_generate
        except ImportError:
            return text

        # 텍스트를 청크로 분할한다 — 짧으면 단일 청크로 처리된다
        chunks = chunk_text_for_refinement(text)
        if not chunks:
            return text

        refined_chunks: list[str] = []
        for chunk in chunks:
            refined_chunk = self._refine_single_chunk(chunk, mode, mlx_lm_generate)
            refined_chunks.append(refined_chunk)

        # 청크 결과를 줄바꿈으로 합산한다
        return "\n".join(refined_chunks) if len(refined_chunks) > 1 else refined_chunks[0]

    def _refine_single_chunk(
        self,
        chunk: str,
        mode: str,
        mlx_lm_generate: object,
    ) -> str:
        """단일 청크에 대해 LLM 교정을 수행한다.

        프롬프트 생성 → LLM 추론 → 출력 파싱의 3단계를 조합한다.

        Args:
            chunk: 교정 대상 텍스트 청크
            mode: "korean" 또는 "reasoning"
            mlx_lm_generate: mlx_lm.generate 함수 객체

        Returns:
            교정된 청크 텍스트, 오류 시 원본 청크
        """
        # 프롬프트 빌드 (Atomic Module 호출)
        if mode == "reasoning":
            prompt = build_reasoning_verify_prompt(chunk)
        else:
            prompt = build_korean_refine_prompt(chunk)

        try:
            # mlx-lm generate 호출
            raw_output: str = mlx_lm_generate(  # type: ignore[operator]
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=_POST_MAX_TOKENS,
                temp=_POST_TEMPERATURE,
                top_p=_POST_TOP_P,
                verbose=False,
            )

            # 출력 파싱 (Atomic Module 호출)
            return parse_refined_output(raw_output, chunk)

        except Exception:
            # 추론 실패 — 원본 청크를 그대로 반환
            return chunk

    def unload(self) -> None:
        """로드된 모델을 메모리에서 해제한다."""
        self._model = None
        self._tokenizer = None
        self._is_loaded = False
        self._model_id = ""

        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except (ImportError, AttributeError):
            pass

    def is_loaded(self) -> bool:
        """모델이 로드되어 있는지 여부를 반환한다."""
        return self._is_loaded

    @property
    def model_id(self) -> str:
        """현재 로드된 모델의 ID를 반환한다."""
        return self._model_id


def _redistribute_text_to_blocks(
    original_blocks: list[OcrBlock],
    refined_full_text: str,
) -> list[OcrBlock]:
    """교정된 전체 텍스트를 원본 블록 구조에 맞춰 재분배한다.

    교정된 텍스트의 줄 수가 원본과 같으면 1:1 매핑하고,
    다르면 원본 블록의 줄 수 비율에 따라 분배한다.
    분배에 실패하면 원본 블록을 그대로 반환한다.

    Args:
        original_blocks: 원본 OcrBlock 목록
        refined_full_text: 교정된 전체 텍스트 (\n 구분)

    Returns:
        텍스트가 교정된 새 OcrBlock 목록
    """
    if not original_blocks or not refined_full_text.strip():
        return original_blocks

    original_lines = []
    block_line_counts = []
    for block in original_blocks:
        lines = block.text.split("\n")
        original_lines.extend(lines)
        block_line_counts.append(len(lines))

    refined_lines = refined_full_text.split("\n")

    # 줄 수가 같으면 직접 매핑한다
    if len(refined_lines) == len(original_lines):
        new_blocks: list[OcrBlock] = []
        line_idx = 0
        for i, block in enumerate(original_blocks):
            count = block_line_counts[i]
            new_text = "\n".join(refined_lines[line_idx:line_idx + count])
            new_blocks.append(OcrBlock(
                text=new_text,
                block_type=block.block_type,
                bbox_norm=block.bbox_norm,
                truncated=block.truncated,
            ))
            line_idx += count
        return new_blocks

    # 줄 수가 다르면 비율 기반 분배를 시도한다
    total_original = len(original_lines)
    total_refined = len(refined_lines)

    if total_original == 0:
        return original_blocks

    new_blocks = []
    refined_idx = 0
    for i, block in enumerate(original_blocks):
        # 원본 블록의 줄 수 비율만큼 교정 텍스트를 할당한다
        ratio = block_line_counts[i] / total_original
        alloc = max(1, round(total_refined * ratio))

        # 마지막 블록은 나머지 줄을 모두 할당한다
        if i == len(original_blocks) - 1:
            alloc = total_refined - refined_idx

        new_text = "\n".join(refined_lines[refined_idx:refined_idx + alloc])
        new_blocks.append(OcrBlock(
            text=new_text,
            block_type=block.block_type,
            bbox_norm=block.bbox_norm,
            truncated=block.truncated,
        ))
        refined_idx += alloc

    return new_blocks
