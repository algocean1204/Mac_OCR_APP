# 메모리 관리 모듈
# 아키텍처 문서 9절의 메모리 관리 전략을 구현한다
# 페이지별 GC 강제 실행과 MLX Metal 캐시 해제를 담당한다
from __future__ import annotations

import gc
import os
from typing import Any

import psutil

from backend.errors.codes import ErrorCodes
from backend.errors.exceptions import MemoryLimitError


def get_memory_mb() -> float:
    """현재 프로세스의 메모리 사용량을 MB 단위로 반환한다."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def _clear_mlx_cache() -> None:
    """MLX GPU 캐시를 명시적으로 해제한다.

    MLX가 설치되지 않은 환경에서는 조용히 건너뛴다.
    mlx 0.30+ 에서는 mx.clear_cache()를 사용한다.
    """
    try:
        import mlx.core as mx
        # mlx 0.30+ API — 구버전 mx.metal.clear_cache()는 deprecated되었다
        mx.clear_cache()
    except (ImportError, AttributeError):
        # MLX 미설치 또는 미지원 환경에서는 건너뛴다
        pass


def force_gc() -> None:
    """가비지 컬렉션과 MLX 캐시 정리를 강제로 실행한다."""
    gc.collect()
    _clear_mlx_cache()


class MemoryManager:
    """메모리 사용량을 추적하고 임계값에 따라 경고 및 종료를 관리한다."""

    def __init__(
        self,
        warning_mb: int = 4000,
        danger_mb: int = 5000,
        fatal_mb: int = 8000,
    ) -> None:
        # 각 임계값은 아키텍처 문서 9.3절의 기준을 따른다
        self._warning_mb: int = warning_mb
        self._danger_mb: int = danger_mb
        self._fatal_mb: int = fatal_mb
        self._danger_page_counter: int = 0

    def cleanup_page_memory(self, *objects: Any) -> None:
        """페이지 처리 후 전달된 객체들의 메모리를 명시적으로 해제한다.

        PIL Image는 close()를 호출하여 버퍼를 즉시 반환한다.
        """
        for obj in objects:
            if obj is None:
                continue
            # PIL Image는 close()로 내부 버퍼를 명시적으로 해제한다
            if hasattr(obj, "close"):
                try:
                    obj.close()
                except Exception:
                    pass
            del obj

        # 가비지 컬렉션과 MLX 캐시를 즉시 실행한다
        force_gc()

    def check_and_act(self, error_handler: Any | None = None) -> str:
        """현재 메모리 수준을 확인하고 적절한 조치를 취한다.

        Returns:
            "OK" | "WARNING" | "DANGER" | "FATAL"

        Raises:
            MemoryLimitError: 메모리가 치명 수준을 초과한 경우
        """
        current_mb: float = get_memory_mb()

        if current_mb >= self._fatal_mb:
            # 치명 수준 — 처리를 즉시 중단해야 한다
            raise MemoryLimitError(
                code=ErrorCodes.MEMORY_FATAL,
                detail=f"현재 {current_mb:.0f}MB / 치명 임계값 {self._fatal_mb}MB",
            )

        if current_mb >= self._danger_mb:
            # 위험 수준 — 매 3페이지마다 추가 GC를 수행한다
            self._danger_page_counter += 1
            if self._danger_page_counter % 3 == 0:
                force_gc()
                force_gc()
            if error_handler is not None:
                error_handler.handle_memory_warning(current_mb, self._danger_mb)
            return "DANGER"

        if current_mb >= self._warning_mb:
            # 경고 수준 — 강제 GC를 2회 실행한다
            force_gc()
            force_gc()
            if error_handler is not None:
                error_handler.handle_memory_warning(current_mb, self._warning_mb)
            return "WARNING"

        return "OK"

    def current_mb(self) -> int:
        """현재 메모리 사용량을 정수 MB로 반환한다."""
        return int(get_memory_mb())
