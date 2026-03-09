# 모델 레지스트리 모듈
# 지원하는 MLX 모델 목록과 메모리 프로파일, 권장 구성을 관리한다
# 24GB MacBook 사용자를 위한 메모리 예산 자동 계산을 제공한다
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ModelRole(Enum):
    """모델의 파이프라인 내 역할을 정의한다."""
    OCR_VISION = "ocr_vision"          # 이미지에서 텍스트 추출 (mlx-vlm)
    POST_KOREAN = "post_korean"        # 한국어 OCR 후처리 (mlx-lm)
    POST_REASONING = "post_reasoning"  # 추론 기반 검증 (mlx-lm)


class ModelFramework(Enum):
    """모델이 사용하는 프레임워크를 구분한다."""
    TRANSFORMERS_VLM = "transformers_vlm"  # transformers + torch 비전-언어 모델
    TRANSFORMERS_LM = "transformers_lm"    # transformers + torch 텍스트 전용 모델
    MLX_VLM = "mlx_vlm"  # mlx-vlm 비전-언어 모델 (이미지 입력 지원)
    MLX_LM = "mlx_lm"    # 텍스트 전용 언어 모델


@dataclass(frozen=True)
class ModelSpec:
    """개별 모델의 사양을 정의하는 불변 데이터 컨테이너다."""
    model_id: str                # HuggingFace 모델 ID
    role: ModelRole              # 파이프라인 내 역할
    framework: ModelFramework    # 사용 프레임워크
    quantization: str            # 양자화 수준 (4bit, 8bit, 16bit)
    memory_gb: float             # 추론 시 예상 메모리 (GB, KV 캐시 포함)
    license_name: str            # 라이선스 (Apache-2.0, MIT 등)
    description: str             # 한글 설명


# ── 지원 모델 레지스트리 ─────────────────────────────────────────────────────
# 키: 사용자 친화적 별칭, 값: ModelSpec
SUPPORTED_MODELS: dict[str, ModelSpec] = {
    # --- OCR Vision 모델 (transformers + torch) ---
    "glm-ocr": ModelSpec(
        model_id="zai-org/GLM-OCR",
        role=ModelRole.OCR_VISION,
        framework=ModelFramework.TRANSFORMERS_VLM,
        quantization="bf16",
        memory_gb=8.0,
        license_name="Apache-2.0",
        description="GLM-OCR BF16 — transformers 기반 OCR 비전 모델 (MPS 가속)",
    ),

    # --- OCR Vision 모델 (mlx-vlm) ---
    "qwen3-vl-8b-4bit": ModelSpec(
        model_id="mlx-community/Qwen3-VL-8B-Instruct-4bit",
        role=ModelRole.OCR_VISION,
        framework=ModelFramework.MLX_VLM,
        quantization="4bit",
        memory_gb=7.0,
        license_name="Apache-2.0",
        description="Qwen3 Vision 8B 4비트 — 최신 비전-언어 모델, 한국어 우수",
    ),
    "qwen3-vl-4b-4bit": ModelSpec(
        model_id="mlx-community/Qwen3-VL-4B-Instruct-4bit",
        role=ModelRole.OCR_VISION,
        framework=ModelFramework.MLX_VLM,
        quantization="4bit",
        memory_gb=5.0,
        license_name="Apache-2.0",
        description="Qwen3 Vision 4B 4비트 — 경량 비전 모델, 빠른 처리",
    ),
    "qwen25-vl-7b-4bit": ModelSpec(
        model_id="mlx-community/Qwen2.5-VL-7B-Instruct-4bit",
        role=ModelRole.OCR_VISION,
        framework=ModelFramework.MLX_VLM,
        quantization="4bit",
        memory_gb=7.0,
        license_name="Apache-2.0",
        description="Qwen2.5 Vision 7B 4비트 — 검증된 OCR 성능",
    ),

    # --- 한국어 후처리 모델 (mlx-lm) ---
    "qwen3-8b-4bit": ModelSpec(
        model_id="mlx-community/Qwen3-8B-4bit",
        role=ModelRole.POST_KOREAN,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.5,
        license_name="Apache-2.0",
        description="Qwen3 8B 4비트 — 최신 다국어 모델, 한국어 후처리 최적",
    ),
    "bllossom-8b-4bit": ModelSpec(
        model_id="KYUNGYONG/DeepSeek-llama3.1-Bllossom-8B-Q4-mlx",
        role=ModelRole.POST_KOREAN,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.5,
        license_name="MIT",
        description="Bllossom 8B 4비트 — 한국어 특화 튜닝 모델",
    ),
    "exaone-7.8b-4bit": ModelSpec(
        model_id="mlx-community/EXAONE-3.5-7.8B-Instruct-4bit",
        role=ModelRole.POST_KOREAN,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.0,
        license_name="EXAONE",
        description="EXAONE 7.8B 4비트 — LG AI 한국어 네이티브 모델",
    ),
    "llama31-8b-4bit": ModelSpec(
        model_id="mlx-community/Meta-Llama-3.1-8B-Instruct-4bit",
        role=ModelRole.POST_KOREAN,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.5,
        license_name="Llama-3.1",
        description="Llama 3.1 8B 4비트 — Meta 다국어 모델",
    ),

    # --- 추론 특화 모델 (mlx-lm) ---
    "deepseek-r1-8b-4bit": ModelSpec(
        model_id="mlx-community/DeepSeek-R1-Distill-Llama-8B-4bit",
        role=ModelRole.POST_REASONING,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.5,
        license_name="MIT",
        description="DeepSeek R1 8B 4비트 — 추론·논리 특화, 수식 검증에 적합",
    ),
    "deepseek-r1-qwen-8b-4bit": ModelSpec(
        model_id="mlx-community/DeepSeek-R1-0528-Qwen3-8B-4bit",
        role=ModelRole.POST_REASONING,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.5,
        license_name="MIT",
        description="DeepSeek R1 Qwen3 8B 4비트 — 최신 추론 모델, 한국어 지원",
    ),
    "exaone-deep-7.8b-4bit": ModelSpec(
        model_id="mlx-community/EXAONE-Deep-7.8B-4bit",
        role=ModelRole.POST_REASONING,
        framework=ModelFramework.MLX_LM,
        quantization="4bit",
        memory_gb=6.0,
        license_name="EXAONE",
        description="EXAONE Deep 7.8B 4비트 — 한국어 추론 특화",
    ),
}

