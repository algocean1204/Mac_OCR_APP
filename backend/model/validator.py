# 모델 검증 모듈
# 다운로드 완료 마커 파일 존재 여부로 모델의 유효성을 판단한다
from __future__ import annotations

from pathlib import Path


# 다운로드 완료를 표시하는 마커 파일명
_COMPLETE_MARKER: str = ".download_complete"

# 모델 필수 파일 목록 — 이 파일들이 있어야 유효한 모델이다
_REQUIRED_FILES: list[str] = [
    "config.json",
    "tokenizer.json",
]


class ModelValidator:
    """모델 캐시 디렉토리의 무결성을 검증한다."""

    def __init__(self, cache_dir: Path) -> None:
        # 모델 ID별 하위 디렉토리를 관리한다
        self._cache_dir: Path = cache_dir

    def get_model_dir(self, model_id: str) -> Path:
        """모델 ID에 해당하는 로컬 캐시 디렉토리 경로를 반환한다."""
        # HuggingFace 모델 ID의 슬래시를 언더스코어로 변환한다
        safe_name = model_id.replace("/", "--")
        return self._cache_dir / safe_name

    def is_downloaded(self, model_id: str) -> bool:
        """모델이 완전히 다운로드되어 있는지 확인한다.

        마커 파일과 필수 파일의 존재를 함께 확인한다.
        """
        model_dir = self.get_model_dir(model_id)

        # 디렉토리 자체가 없으면 미다운로드 상태다
        if not model_dir.exists():
            return False

        # 완료 마커 파일이 없으면 불완전 다운로드다
        marker_path = model_dir / _COMPLETE_MARKER
        if not marker_path.exists():
            return False

        # 필수 파일들이 실제로 존재하는지 확인한다
        return self._check_required_files(model_dir)

    def _check_required_files(self, model_dir: Path) -> bool:
        """모델 디렉토리에 필수 파일이 존재하는지 확인한다."""
        for filename in _REQUIRED_FILES:
            if not (model_dir / filename).exists():
                return False
        return True

    def mark_complete(self, model_id: str) -> None:
        """다운로드 완료 마커 파일을 생성한다."""
        model_dir = self.get_model_dir(model_id)
        marker_path = model_dir / _COMPLETE_MARKER
        marker_path.touch(exist_ok=True)

    def remove_incomplete(self, model_id: str) -> None:
        """불완전한 다운로드 파일을 삭제하여 재다운로드를 준비한다."""
        import shutil
        model_dir = self.get_model_dir(model_id)
        if model_dir.exists():
            shutil.rmtree(model_dir, ignore_errors=True)
