# 파이프라인 컨트롤러 모듈
# 병렬 청크 기반 OCR 파이프라인을 총괄 제어한다
# 3개의 워커 프로세스가 각각 독립 모델을 로드하고 페이지를 나누어 처리한다
from __future__ import annotations

import multiprocessing
import queue as queue_module
import shutil
import threading
import time
import uuid
from pathlib import Path

from backend.config.settings import PipelineConfig
from backend.errors.handler import ErrorHandler
from backend.model.downloader import ModelDownloader
from backend.pdf.splitter import split_pdf
from backend.pipeline.chunk_worker import run_worker
from backend.pipeline.merger import merge_chunks
from backend.progress.reporter import ProgressReporter
from backend.utils.file_utils import generate_output_path, validate_pdf_file


class PipelineController:
    """병렬 청크 기반 PDF OCR 변환 파이프라인을 총괄 제어하는 오케스트레이터다.

    아키텍처:
    1. 메인 프로세스: PDF 검증, 모델 다운로드, 워커 생성, 진행률 집계
    2. 워커 프로세스: 각각 독립 모델 인스턴스로 OCR 수행, 청크 PDF 저장
    3. 메인 프로세스: 청크 병합 → 최종 PDF → 분할 (선택)
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config: PipelineConfig = config
        self._reporter: ProgressReporter = ProgressReporter()
        self._error_handler: ErrorHandler = ErrorHandler()
        # 취소 플래그 — stdin 모니터링 스레드와 공유한다
        self._cancelled: bool = False

    def run(self) -> None:
        """파이프라인 전체를 실행한다. 완료 또는 에러 시 반환한다."""
        start_time = time.monotonic()

        # 1단계: 입력 파일 검증 + 출력 경로 결정
        pdf_path = validate_pdf_file(self._config.input_path)
        output_dir = self._config.resolved_output_dir()
        output_path = generate_output_path(pdf_path, output_dir)

        # 2단계: 모델 다운로드 (필요 시)
        model_dir = self._ensure_model_ready()

        # 2-b단계: 후처리 모델 다운로드 (활성화 시)
        post_model_dir = self._ensure_post_model_ready()

        # 3단계: 총 페이지 수 확인
        total_pages = self._count_pages(pdf_path)

        # 4단계: 초기화 보고 — Flutter에게 총 페이지 수를 알린다
        self._reporter.report_init(
            model_name=self._config.model_id,
            total_pages=total_pages,
        )

        # 5단계: 취소 명령 수신 스레드 시작
        self._start_cancel_listener()

        # 6단계: 임시 디렉토리 생성
        temp_dir = self._create_temp_dir()

        try:
            # 7단계: 워커별 페이지 할당 계산
            assignments = self._calculate_assignments(total_pages)

            # 8단계: 병렬 OCR 처리
            self._run_parallel(
                pdf_path=pdf_path,
                model_dir=model_dir,
                assignments=assignments,
                temp_dir=temp_dir,
                total_pages=total_pages,
                post_model_dir=post_model_dir,
            )

            # 9단계: 청크 병합 → 최종 PDF
            self._reporter.report_log("info", "청크 병합 시작")
            actual_pages = merge_chunks(temp_dir, output_path)
            self._reporter.report_log(
                "info", f"청크 병합 완료 — {actual_pages}페이지"
            )

            # 10단계: 완료 보고
            elapsed = time.monotonic() - start_time
            self._reporter.report_complete(
                output_path=str(output_path),
                total_pages=actual_pages,
                elapsed_seconds=elapsed,
            )

            # 11단계: PDF 분할 (split_parts > 1인 경우에만)
            if self._config.split_parts > 1:
                self._run_split(output_path)

        finally:
            # 임시 디렉토리 정리
            self._cleanup_temp(temp_dir)

    def _ensure_model_ready(self) -> Path:
        """모델이 로컬에 없으면 다운로드하고 모델 디렉토리를 반환한다."""
        cache_dir = self._config.resolved_model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        downloader = ModelDownloader(
            cache_dir=cache_dir,
            reporter=self._reporter,
        )
        return downloader.ensure_downloaded(self._config.model_id)

    def _ensure_post_model_ready(self) -> Path | None:
        """후처리 모델이 로컬에 없으면 다운로드하고 모델 디렉토리를 반환한다.

        후처리가 비활성화되어 있으면 None을 반환한다.
        """
        if not self._config.enable_post_process:
            return None

        cache_dir = self._config.resolved_model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        downloader = ModelDownloader(
            cache_dir=cache_dir,
            reporter=self._reporter,
        )
        self._reporter.report_log(
            "info", f"후처리 모델 준비: {self._config.post_process_model_id}"
        )
        return downloader.ensure_downloaded(self._config.post_process_model_id)

    def _count_pages(self, pdf_path: Path) -> int:
        """PDF의 총 페이지 수를 반환한다."""
        import fitz

        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count

    def _calculate_assignments(self, total_pages: int) -> list[list[int]]:
        """각 워커에 할당할 페이지 번호 목록을 계산한다.

        총 페이지를 워커 수로 균등 분배한다.
        페이지가 너무 적으면 워커 수를 자동으로 줄인다.
        """
        # 활성 워커 수를 동적으로 결정한다
        # chunk_size * num_workers 페이지 미만이면 사용 가능한 워커 수를 줄여
        # 지나치게 작은 청크가 생기는 상황을 방지한다 (graceful degradation)
        num_workers = self._config.num_workers
        min_pages_for_multi = self._config.chunk_size * num_workers
        if total_pages < min_pages_for_multi:
            # 최소 1 워커는 유지하며, chunk_size 기준으로 적정 워커 수를 역산한다
            num_workers = max(1, total_pages // self._config.chunk_size)
        num_workers = min(num_workers, total_pages)

        # 균등 분배: 페이지를 num_workers 개로 나누어 각 워커에 할당한다
        pages_per_worker = total_pages // num_workers
        assignments: list[list[int]] = []

        for i in range(num_workers):
            start = i * pages_per_worker
            end = (i + 1) * pages_per_worker if i < num_workers - 1 else total_pages
            assignments.append(list(range(start, end)))

        return assignments

    def _create_temp_dir(self) -> Path:
        """청크 PDF를 저장할 임시 디렉토리를 생성한다."""
        temp_base = Path(__file__).resolve().parent.parent / ".tmp_ocr"
        temp_dir = temp_base / uuid.uuid4().hex[:8]
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _cleanup_temp(self, temp_dir: Path) -> None:
        """임시 디렉토리를 삭제한다."""
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            # 부모 .tmp_ocr 디렉토리가 비어있으면 삭제
            parent = temp_dir.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass

    def _run_parallel(
        self,
        pdf_path: Path,
        model_dir: Path,
        assignments: list[list[int]],
        temp_dir: Path,
        total_pages: int,
        post_model_dir: Path | None = None,
    ) -> None:
        """워커 프로세스를 생성하고 진행률을 집계한다."""
        # macOS에서 MLX/Metal 호환을 위해 spawn 컨텍스트를 사용한다
        ctx = multiprocessing.get_context("spawn")
        progress_queue: multiprocessing.Queue = ctx.Queue()

        # 워커 프로세스 생성 및 시작
        workers: list[multiprocessing.Process] = []
        for worker_id, pages in enumerate(assignments):
            if not pages:
                continue

            p = ctx.Process(
                target=run_worker,
                kwargs={
                    "worker_id": worker_id,
                    "model_id": self._config.model_id,
                    "model_dir": str(model_dir),
                    "pdf_path": str(pdf_path),
                    "page_numbers": pages,
                    "chunk_size": self._config.chunk_size,
                    "dpi": self._config.dpi,
                    "ocr_timeout": self._config.ocr_timeout_seconds,
                    "temp_dir": str(temp_dir),
                    "progress_queue": progress_queue,
                    # 설정에서 중앙화된 토큰/이미지 파라미터를 워커에 주입한다
                    "max_tokens": self._config.max_tokens,
                    "max_image_size": self._config.max_image_size,
                    "post_model_id": self._config.post_process_model_id,
                    "post_model_dir": str(post_model_dir) if post_model_dir else "",
                    "enable_post_process": self._config.enable_post_process,
                    "post_process_mode": self._config.post_process_mode,
                },
                name=f"ocr-worker-{worker_id}",
            )
            p.start()
            workers.append(p)

        self._reporter.report_log(
            "info", f"{len(workers)}개 워커 프로세스 시작"
        )

        # 진행률 수집 + Flutter 보고 — assignments를 전달하여 워커별 총 페이지 수를 추적한다
        self._listen_progress(progress_queue, workers, total_pages, assignments)

        # 워커 종료 대기
        for w in workers:
            w.join(timeout=30)
            if w.is_alive():
                w.terminate()

    def _listen_progress(
        self,
        progress_queue: multiprocessing.Queue,
        workers: list[multiprocessing.Process],
        total_pages: int,
        assignments: list[list[int]],
    ) -> None:
        """Queue에서 워커 메시지를 수집하고 Flutter에 진행률을 보고한다.

        Args:
            progress_queue: 워커 프로세스들이 메시지를 전송하는 큐
            workers: 생성된 워커 프로세스 목록
            total_pages: 전체 처리 대상 페이지 수
            assignments: 워커별 할당 페이지 목록 — 워커별 총 페이지 수 초기화에 사용
        """
        completed: int = 0
        workers_done: int = 0
        num_workers: int = len(workers)

        # 워커별 완료 페이지 수 추적 딕셔너리 — {worker_id: 완료된 페이지 수}
        worker_completed: dict[int, int] = {}

        # assignments에서 워커별 총 페이지 수를 미리 초기화한다
        # assignments 인덱스가 worker_id에 대응한다
        worker_totals: dict[int, int] = {
            wid: len(pages)
            for wid, pages in enumerate(assignments)
            if pages  # 빈 할당은 제외한다
        }

        while workers_done < num_workers:
            # 취소 요청 처리
            if self._cancelled:
                for w in workers:
                    if w.is_alive():
                        w.terminate()
                self._reporter.report_log("info", "취소 요청 — 워커 종료")
                break

            try:
                msg = progress_queue.get(timeout=5)
            except queue_module.Empty:
                # 워커가 살아있는지 확인
                alive = sum(1 for w in workers if w.is_alive())
                if alive == 0 and workers_done < num_workers:
                    self._reporter.report_log(
                        "warn", "일부 워커가 비정상 종료됨"
                    )
                    break
                continue

            msg_type = msg.get("type")

            if msg_type == "page_done":
                completed += 1

                # 해당 메시지를 보낸 워커의 완료 카운트 갱신
                wid: int = msg.get("worker_id", 0)
                worker_completed[wid] = worker_completed.get(wid, 0) + 1

                # 워커별 진행 상태 목록 구성 — worker_id 오름차순으로 정렬한다
                wp: list[dict[str, int]] = [
                    {
                        "worker_id": wid_k,
                        "completed": c,
                        "total": worker_totals.get(wid_k, 0),
                    }
                    for wid_k, c in sorted(worker_completed.items())
                ]

                self._reporter.report_progress(
                    completed,
                    total_pages,
                    "ocr_processing",
                    0,
                    num_workers=num_workers,
                    worker_progress=wp,
                )

            elif msg_type == "page_error":
                page_display = msg.get("page_num", -1) + 1
                self._reporter.report_log(
                    "warn",
                    f"페이지 {page_display} 오류: {msg.get('error', '')}",
                )

            elif msg_type == "worker_ready":
                self._reporter.report_log(
                    "info",
                    f"워커 {msg['worker_id']} 모델 로드 완료",
                )

            elif msg_type == "worker_done":
                workers_done += 1
                self._reporter.report_log(
                    "info",
                    f"워커 {msg['worker_id']} 처리 완료"
                    f" ({workers_done}/{num_workers})",
                )

            elif msg_type == "worker_error":
                self._reporter.report_log(
                    "warn",
                    f"워커 {msg['worker_id']} 오류: {msg.get('error', '')}",
                )
                workers_done += 1

            elif msg_type == "log":
                self._reporter.report_log(
                    msg.get("level", "info"),
                    f"[워커{msg['worker_id']}] {msg.get('message', '')}",
                )

    def _run_split(self, output_path: Path) -> None:
        """OCR 완료된 PDF를 설정된 권 수로 분할한다.

        분할 실패 시 경고 로그를 출력하고 빈 split_complete를 전송하여
        Flutter가 마스터 PDF를 최종 결과로 사용하도록 한다.
        """
        try:
            split_pdf(
                source_path=output_path,
                num_parts=self._config.split_parts,
                reporter=self._reporter,
                chunk_size=self._config.chunk_size,
            )
        except Exception as exc:
            self._reporter.report_log(
                "warn",
                f"PDF 분할 실패 — 마스터 PDF를 사용합니다: {exc}",
            )
            self._reporter.report_split_complete([])

    def _start_cancel_listener(self) -> None:
        """stdin을 비동기로 모니터링하여 CANCEL 명령을 처리하는 스레드를 시작한다."""
        thread = threading.Thread(
            target=self._listen_for_cancel,
            daemon=True,
            name="cancel-listener",
        )
        thread.start()

    def _listen_for_cancel(self) -> None:
        """stdin에서 CANCEL 명령을 대기한다."""
        import sys

        try:
            for line in sys.stdin:
                if line.strip() == "CANCEL":
                    self._cancelled = True
                    self._reporter.report_log("info", "취소 명령 수신됨")
                    break
        except Exception:
            pass
