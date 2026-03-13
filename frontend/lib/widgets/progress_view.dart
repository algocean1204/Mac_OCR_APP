// OCR 처리 진행률 표시 뷰
// 현재 페이지/전체 페이지, 퍼센트, 경과 시간, 예상 잔여 시간을 표시한다.
// OCR 완료 후 PDF 분할 진행 중이면 분할 진행률 섹션을 추가로 표시한다.

import 'dart:async';
import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';
import 'phase_timeline.dart';
import 'progress_stats_row.dart';

/// OCR 처리 진행률 뷰
class ProgressView extends StatefulWidget {
  /// 현재 처리 진행 데이터
  final ProcessingProgress progress;

  /// PDF 분할 진행 중 데이터 (null이면 분할 없음 또는 분할 전)
  final SplitProgress? splitProgress;

  /// Phase 1(OCR)에서 수신한 원래 총 페이지 수
  /// Phase 2 후처리 시 모델별 진행률 계산에 사용한다.
  final int originalTotalPages;

  /// 로그 메시지 목록 — 처리 중 수신한 로그를 표시한다
  final List<LogEntry> logEntries;

  /// 메모리 경고 표시 여부
  final bool showMemoryWarning;

  /// 최근 메모리 경고 메시지
  final String? memoryWarningMessage;

  /// 현재 활성 모델 이름 (Phase 2 후처리 중)
  final String? activeModelName;

  /// 취소 버튼 클릭 콜백
  final VoidCallback onCancel;

  const ProgressView({
    super.key,
    required this.progress,
    this.splitProgress,
    this.originalTotalPages = 0,
    this.logEntries = const [],
    this.showMemoryWarning = false,
    this.memoryWarningMessage,
    this.activeModelName,
    required this.onCancel,
  });

  @override
  State<ProgressView> createState() => _ProgressViewState();
}

class _ProgressViewState extends State<ProgressView> {
  /// 경과 시간 갱신을 위한 타이머
  late Timer _timer;

  /// 표시용 경과 시간 (초)
  double _displayedElapsedSeconds = 0;

