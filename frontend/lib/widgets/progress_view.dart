// OCR 처리 진행률 표시 뷰
// 현재 페이지/전체 페이지, 퍼센트, 경과 시간, 예상 잔여 시간을 표시한다.
// OCR 완료 후 PDF 분할 진행 중이면 분할 진행률 섹션을 추가로 표시한다.

import 'dart:async';
import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';
import 'progress_stats_row.dart';

/// OCR 처리 진행률 뷰
class ProgressView extends StatefulWidget {
  /// 현재 처리 진행 데이터
  final ProcessingProgress progress;

  /// PDF 분할 진행 중 데이터 (null이면 분할 없음 또는 분할 전)
  final SplitProgress? splitProgress;

  /// 취소 버튼 클릭 콜백
  final VoidCallback onCancel;

  const ProgressView({
    super.key,
    required this.progress,
    this.splitProgress,
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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(isDark),
          const SizedBox(height: AppSpacing.xl),
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
          if (widget.progress.skippedPages > 0) ...[
            const SizedBox(height: AppSpacing.md),
            _buildSkippedWarning(),
          ],
          // OCR 완료 후 분할 진행 중이면 분할 상태 섹션을 표시한다.
          if (widget.splitProgress != null) ...[
            const SizedBox(height: AppSpacing.md),
            _buildSplitProgressSection(isDark),
          ],
          const SizedBox(height: AppSpacing.xl),
          _buildCancelButton(),
        ],
      ),
    );
  }

  /// 처리 중 헤더 (스피너 + 제목)를 빌드한다.
  /// 분할 진행 중이면 제목이 변경된다.
  Widget _buildHeader(bool isDark) {
    final isSplitting = widget.splitProgress != null;
    final split = widget.splitProgress;
    final title = isSplitting
        ? 'PDF 분할 중... (${split!.currentPart}/${split.totalParts}권)'
        : 'OCR 처리 중...';

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
        Text(
          title,
          style: TextStyle(
            fontSize: AppTextSize.heading3,
            fontWeight: FontWeight.w600,
            color: isDark ? Colors.white : AppColors.textPrimary,
          ),
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
  Widget _buildProgressBar() {
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              '${widget.progress.currentPage} / ${widget.progress.totalPages} 페이지',
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
          child: LinearProgressIndicator(
            value: widget.progress.percent / 100.0,
            minHeight: 8,
            backgroundColor: AppColors.divider,
            valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
          ),
        ),
      ],
    );
  }

  /// 스킵된 페이지 경고를 빌드한다.
  Widget _buildSkippedWarning() {
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
          Text(
            '${widget.progress.skippedPages}페이지 스킵됨 (처리 계속 중)',
            style: const TextStyle(
              fontSize: AppTextSize.bodySmall,
              color: AppColors.warning,
            ),
          ),
        ],
      ),
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
