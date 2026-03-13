# 진행률 보고 모듈
# 아키텍처 문서 4.2절의 stdout NDJSON 프로토콜을 구현한다
# 모든 stdout 출력은 이 모듈을 통해서만 수행해야 한다
from __future__ import annotations

import json
import sys
from datetime import datetime


def _now_iso() -> str:
    """현재 시각을 ISO 8601 형식으로 반환한다."""
    return datetime.now().isoformat(timespec="seconds")


def _emit(payload: dict[str, object]) -> None:
    """딕셔너리를 JSON 한 줄로 stdout에 즉시 출력한다."""
    print(json.dumps(payload, ensure_ascii=False), flush=True)


class ProgressReporter:
    """파이프라인 각 단계의 진행률을 stdout에 NDJSON 형식으로 보고한다."""

    @staticmethod
    def report_init(model_name: str, total_pages: int, model_loaded: bool = True) -> None:
        """모델 로드 완료 및 초기화 정보를 출력한다."""
        _emit({
            "type": "init",
            "model_name": model_name,
            "model_loaded": model_loaded,
            "total_pages": total_pages,
            "timestamp": _now_iso(),
        })

    @staticmethod
    def report_progress(
        current: int,
        total: int,
        status: str,
        memory_mb: int = 0,
        num_workers: int = 0,
        worker_progress: list[dict[str, int]] | None = None,
        model_name: str | None = None,
    ) -> None:
        """현재 페이지 처리 진행률을 출력한다.

        Args:
            current: 완료된 페이지 수 (1-based)
            total: 전체 페이지 수
            status: 현재 처리 단계 식별자
            memory_mb: 현재 메모리 사용량 (MB)
            num_workers: 활성 워커 총 수 (0이면 미포함)
            worker_progress: 워커별 진행 상태 목록 [{worker_id, completed, total}]
                             None이면 미포함 — 역호환성 유지
            model_name: 현재 활성 모델 이름 (Phase 2 후처리 시 사용)
        """
        percent: float = round(current / total * 100, 2) if total > 0 else 0.0

        # 기본 진행률 페이로드 구성
        payload: dict[str, object] = {
            "type": "progress",
            "current_page": current,
            "total_pages": total,
            "percent": percent,
            "status": status,
            "memory_mb": memory_mb,
            "timestamp": _now_iso(),
        }

        # 워커별 진행 정보가 제공된 경우에만 페이로드에 포함 (선택적 필드)
        if num_workers > 0:
            payload["num_workers"] = num_workers
        if worker_progress is not None:
            payload["worker_progress"] = worker_progress  # type: ignore[assignment]
        # 활성 모델 이름이 제공된 경우에만 페이로드에 포함한다
        if model_name is not None:
            payload["model_name"] = model_name

        _emit(payload)

    @staticmethod
    def report_download(
        downloaded_mb: float,
        total_mb: float,
        status: str = "downloading",
    ) -> None:
        """모델 다운로드 진행률을 출력한다."""
        percent: float = round(downloaded_mb / total_mb * 100, 1) if total_mb > 0 else 0.0
        _emit({
            "type": "download",
            "downloaded_mb": round(downloaded_mb),
            "total_mb": round(total_mb),
            "percent": percent,
            "status": status,
            "timestamp": _now_iso(),
        })

    @staticmethod
    def report_complete(
        output_path: str,
        total_pages: int,
        elapsed_seconds: float,
    ) -> None:
        """전체 처리 완료 메시지를 출력한다."""
        _emit({
            "type": "complete",
            "output_path": output_path,
            "total_pages": total_pages,
            "elapsed_seconds": round(elapsed_seconds, 1),
            "timestamp": _now_iso(),
        })

    @staticmethod
    def report_split_progress(
        current_part: int,
        total_parts: int,
        start_page: int,
        end_page: int,
    ) -> None:
        """PDF 분할 진행률을 출력한다.

        Args:
            current_part: 현재까지 완료된 권 번호 (1-based)
            total_parts: 전체 분할 권 수
            start_page: 현재 권의 시작 페이지 (1-based)
            end_page: 현재 권의 끝 페이지 (1-based)
        """
        _emit({
            "type": "split_progress",
            "current_part": current_part,
            "total_parts": total_parts,
            "start_page": start_page,
            "end_page": end_page,
            "timestamp": _now_iso(),
        })

    @staticmethod
    def report_split_complete(part_paths: list[str]) -> None:
        """PDF 분할 완료 메시지를 출력한다.

        Args:
            part_paths: 생성된 분할 파일 경로 목록 (문자열)
        """
        _emit({
            "type": "split_complete",
            "parts": part_paths,
            "total_parts": len(part_paths),
            "timestamp": _now_iso(),
        })

    @staticmethod
    def report_log(level: str, message: str) -> None:
        """디버깅용 로그 메시지를 출력한다.

        Args:
            level: 로그 레벨 ("debug", "info", "warn")
            message: 로그 메시지 (한국어)
        """
        _emit({
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": _now_iso(),
        })