# ── 기본 모델 별칭 ────────────────────────────────────────────────────────────
DEFAULT_OCR_MODEL: str = "glm-ocr"
DEFAULT_POST_MODEL: str = "exaone-7.8b-4bit"
DEFAULT_REASONING_MODEL: str = "deepseek-r1-8b-4bit"

# 순차 후처리 모델 목록 — OCR 완료 후 순서대로 적용한다
# 메모리 관리: 각 모델을 로드 → 처리 → 언로드 방식으로 순차 실행한다
# 앙상블 후처리: 3개 모델이 독립적으로 교정한 뒤 투표로 최종 결과를 결정한다
# Qwen3(한국어·영어) → EXAONE(고유명사·문맥) → DeepSeek-R1(수학·코드·표)
DEFAULT_POST_MODELS: list[str] = [
    "qwen3-8b-4bit",          # 1차: 한국어·영어 텍스트 교정
    "exaone-7.8b-4bit",       # 2차: 한국어 고유명사·문맥 검증
    "deepseek-r1-8b-4bit",    # 3차: 수학·코드·표 구조 검증
]


def get_model_spec(alias: str) -> ModelSpec | None:
    """별칭으로 모델 사양을 조회한다. 없으면 None을 반환한다."""
    return SUPPORTED_MODELS.get(alias)


def get_model_spec_by_id(model_id: str) -> ModelSpec | None:
    """HuggingFace 모델 ID로 모델 사양을 조회한다."""
    for spec in SUPPORTED_MODELS.values():
        if spec.model_id == model_id:
            return spec
    return None


def list_models_by_role(role: ModelRole) -> list[ModelSpec]:
    """지정된 역할의 모델 목록을 반환한다."""
    return [spec for spec in SUPPORTED_MODELS.values() if spec.role == role]


def calculate_max_workers(
    total_ram_gb: float,
    ocr_model_gb: float,
    post_model_gb: float = 0.0,
    os_reserved_gb: float = 4.0,
    safety_margin_gb: float = 2.0,
) -> int:
    """사용 가능한 RAM에 따라 최대 워커 수를 계산한다.

    각 워커는 OCR 모델의 독립 인스턴스를 로드한다.
    후처리 모델은 워커와 무관하게 별도 1개만 로드한다.

    Args:
        total_ram_gb: 시스템 총 RAM (GB)
        ocr_model_gb: OCR 모델의 추론 시 메모리 (GB)
        post_model_gb: 후처리 모델의 추론 시 메모리 (GB, 0이면 비활성)
        os_reserved_gb: OS 예약 메모리 (GB)
        safety_margin_gb: 안전 여유 메모리 (GB)

    Returns:
        권장 워커 수 (최소 1)
    """
    available = total_ram_gb - os_reserved_gb - post_model_gb - safety_margin_gb
    if available <= 0:
        return 1
    max_workers = int(available / ocr_model_gb)
    return max(1, min(max_workers, 4))  # 상한 4워커


def get_system_ram_gb() -> float:
    """현재 시스템의 총 RAM을 GB 단위로 반환한다."""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        # psutil 실패 시 보수적으로 24GB 가정
        return 24.0
