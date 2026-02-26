# 설정 관리 모듈
# CLI 인자, 환경변수, 기본값을 통합하여 PipelineConfig 데이터클래스를 생성한다
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

from backend.config.model_registry import (
    DEFAULT_OCR_MODEL,
    DEFAULT_POST_MODEL,
    SUPPORTED_MODELS,
    calculate_max_workers,
    get_system_ram_gb,
)


# HuggingFace 모델 식별자 — mlx-community 허브의 8bit 양자화 OCR 비전 모델을 사용한다
# bf16(13.6GB)은 정밀도는 높지만 추론 속도가 ~10배 느려 실용성이 떨어진다
# 8bit(5GB)이 속도/품질 균형에서 최적이다
MODEL_ID: str = "mlx-community/DeepSeek-OCR-2-8bit"

# 모델 캐시 저장 경로 — 프로젝트 루트 기준 backend/AImodels에 보관한다
MODEL_CACHE_DIR: Path = Path(__file__).resolve().parent.parent / "AImodels"

# PDF → 이미지 변환 해상도 (DPI) — 300 DPI는 고품질 OCR 인식을 위한 최적 해상도다
DEFAULT_DPI: int = 300

# 페이지당 최대 생성 토큰 수 — grounding 태그와 좌표 출력을 충분히 담기 위해 16384로 확장한다
MAX_TOKENS: int = 16384

# 이미지 최대 크기 (픽셀) — 너무 큰 이미지는 메모리 문제를 일으킬 수 있으므로 5120으로 제한한다
MAX_IMAGE_SIZE: int = 5120

# 메모리 임계값 (MB 단위)
MEMORY_WARNING_MB: int = 4000   # 경고 수준 — 강제 GC 실행
MEMORY_DANGER_MB: int = 5000    # 위험 수준 — 매 페이지마다 추가 GC
MEMORY_FATAL_MB: int = 8000     # 치명 수준 — 부분 결과 저장 후 종료

# 페이지당 OCR 타임아웃 (초)
OCR_TIMEOUT_SECONDS: int = 120

# 병렬 워커 수 — 각 워커가 독립 모델 인스턴스를 로드한다 (2개 워커로 병렬 처리)
# 후처리 LLM 필수화에 따라 메모리 안정성을 위해 3→2로 변경
NUM_WORKERS: int = 2

# 청크 크기 — 워커가 N페이지씩 묶어 임시 PDF로 저장한다
CHUNK_SIZE: int = 10

# 출력 파일 기본 저장 경로
OUTPUT_DIR: Path = Path.home() / "Downloads"

# 후처리 모델 기본 ID — 한국어 교정을 위한 Qwen3-8B-4bit 모델
POST_PROCESS_MODEL_ID: str = SUPPORTED_MODELS[DEFAULT_POST_MODEL].model_id

# 후처리 활성화 기본값 — OCR 품질 향상을 위해 기본 활성화한다
ENABLE_POST_PROCESS: bool = True

# 후처리 모드 기본값 — "korean" (한국어 교정) 또는 "reasoning" (추론 검증)
POST_PROCESS_MODE: str = "korean"


