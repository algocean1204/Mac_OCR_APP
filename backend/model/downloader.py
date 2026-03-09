# 모델 다운로드 모듈
# HuggingFace Hub에서 OCR/LLM 모델을 다운로드하고 캐시를 관리한다
from __future__ import annotations

from pathlib import Path

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import ModelError
from backend.model.validator import ModelValidator
from backend.progress.reporter import ProgressReporter


# 최대 다운로드 재시도 횟수
_MAX_RETRIES: int = 3


class ModelDownloader:
    """HuggingFace Hub에서 MLX 모델을 다운로드하고 로컬에 캐시한다."""

    def __init__(
        self,
        cache_dir: Path,
        reporter: ProgressReporter,
    ) -> None:
        self._cache_dir: Path = cache_dir
        self._reporter: ProgressReporter = reporter
        self._validator: ModelValidator = ModelValidator(cache_dir)

    def ensure_downloaded(self, model_id: str) -> Path:
        """모델이 로컬에 없으면 다운로드하고 모델 디렉토리를 반환한다.

        Args:
            model_id: HuggingFace 모델 ID (예: "mlx-community/DeepSeek-OCR-2-8bit")

        Returns:
            로컬 모델 디렉토리 경로

        Raises:
            ModelError: 다운로드 실패 시
        """
        if self._validator.is_downloaded(model_id):
            self._reporter.report_log("info", f"모델 캐시 확인 완료: {model_id}")
            return self._validator.get_model_dir(model_id)

        self._reporter.report_log("info", f"모델 다운로드 시작: {model_id}")
        return self._download_with_retry(model_id)

    def _download_with_retry(self, model_id: str) -> Path:
        """최대 _MAX_RETRIES 회 재시도하며 모델을 다운로드한다."""
        last_error: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                if attempt > 1:
                    self._reporter.report_log(
                        "warn", f"다운로드 재시도 {attempt}/{_MAX_RETRIES}"
                    )
                    # 불완전한 이전 다운로드를 정리한다
                    self._validator.remove_incomplete(model_id)

                return self._download(model_id)

            except Exception as exc:
                last_error = exc
                self._reporter.report_log(
                    "warn", f"다운로드 시도 {attempt} 실패: {exc}"
                )

        # 모든 재시도 실패 — 치명 에러를 발생시킨다
        raise ModelError(
            code=ErrorCodes.MODEL_DOWNLOAD_FAILED,
            detail=f"최대 {_MAX_RETRIES}회 재시도 후 실패: {last_error}",
        ) from last_error

    def _download(self, model_id: str) -> Path:
        """huggingface_hub을 통해 모델을 실제로 다운로드한다."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ModelError(
                code=ErrorCodes.MODEL_INCOMPATIBLE,
                detail="huggingface_hub 패키지가 설치되지 않음",
            ) from exc

        model_dir = self._validator.get_model_dir(model_id)
        model_dir.mkdir(parents=True, exist_ok=True)

        self._reporter.report_download(0, 100, status="downloading")

        try:
            # snapshot_download은 전체 모델 레포지토리를 다운로드한다
            local_dir = snapshot_download(
                repo_id=model_id,
                local_dir=str(model_dir),
                local_dir_use_symlinks=False,
            )
        except Exception as exc:
            raise ModelError(
                code=ErrorCodes.MODEL_DOWNLOAD_FAILED,
                detail=f"snapshot_download 실패: {exc}",
            ) from exc

        self._reporter.report_download(100, 100, status="verifying")

        # 완료 마커 파일을 생성하여 이후 재다운로드를 방지한다
        self._validator.mark_complete(model_id)
        self._reporter.report_log("info", "모델 다운로드 완료")

        return Path(local_dir)
