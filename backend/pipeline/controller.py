# 파이프라인 컨트롤러 모듈
# 병렬 OCR → 앙상블 후처리 → PDF 생성 파이프라인을 총괄 제어한다
#
# 3단계 순차 파이프라인:
#   Phase 1: 병렬 워커가 OCR + 도메인 보정을 수행하고 텍스트 결과를 JSON으로 저장한다
#   Phase 2: 3개 후처리 모델이 독립적으로 교정 → 앙상블 투표로 최종 결과 결정
#   Phase 3: 교정된 텍스트 + 원본 이미지로 최종 PDF를 생성한다
#
# 앙상블 투표: Qwen3(한국어·영어) + EXAONE(고유명사) + DeepSeek-R1(수학·코드) → 다수결
# 메모리 관리: 각 모델을 순차 로드/교정/언로드하여 동시 메모리 점유를 방지한다.
from __future__ import annotations

import json
import multiprocessing
import queue as queue_module
import shutil
import threading
import time
import uuid
from pathlib import Path

from backend.config.model_registry import SUPPORTED_MODELS
from backend.config.settings import PipelineConfig
from backend.errors.handler import ErrorHandler
from backend.model.downloader import ModelDownloader
from backend.ocr.post_processor import PostProcessor
from backend.pdf.splitter import split_pdf
from backend.pipeline.chunk_worker import run_worker
from backend.progress.reporter import ProgressReporter
from backend.utils.file_utils import generate_output_path, validate_pdf_file