  @override
  void initState() {
    super.initState();
    _displayedElapsedSeconds = widget.progress.elapsedSeconds;
    // 1초마다 경과 시간 갱신
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) {
        setState(() {
          _displayedElapsedSeconds = widget.progress.elapsedSeconds;
        });
      }
    });
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF1E2430) : AppColors.backgroundCard,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildHeader(isDark),
            const SizedBox(height: AppSpacing.xl),
            _buildPhaseTimeline(),
            const SizedBox(height: AppSpacing.md),
            // 메모리 경고가 있으면 진행률 바 위에 배너를 표시한다
            if (widget.showMemoryWarning) ...[
              _buildMemoryWarning(isDark),
              const SizedBox(height: AppSpacing.md),
            ],
            _buildProgressBar(),
            // 워커 진행 정보가 있으면 워커별 진행률 섹션을 표시한다
            if (widget.progress.workerProgress.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              _buildWorkerProgress(isDark),
            ],
            const SizedBox(height: AppSpacing.md),
            ProgressStatsRow(
              elapsedSeconds: _displayedElapsedSeconds,
              estimatedRemainingSeconds: widget.progress.estimatedRemainingSeconds,
              memoryMb: widget.progress.memoryMb,
            ),
            // 처리 속도 표시
            if (widget.progress.secondsPerPage > 0) ...[
              const SizedBox(height: AppSpacing.xs),
              _buildSpeedIndicator(isDark),
            ],
            if (widget.progress.skippedPages > 0) ...[
              const SizedBox(height: AppSpacing.md),
              _buildSkippedWarning(),
            ],
            // OCR 완료 후 분할 진행 중이면 분할 상태 섹션을 표시한다.
            if (widget.splitProgress != null) ...[
              const SizedBox(height: AppSpacing.md),
              _buildSplitProgressSection(isDark),
            ],
            // 처리 로그 패널 — 취소 버튼 위에 표시한다
            _buildLogPanel(isDark),
            const SizedBox(height: AppSpacing.xl),
            _buildCancelButton(),
          ],
        ),
      ),
    );
  }

  /// 페이지 처리 속도를 표시한다.
  Widget _buildSpeedIndicator(bool isDark) {
    final pagesPerMin = 60.0 / widget.progress.secondsPerPage;
    return Row(
      children: [
        Icon(
          Icons.speed_rounded,
          size: 12,
          color: isDark ? Colors.white38 : AppColors.textTertiary,
        ),
        const SizedBox(width: 4),
        Text(
          '${pagesPerMin.toStringAsFixed(1)} 페이지/분',
          style: TextStyle(
            fontSize: AppTextSize.caption,
            color: isDark ? Colors.white38 : AppColors.textTertiary,
          ),
        ),
      ],
    );
  }

  /// 현재 상태에 맞는 파이프라인 단계를 결정하여 타임라인을 빌드한다.
  Widget _buildPhaseTimeline() {
    final statusText = widget.progress.statusText;
    final PipelinePhase phase;
    if (statusText.contains('PDF 생성')) {
      phase = PipelinePhase.pdfGeneration;
    } else if (statusText.contains('후처리')) {
      phase = PipelinePhase.postProcess;
    } else {
      phase = PipelinePhase.ocr;
    }
    return PhaseTimeline(currentPhase: phase);
  }

  /// 처리 중 헤더 (스피너 + 제목 + Phase 부제목)를 빌드한다.
  /// 분할 진행 중이면 제목이 변경된다.
  Widget _buildHeader(bool isDark) {
    final isSplitting = widget.splitProgress != null;
    final statusText = widget.progress.statusText;
    final String title;
    final String? subtitle;

    if (isSplitting) {
      final split = widget.splitProgress!;
      title = 'PDF 분할 중... (${split.currentPart}/${split.totalParts}권)';
      subtitle = null;
    } else if (statusText.contains('후처리')) {
      final modelDisplay = widget.activeModelName ?? '앙상블';
      title = '$modelDisplay 후처리 중...';
      subtitle = '2단계/3단계';
    } else if (statusText.contains('PDF 생성')) {
      title = 'PDF 생성 중...';
      subtitle = '3단계/3단계';
    } else {
      title = 'OCR 처리 중...';
      subtitle = '1단계/3단계';
    }

    return Row(
      children: [
        const SizedBox(
          width: 20,
          height: 20,
          child: CircularProgressIndicator(
            strokeWidth: 2.5,
            valueColor: AlwaysStoppedAnimation<Color>(AppColors.primary),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: TextStyle(
                fontSize: AppTextSize.heading3,
                fontWeight: FontWeight.w600,
                color: isDark ? Colors.white : AppColors.textPrimary,
              ),
            ),
            if (subtitle != null)
              Text(
                subtitle,
                style: TextStyle(
                  fontSize: AppTextSize.caption,
                  color: isDark ? Colors.white38 : AppColors.textTertiary,
                ),
              ),
          ],
        ),
      ],
    );
  }

  /// PDF 분할 진행 중 섹션을 빌드한다.
  Widget _buildSplitProgressSection(bool isDark) {
    final split = widget.splitProgress!;
    // 분할 진행률을 퍼센트로 환산한다.
    final splitPercent = (split.currentPart / split.totalParts).clamp(0.0, 1.0);

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.primary.withAlpha(13),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: AppColors.primary.withAlpha(51)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'PDF 분할 중',
                style: TextStyle(
                  fontSize: AppTextSize.bodySmall,
                  fontWeight: FontWeight.w600,
                  color: AppColors.primary,
                ),
              ),
              Text(
                '${split.currentPart} / ${split.totalParts}권',
                style: const TextStyle(
                  fontSize: AppTextSize.bodySmall,
                  fontWeight: FontWeight.w600,
                  color: AppColors.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          // 분할 진행률 바
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.sm),
            child: LinearProgressIndicator(
              value: splitPercent,
              minHeight: 6,
              backgroundColor: AppColors.primary.withAlpha(26),
              valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          // 현재 권의 페이지 범위 표시
          Text(
            '${split.currentPart}권: ${split.startPage}~${split.endPage}페이지',
            style: TextStyle(
              fontSize: AppTextSize.caption,
              color: isDark ? Colors.white54 : AppColors.textTertiary,
            ),
          ),
        ],
      ),
    );
  }

  /// 워커별 진행률 표시 섹션을 빌드한다.
  Widget _buildWorkerProgress(bool isDark) {
    final workers = widget.progress.workerProgress;
    if (workers.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF252B38) : const Color(0xFFF8FAFD),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(
          color: isDark ? const Color(0xFF3A4155) : AppColors.divider,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.memory_rounded,
                size: 14,
                color: isDark ? Colors.white54 : AppColors.textTertiary,
              ),
              const SizedBox(width: 6),
              Text(
                '워커 진행 상황 (${workers.length}개 병렬)',
                style: TextStyle(
                  fontSize: AppTextSize.caption,
                  fontWeight: FontWeight.w600,
                  color: isDark ? Colors.white70 : AppColors.textSecondary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          // 각 워커별 진행률 바를 순서대로 렌더링한다
          ...workers.map((worker) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: _buildSingleWorkerBar(worker, isDark),
              )),
        ],
      ),
    );
  }

  /// 개별 워커 1개의 진행률 바 행을 빌드한다.
  Widget _buildSingleWorkerBar(WorkerProgress worker, bool isDark) {
    // 워커별 구분 색상 (파랑, 초록, 오렌지 순으로 순환)
    const workerColors = [
      AppColors.primary,       // 워커 0: 파랑
      Color(0xFF34C759),       // 워커 1: 초록
      Color(0xFFFF9500),       // 워커 2: 오렌지
    ];
    final color = workerColors[worker.workerId % workerColors.length];

    return Row(
      children: [
        // 워커 번호 레이블 (1-based로 표시)
        SizedBox(
          width: 52,
          child: Text(
            '워커 ${worker.workerId + 1}',
            style: TextStyle(
              fontSize: AppTextSize.caption,
              color: isDark ? Colors.white54 : AppColors.textTertiary,
            ),
          ),
        ),
        // 진행률 바
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: worker.progress,
              minHeight: 6,
              backgroundColor:
                  isDark ? const Color(0xFF3A4155) : AppColors.divider,
              valueColor: AlwaysStoppedAnimation<Color>(color),
            ),
          ),
        ),
        const SizedBox(width: 8),
        // 완료/전체 페이지 수 텍스트
        SizedBox(
          width: 70,
          child: Text(
            '${worker.completed}/${worker.total}',
            textAlign: TextAlign.right,
            style: TextStyle(
              fontSize: AppTextSize.caption,
              fontWeight: FontWeight.w500,
              color: isDark ? Colors.white54 : AppColors.textTertiary,
            ),
          ),
        ),
      ],
    );
  }

  /// 진행률 바와 퍼센트 텍스트를 빌드한다.
  /// Phase 2(후처리)에서는 모델 번호와 실제 페이지 수를 표시한다.
  Widget _buildProgressBar() {
    final isPostProcessing = widget.progress.statusText.contains('후처리');
    final isGeneratingPdf = widget.progress.statusText.contains('PDF 생성');

    // Phase별 페이지 레이블 생성
    final String pageLabel;
    if (isPostProcessing && widget.originalTotalPages > 0) {
      // Phase 2: 모델 번호 + 실제 페이지 수 표시
      final totalModels =
          (widget.progress.totalPages / widget.originalTotalPages).ceil();
      final modelIndex =
          (widget.progress.currentPage / widget.originalTotalPages)
              .ceil()
              .clamp(1, totalModels);
      final pageInModel = widget.progress.currentPage -
          (modelIndex - 1) * widget.originalTotalPages;
      pageLabel =
          '모델 $modelIndex/$totalModels — $pageInModel / ${widget.originalTotalPages} 페이지';
    } else if (isGeneratingPdf) {
      pageLabel =
          '${widget.progress.currentPage} / ${widget.progress.totalPages} 페이지 생성 중';
    } else {
      pageLabel =
          '${widget.progress.currentPage} / ${widget.progress.totalPages} 페이지';
    }

    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              pageLabel,
              style: const TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: AppColors.textSecondary,
              ),
            ),
            Text(
              '${widget.progress.percent.toStringAsFixed(1)}%',
              style: const TextStyle(
                fontSize: AppTextSize.bodySmall,
                fontWeight: FontWeight.w600,
                color: AppColors.primary,
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.sm),
          child: TweenAnimationBuilder<double>(
            tween: Tween<double>(
              begin: widget.progress.percent / 100.0,
              end: widget.progress.percent / 100.0,
            ),
            duration: AppDuration.slow,
            curve: Curves.easeInOut,
            builder: (context, value, _) => LinearProgressIndicator(
              value: value,
              minHeight: 8,
              backgroundColor: AppColors.divider,
              valueColor:
                  const AlwaysStoppedAnimation<Color>(AppColors.primary),
            ),
          ),
        ),
      ],
    );
  }

  /// 스킵된 페이지 경고를 빌드한다.
  /// 실패한 페이지 번호가 있으면 함께 표시한다.
  Widget _buildSkippedWarning() {
    final failedPages = widget.progress.failedPages;
    // 실패한 페이지 번호를 간결하게 표시한다 (최대 5개 + 나머지)
    final String pageDetail;
    if (failedPages.isEmpty) {
      pageDetail = '';
    } else if (failedPages.length <= 5) {
      pageDetail = ' (${failedPages.join(", ")}p)';
    } else {
      final shown = failedPages.take(5).join(", ");
      pageDetail = ' ($shown... 외 ${failedPages.length - 5}페이지)';
    }

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.warning.withAlpha(26),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: AppColors.warning.withAlpha(77)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.warning_amber_rounded,
            size: 14,
            color: AppColors.warning,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              '${widget.progress.skippedPages}페이지 스킵됨$pageDetail',
              style: const TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: AppColors.warning,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 메모리 경고 배너를 빌드한다.
  Widget _buildMemoryWarning(bool isDark) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.error.withAlpha(26),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: AppColors.error.withAlpha(77)),
      ),
      child: Row(
        children: [
          const Icon(Icons.memory_rounded, size: 14, color: AppColors.error),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              widget.memoryWarningMessage ?? '메모리 사용량이 높습니다',
              style: const TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: AppColors.error,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 처리 로그를 접을 수 있는 패널로 빌드한다.
  Widget _buildLogPanel(bool isDark) {
    if (widget.logEntries.isEmpty) return const SizedBox.shrink();
    // 최근 5개 로그만 표시한다
    final recentLogs = widget.logEntries.length > 5
        ? widget.logEntries.sublist(widget.logEntries.length - 5)
        : widget.logEntries;

    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text(
        '처리 로그 (${widget.logEntries.length})',
        style: TextStyle(
          fontSize: AppTextSize.caption,
          color: isDark ? Colors.white54 : AppColors.textTertiary,
        ),
      ),
      children: recentLogs.map((log) {
        final Color levelColor;
        switch (log.level) {
          case 'warn':
            levelColor = AppColors.warning;
          case 'error':
            levelColor = AppColors.error;
          default:
            levelColor = isDark ? Colors.white38 : AppColors.textTertiary;
        }
        return Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: Text(
            log.message,
            style: TextStyle(
              fontSize: 11,
              color: levelColor,
              fontFamily: 'monospace',
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        );
      }).toList(),
    );
  }

  /// 취소 확인 다이얼로그를 표시한 후 취소한다.
  Widget _buildCancelButton() {
    return Center(
      child: OutlinedButton.icon(
        onPressed: _showCancelConfirmDialog,
        icon: const Icon(Icons.stop_circle_outlined, size: 18),
        label: const Text('취소'),
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.textSecondary,
          side: const BorderSide(color: AppColors.dropZoneBorder),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.md,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
      ),
    );
  }

  /// 취소 확인 다이얼로그를 표시한다.
  Future<void> _showCancelConfirmDialog() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('변환 취소'),
        content: const Text(
          '진행 중인 변환을 취소하시겠습니까?\n처리된 페이지까지의 부분 결과가 저장될 수 있습니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('계속 처리'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: AppColors.error),
            child: const Text('취소'),
          ),
        ],
      ),
    );

    if (confirmed == true) widget.onCancel();
  }
}