@dataclass
class PipelineConfig:
    """파이프라인 전체 설정을 담는 불변 데이터 컨테이너다."""

    # 필수 입력 경로
    input_path: str

    # 선택적 설정 — 기본값이 있다
    output_dir: str = field(default_factory=lambda: str(OUTPUT_DIR))
    model_id: str = field(default=MODEL_ID)
    model_cache_dir: str = field(default_factory=lambda: str(MODEL_CACHE_DIR))
    dpi: int = field(default=DEFAULT_DPI)
    memory_warning_mb: int = field(default=MEMORY_WARNING_MB)
    memory_danger_mb: int = field(default=MEMORY_DANGER_MB)
    memory_fatal_mb: int = field(default=MEMORY_FATAL_MB)
    ocr_timeout_seconds: int = field(default=OCR_TIMEOUT_SECONDS)
    # OCR 완료 후 최종 PDF를 분할할 권 수 — 1은 분할 없음(기본값)
    split_parts: int = field(default=1)
    # 병렬 워커 수 — 각 워커가 독립 모델 인스턴스를 로드한다
    num_workers: int = field(default=NUM_WORKERS)
    # 청크 크기 — 워커가 N페이지씩 묶어 임시 PDF로 저장한다
    chunk_size: int = field(default=CHUNK_SIZE)
    # 페이지당 최대 생성 토큰 수 — grounding 태그와 좌표 출력 용량을 결정한다
    max_tokens: int = field(default=MAX_TOKENS)
    # 이미지 최대 크기 (픽셀) — 초과 시 비율 유지하며 축소하여 메모리를 절약한다
    max_image_size: int = field(default=MAX_IMAGE_SIZE)
    # 후처리 LLM 모델 ID — OCR 결과의 한국어 교정에 사용한다
    post_process_model_id: str = field(default=POST_PROCESS_MODEL_ID)
    # 후처리 활성화 여부 — True이면 OCR 후 LLM 교정 단계를 추가한다
    enable_post_process: bool = field(default=ENABLE_POST_PROCESS)
    # 후처리 모드 — "korean" (한국어 교정) 또는 "reasoning" (추론 검증)
    post_process_mode: str = field(default=POST_PROCESS_MODE)

    def resolved_output_dir(self) -> Path:
        """출력 디렉토리를 절대 경로로 반환한다."""
        return Path(self.output_dir).expanduser().resolve()

    def resolved_model_cache_dir(self) -> Path:
        """모델 캐시 디렉토리를 절대 경로로 반환한다."""
        return Path(self.model_cache_dir).expanduser().resolve()

    def resolved_input_path(self) -> Path:
        """입력 PDF 경로를 절대 경로로 반환한다."""
        return Path(self.input_path).expanduser().resolve()


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI 인자 파서를 생성한다."""
    parser = argparse.ArgumentParser(
        description="PDF OCR 변환기 — 검색 가능한 PDF를 생성한다",
        prog="backend.main",
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="PDF_PATH",
        help="변환할 PDF 파일 경로",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        metavar="DIR",
        help=f"출력 PDF 저장 디렉토리 (기본값: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        metavar="DPI",
        help=f"PDF 이미지 변환 해상도 (기본값: {DEFAULT_DPI})",
    )
    parser.add_argument(
        "--model-id",
        default=MODEL_ID,
        metavar="MODEL_ID",
        help=f"HuggingFace 모델 ID (기본값: {MODEL_ID})",
    )
    parser.add_argument(
        "--model-cache-dir",
        default=str(MODEL_CACHE_DIR),
        metavar="DIR",
        help=f"모델 캐시 디렉토리 (기본값: {MODEL_CACHE_DIR})",
    )
    parser.add_argument(
        "--split",
        type=int,
        default=1,
        metavar="N",
        help="OCR 완료 후 출력 PDF를 N권으로 분할한다 (기본값: 1 — 분할 없음)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=NUM_WORKERS,
        metavar="N",
        help=f"병렬 OCR 워커 수 (기본값: {NUM_WORKERS})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        metavar="N",
        help=f"청크당 페이지 수 (기본값: {CHUNK_SIZE})",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=MAX_TOKENS,
        metavar="N",
        help=f"페이지당 최대 생성 토큰 수 (기본값: {MAX_TOKENS})",
    )
    parser.add_argument(
        "--max-image-size",
        type=int,
        default=MAX_IMAGE_SIZE,
        metavar="PX",
        help=f"이미지 최대 크기 픽셀 — 초과 시 축소 (기본값: {MAX_IMAGE_SIZE})",
    )
    parser.add_argument(
        "--post-process",
        action="store_true",
        default=ENABLE_POST_PROCESS,
        help="OCR 후처리 LLM 교정을 활성화한다 (정확도 향상, 속도 감소)",
    )
    parser.add_argument(
        "--post-model",
        default=POST_PROCESS_MODEL_ID,
        metavar="MODEL_ID",
        help=f"후처리 LLM 모델 ID (기본값: {POST_PROCESS_MODEL_ID})",
    )
    parser.add_argument(
        "--post-mode",
        default=POST_PROCESS_MODE,
        choices=["korean", "reasoning"],
        help=f"후처리 모드 — korean 또는 reasoning (기본값: {POST_PROCESS_MODE})",
    )
    return parser


def load_config(argv: list[str] | None = None) -> PipelineConfig:
    """CLI 인자와 환경변수를 읽어 PipelineConfig를 생성하여 반환한다."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # 환경변수로 모델 ID 오버라이드를 허용한다
    model_id = os.environ.get("OCR_MODEL_ID", args.model_id)
    model_cache_dir = os.environ.get("OCR_MODEL_CACHE_DIR", args.model_cache_dir)

    # 후처리 설정
    post_model_id = os.environ.get("OCR_POST_MODEL_ID", args.post_model)
    enable_post = args.post_process or os.environ.get("OCR_POST_PROCESS", "").lower() in ("1", "true")
    post_mode = os.environ.get("OCR_POST_MODE", args.post_mode)

    # 후처리 활성화 시 워커 수를 자동 조절한다
    num_workers = args.workers
    if enable_post:
        from backend.config.model_registry import get_model_spec_by_id
        ocr_spec = get_model_spec_by_id(model_id)
        post_spec = get_model_spec_by_id(post_model_id)
        ocr_mem = ocr_spec.memory_gb if ocr_spec else 5.0
        post_mem = post_spec.memory_gb if post_spec else 6.5
        auto_workers = calculate_max_workers(
            total_ram_gb=get_system_ram_gb(),
            ocr_model_gb=ocr_mem,
            post_model_gb=post_mem,
        )
        # 사용자 지정 워커 수와 자동 계산 값 중 작은 것을 사용한다
        num_workers = min(num_workers, auto_workers)

    return PipelineConfig(
        input_path=args.input,
        output_dir=args.output_dir,
        model_id=model_id,
        model_cache_dir=model_cache_dir,
        dpi=args.dpi,
        split_parts=args.split,
        chunk_size=args.chunk_size,
        max_tokens=args.max_tokens,
        max_image_size=args.max_image_size,
        post_process_model_id=post_model_id,
        enable_post_process=enable_post,
        post_process_mode=post_mode,
        num_workers=num_workers,
    )