class PipelineController:
    """병렬 OCR → 앙상블 후처리 → PDF 생성 파이프라인 오케스트레이터다.

    아키텍처:
    1. Phase 1 (OCR): 병렬 워커가 GLM-OCR로 텍스트를 추출한다
    2. Phase 2 (앙상블 후처리): 3개 모델이 독립 교정 → 투표로 최종 결정
    3. Phase 3 (PDF): 교정된 텍스트 + 원본 이미지로 PDF를 생성한다
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config: PipelineConfig = config
        self._reporter: ProgressReporter = ProgressReporter()
        self._error_handler: ErrorHandler = ErrorHandler()
        self._cancelled: bool = False

    def run(self) -> None:
        """파이프라인 전체를 실행한다."""
        start_time = time.monotonic()

        # 1단계: 입력 파일 검증 + 출력 경로 결정
        pdf_path = validate_pdf_file(self._config.input_path)
        output_dir = self._config.resolved_output_dir()
        output_path = generate_output_path(pdf_path, output_dir)

        # 2단계: OCR 모델 다운로드 (필요 시)
        model_dir = self._ensure_model_ready()

        # 2-b단계: 후처리 모델들 다운로드 (활성화 시)
        post_model_dirs = self._ensure_post_models_ready()

        # 3단계: 총 페이지 수 확인
        total_pages = self._count_pages(pdf_path)

        # 4단계: 초기화 보고
        self._reporter.report_init(
            model_name=self._config.model_id,
            total_pages=total_pages,
        )

        # 5단계: 취소 명령 수신 스레드 시작
        self._start_cancel_listener()

        # 6단계: 임시 디렉토리 생성
        temp_dir = self._create_temp_dir()

        try:
            # === Phase 1: 병렬 OCR ===
            assignments = self._calculate_assignments(total_pages)
            self._run_parallel_ocr(
                pdf_path=pdf_path,
                model_dir=model_dir,
                assignments=assignments,
                temp_dir=temp_dir,
                total_pages=total_pages,
            )

            # OCR 결과 수집 — 워커들이 저장한 JSON에서 텍스트와 블록 결과를 읽는다
            page_texts, page_block_results = self._collect_ocr_results(
                temp_dir, total_pages
            )

            # === Phase 2: 순차 후처리 ===
            if self._config.enable_post_process and post_model_dirs:
                page_texts = self._run_sequential_post_processing(
                    page_texts, post_model_dirs
                )

            # === Phase 3: PDF 생성 ===
            self._reporter.report_log("info", "PDF 생성 시작")
            self._generate_final_pdf(
                pdf_path=pdf_path,
                page_texts=page_texts,
                output_path=output_path,
                total_pages=total_pages,
                page_block_results=page_block_results,
            )

            # 완료 보고
            elapsed = time.monotonic() - start_time
            self._reporter.report_complete(
                output_path=str(output_path),
                total_pages=total_pages,
                elapsed_seconds=elapsed,
            )

            # PDF 분할 (split_parts > 1인 경우에만)
            if self._config.split_parts > 1:
                self._run_split(output_path)

        finally:
            self._cleanup_temp(temp_dir)

    # ── Phase 1: 병렬 OCR ────────────────────────────────────────────────────

    def _run_parallel_ocr(
        self,
        pdf_path: Path,
        model_dir: Path,
        assignments: list[list[int]],
        temp_dir: Path,
        total_pages: int,
    ) -> None:
        """워커 프로세스를 생성하여 병렬 OCR을 실행한다."""
        ctx = multiprocessing.get_context("spawn")
        progress_queue: multiprocessing.Queue = ctx.Queue()

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
                    "max_tokens": self._config.max_tokens,
                    "max_image_size": self._config.max_image_size,
                },
                name=f"ocr-worker-{worker_id}",
            )
            p.start()
            workers.append(p)

        self._reporter.report_log(
            "info", f"{len(workers)}개 워커 프로세스 시작 (OCR 전용)"
        )

        # 진행률 수집
        self._listen_progress(progress_queue, workers, total_pages, assignments)

        # 워커 종료 대기
        for w in workers:
            w.join(timeout=30)
            if w.is_alive():
                w.terminate()

        self._reporter.report_log("info", "OCR 완료 — 워커 종료, 메모리 해제됨")

    def _collect_ocr_results(
        self, temp_dir: Path, total_pages: int,
    ) -> tuple[dict[int, str], dict[int, list[dict]]]:
        """워커가 저장한 JSON에서 OCR 결과와 블록 결과를 수집한다.

        Args:
            temp_dir: JSON 파일이 저장된 임시 디렉토리
            total_pages: 전체 페이지 수

        Returns:
            (page_texts, page_block_results) 튜플
            - page_texts: {page_num: text} 딕셔너리
            - page_block_results: {page_num: block_results} 딕셔너리
        """
        page_texts: dict[int, str] = {}
        page_block_results: dict[int, list[dict]] = {}

        for json_path in sorted(temp_dir.glob("ocr_results_worker_*.json")):
            try:
                results = json.loads(json_path.read_text(encoding="utf-8"))
                for entry in results:
                    page_num = entry.get("page_num", -1)
                    text = entry.get("text", "")
                    block_results = entry.get("block_results")
                    if page_num >= 0:
                        page_texts[page_num] = text
                        if block_results is not None:
                            page_block_results[page_num] = block_results
            except Exception as exc:
                self._reporter.report_log(
                    "warn", f"OCR 결과 읽기 실패: {json_path.name} — {exc}"
                )

        n_block = len(page_block_results)
        self._reporter.report_log(
            "info",
            f"OCR 결과 수집: {len(page_texts)}/{total_pages} 페이지 "
            f"(블록 위치 정보: {n_block}페이지)",
        )
        return page_texts, page_block_results

    # ── Phase 2: 앙상블 후처리 ────────────────────────────────────────────────

    def _run_sequential_post_processing(
        self,
        page_texts: dict[int, str],
        post_model_dirs: list[tuple[str, Path | None]],
    ) -> dict[int, str]:
        """3개 모델로 독립 교정 후 앙상블 투표로 최종 결과를 결정한다.

        각 모델이 원본 OCR 텍스트를 독립적으로 교정하고,
        3개 결과를 줄 단위로 비교하여 다수결·전문모델 우선·사전 매칭으로 최종 텍스트를 결정한다.

        모델이 3개 미만이면 기존 캐스케이드 방식으로 폴백한다.

        Args:
            page_texts: {page_num: text} 딕셔너리
            post_model_dirs: [(model_id, model_dir)] 목록

        Returns:
            교정된 {page_num: text} 딕셔너리
        """
        # 3개 모델 미만이면 캐스케이드 폴백
        if len(post_model_dirs) < 3:
            return self._run_cascade_post_processing(page_texts, post_model_dirs)

        # 모델별 특화 모드 매핑 — 순서: Qwen3(korean) → EXAONE(proper_noun) → DeepSeek-R1(reasoning)
        model_modes = ["korean", "proper_noun", "reasoning"]

        # 각 모델의 독립 교정 결과를 저장한다
        # versions[model_idx][page_num] = 교정된 텍스트
        versions: list[dict[int, str]] = []

        for step_idx, (model_id, model_dir) in enumerate(post_model_dirs[:3]):
            mode = model_modes[step_idx] if step_idx < len(model_modes) else "korean"
            total_models = min(len(post_model_dirs), 3)

            self._reporter.report_log(
                "info",
                f"앙상블 {step_idx + 1}/{total_models} 시작: {model_id} (모드: {mode})",
            )

            version: dict[int, str] = {}
            processor = PostProcessor()

            try:
                processor.load_model(model_id, model_dir)
                self._reporter.report_log("info", f"후처리 모델 로드 완료: {model_id}")

                # 모든 페이지에 독립 교정 적용 — 원본 OCR 텍스트 기반
                for page_num in sorted(page_texts.keys()):
                    text = page_texts[page_num]
                    if not text.strip():
                        version[page_num] = text
                        continue

                    try:
                        refined = processor.refine_text(text, mode=mode)
                        version[page_num] = refined
                    except Exception:
                        version[page_num] = text  # 교정 실패 — 원본 유지

                self._reporter.report_log(
                    "info", f"앙상블 {step_idx + 1}/{total_models} 완료: {model_id}"
                )

            except RuntimeError as exc:
                self._reporter.report_log(
                    "warn", f"후처리 모델 로드 실패 (건너뜀): {model_id} — {exc}"
                )
                # 로드 실패 시 원본 텍스트를 해당 버전으로 사용
                for page_num in page_texts:
                    version[page_num] = page_texts[page_num]

            finally:
                processor.unload()
                self._reporter.report_log("info", f"후처리 모델 언로드: {model_id}")

            versions.append(version)

        # 앙상블 투표 — 3개 버전을 비교하여 최종 텍스트 결정
        self._reporter.report_log("info", "앙상블 투표 시작")

        from backend.ocr.atoms.ensemble_voter import ensemble_vote

        final_texts: dict[int, str] = {}
        vote_stats: dict[str, int] = {}

        for page_num in sorted(page_texts.keys()):
            original = page_texts[page_num]
            va = versions[0].get(page_num, original)
            vb = versions[1].get(page_num, original)
            vc = versions[2].get(page_num, original)

            result = ensemble_vote(va, vb, vc, original)
            final_texts[page_num] = result.text

            # 투표 통계 수집
            vote_stats[result.source] = vote_stats.get(result.source, 0) + 1

        # 투표 결과 보고
        stats_str = ", ".join(f"{k}={v}" for k, v in sorted(vote_stats.items()))
        self._reporter.report_log(
            "info", f"앙상블 투표 완료: {stats_str}"
        )

        return final_texts

    def _run_cascade_post_processing(
        self,
        page_texts: dict[int, str],
        post_model_dirs: list[tuple[str, Path | None]],
    ) -> dict[int, str]:
        """캐스케이드 방식으로 후처리를 수행한다 (모델 3개 미만 시 폴백).

        각 모델이 이전 모델의 결과를 이어받아 순차적으로 교정한다.

        Args:
            page_texts: {page_num: text} 딕셔너리
            post_model_dirs: [(model_id, model_dir)] 목록

        Returns:
            교정된 {page_num: text} 딕셔너리
        """
        mode = self._config.post_process_mode

        for step_idx, (model_id, model_dir) in enumerate(post_model_dirs, 1):
            total_models = len(post_model_dirs)
            self._reporter.report_log(
                "info",
                f"후처리 {step_idx}/{total_models} 시작: {model_id}",
            )

            processor = PostProcessor()
            try:
                processor.load_model(model_id, model_dir)
                self._reporter.report_log("info", f"후처리 모델 로드 완료: {model_id}")

                for page_num in sorted(page_texts.keys()):
                    text = page_texts[page_num]
                    if not text.strip():
                        continue

                    try:
                        refined = processor.refine_text(text, mode=mode)
                        page_texts[page_num] = refined
                    except Exception:
                        pass

                self._reporter.report_log(
                    "info", f"후처리 {step_idx}/{total_models} 완료: {model_id}"
                )

            except RuntimeError as exc:
                self._reporter.report_log(
                    "warn", f"후처리 모델 로드 실패 (건너뜀): {model_id} — {exc}"
                )

            finally:
                processor.unload()
                self._reporter.report_log("info", f"후처리 모델 언로드: {model_id}")

        return page_texts

    # ── Phase 3: PDF 생성 ────────────────────────────────────────────────────

    def _generate_final_pdf(
        self,
        pdf_path: Path,
        page_texts: dict[int, str],
        output_path: Path,
        total_pages: int,
        page_block_results: dict[int, list[dict]] | None = None,
    ) -> None:
        """교정된 텍스트 + 원본 이미지로 최종 PDF를 생성한다.

        블록 결과가 있는 페이지는 정확한 위치에 텍스트를 배치하고,
        없는 페이지는 기존 방식(Tesseract 위치 기반)으로 폴백한다.

        Args:
            pdf_path: 원본 PDF 파일 경로
            page_texts: {page_num: text} 딕셔너리
            output_path: 출력 PDF 경로
            total_pages: 전체 페이지 수
            page_block_results: {page_num: block_results} 블록 위치 정보 (선택)
        """
        from PIL import Image

        from backend.pdf.extractor import PdfExtractor
        from backend.pdf.generator import PdfGenerator

        if page_block_results is None:
            page_block_results = {}

        extractor = PdfExtractor(dpi=self._config.dpi)
        extractor.open(pdf_path)

        # 청크 단위로 PDF를 생성하여 메모리를 관리한다
        chunk_size = self._config.chunk_size
        chunk_paths: list[Path] = []
        temp_pdf_dir = output_path.parent / f".tmp_pdf_{uuid.uuid4().hex[:8]}"
        temp_pdf_dir.mkdir(parents=True, exist_ok=True)

        try:
            for chunk_start in range(0, total_pages, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_pages)
                chunk_path = temp_pdf_dir / f"chunk_{chunk_start:06d}.pdf"

                generator = PdfGenerator(chunk_path)

                for page_num in range(chunk_start, chunk_end):
                    image: Image.Image | None = None
                    try:
                        image = extractor.extract_page_image(page_num)
                        page_width, page_height = extractor.get_page_size(page_num)
                        text = page_texts.get(page_num, "")
                        block_results = page_block_results.get(page_num)

                        if block_results:
                            # 블록 결과가 있으면 정확한 위치에 배치
                            generator.add_page_with_block_results(
                                image, block_results,
                                page_width, page_height,
                            )
                        elif text.strip():
                            # 폴백: 기존 방식 (Tesseract 위치 기반)
                            generator.add_page(
                                image, text, page_width, page_height,
                            )
                        else:
                            generator.add_image_only_page(
                                image, page_width, page_height,
                            )
                    except Exception:
                        pass
                    finally:
                        if image is not None:
                            try:
                                image.close()
                            except Exception:
                                pass

                if generator.page_count > 0:
                    generator.save()
                    chunk_paths.append(chunk_path)

            extractor.close()

            # 청크 병합 → 최종 PDF
            from backend.pipeline.merger import merge_chunks

            actual_pages = merge_chunks(temp_pdf_dir, output_path)
            self._reporter.report_log(
                "info", f"PDF 생성 완료 — {actual_pages}페이지"
            )

        finally:
            # 임시 PDF 디렉토리 정리
            shutil.rmtree(temp_pdf_dir, ignore_errors=True)

    # ── 모델 준비 ────────────────────────────────────────────────────────────

    def _ensure_model_ready(self) -> Path:
        """OCR 모델이 로컬에 없으면 다운로드하고 모델 디렉토리를 반환한다."""
        cache_dir = self._config.resolved_model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        downloader = ModelDownloader(
            cache_dir=cache_dir,
            reporter=self._reporter,
        )
        return downloader.ensure_downloaded(self._config.model_id)

    def _ensure_post_models_ready(self) -> list[tuple[str, Path | None]]:
        """후처리 모델들을 다운로드하고 (model_id, model_dir) 목록을 반환한다.

        후처리가 비활성화되어 있으면 빈 목록을 반환한다.
        """
        if not self._config.enable_post_process:
            return []

        cache_dir = self._config.resolved_model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        downloader = ModelDownloader(
            cache_dir=cache_dir,
            reporter=self._reporter,
        )

        result: list[tuple[str, Path | None]] = []

        for alias in self._config.post_model_aliases:
            spec = SUPPORTED_MODELS.get(alias)
            if spec is None:
                self._reporter.report_log(
                    "warn", f"알 수 없는 후처리 모델 별칭: {alias} (건너뜀)"
                )
                continue

            model_id = spec.model_id
            self._reporter.report_log(
                "info", f"후처리 모델 준비: {model_id}"
            )

            try:
                model_dir = downloader.ensure_downloaded(model_id)
                result.append((model_id, model_dir))
            except Exception as exc:
                self._reporter.report_log(
                    "warn", f"후처리 모델 다운로드 실패 (건너뜀): {model_id} — {exc}"
                )

        return result

    # ── 유틸리티 ─────────────────────────────────────────────────────────────

    def _count_pages(self, pdf_path: Path) -> int:
        """PDF의 총 페이지 수를 반환한다."""
        import fitz

        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count

    def _calculate_assignments(self, total_pages: int) -> list[list[int]]:
        """각 워커에 할당할 페이지 번호 목록을 계산한다."""
        num_workers = self._config.num_workers
        min_pages_for_multi = self._config.chunk_size * num_workers
        if total_pages < min_pages_for_multi:
            num_workers = max(1, total_pages // self._config.chunk_size)
        num_workers = min(num_workers, total_pages)

        pages_per_worker = total_pages // num_workers
        assignments: list[list[int]] = []

        for i in range(num_workers):
            start = i * pages_per_worker
            end = (i + 1) * pages_per_worker if i < num_workers - 1 else total_pages
            assignments.append(list(range(start, end)))

        return assignments

    def _create_temp_dir(self) -> Path:
        """OCR 결과를 저장할 임시 디렉토리를 생성한다."""
        temp_base = Path(__file__).resolve().parent.parent / ".tmp_ocr"
        temp_dir = temp_base / uuid.uuid4().hex[:8]
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _cleanup_temp(self, temp_dir: Path) -> None:
        """임시 디렉토리를 삭제한다."""
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            parent = temp_dir.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass

    def _listen_progress(
        self,
        progress_queue: multiprocessing.Queue,
        workers: list[multiprocessing.Process],
        total_pages: int,
        assignments: list[list[int]],
    ) -> None:
        """Queue에서 워커 메시지를 수집하고 Flutter에 진행률을 보고한다."""
        completed: int = 0
        workers_done: int = 0
        num_workers: int = len(workers)
        worker_completed: dict[int, int] = {}
        worker_totals: dict[int, int] = {
            wid: len(pages)
            for wid, pages in enumerate(assignments)
            if pages
        }

        while workers_done < num_workers:
            if self._cancelled:
                for w in workers:
                    if w.is_alive():
                        w.terminate()
                self._reporter.report_log("info", "취소 요청 — 워커 종료")
                break

            try:
                msg = progress_queue.get(timeout=5)
            except queue_module.Empty:
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
                wid: int = msg.get("worker_id", 0)
                worker_completed[wid] = worker_completed.get(wid, 0) + 1

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
        """OCR 완료된 PDF를 설정된 권 수로 분할한다."""
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
