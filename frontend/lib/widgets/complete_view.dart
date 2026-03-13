// OCR 처리 완료 뷰
// 성공 아이콘, 처리 통계, 파일 열기 / Finder에서 보기 / 새 변환 버튼을 표시한다.
// 분할이 수행된 경우 분할 파일 목록과 각 권의 페이지 범위를 함께 표시한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';
import '../services/file_service.dart';
import 'complete_stats_card.dart';

/// OCR 완료 결과 뷰
class CompleteView extends StatelessWidget {
  final OcrResult result;
  final VoidCallback onNewConversion;
  final FileService _fileService = FileService();

  CompleteView({
    super.key,
    required this.result,
    required this.onNewConversion,
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF1E2430) : AppColors.backgroundCard,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(
          color: AppColors.success.withAlpha(128),
          width: 1.5,
        ),
      ),
      child: SingleChildScrollView(
        child: Column(
          children: [
            _buildSuccessIcon(),
            const SizedBox(height: AppSpacing.lg),
            // 분할 여부에 따라 완료 문구를 다르게 표시한다.
            Text(
              result.isSplit ? '변환 및 분할 완료!' : '변환 완료!',
              style: TextStyle(
                fontSize: AppTextSize.heading2,
                fontWeight: FontWeight.bold,
                color: isDark ? Colors.white : AppColors.textPrimary,
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
            CompleteStatsCard(result: result),

            // 분할 파일 목록 -- 분할이 수행된 경우에만 표시한다.
            if (result.isSplit) ...[
              const SizedBox(height: AppSpacing.md),
              _buildSplitPartsList(isDark),
            ],

            const SizedBox(height: AppSpacing.xl),
            _buildActionButtons(context),
          ],
        ),
      ),
    );
  }

  /// 성공 체크 아이콘을 스케일+페이드 애니메이션과 함께 빌드한다.
  Widget _buildSuccessIcon() {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0.0, end: 1.0),
      duration: const Duration(milliseconds: 600),
      curve: Curves.elasticOut,
      builder: (context, value, child) {
        return Transform.scale(
          scale: value,
          child: Opacity(
            opacity: value.clamp(0.0, 1.0),
            child: child,
          ),
        );
      },
      child: Container(
        width: 72,
        height: 72,
        decoration: BoxDecoration(
          color: AppColors.success.withAlpha(26),
          shape: BoxShape.circle,
        ),
        child: const Icon(
          Icons.check_circle_rounded,
          size: 44,
          color: AppColors.success,
        ),
      ),
    );
  }

  /// 분할 파일 목록을 빌드한다.
  /// 각 권의 파일명과 페이지 범위를 보여준다.
  Widget _buildSplitPartsList(bool isDark) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF262D3D) : AppColors.backgroundPrimary,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 섹션 헤더
          Row(
            children: [
              const Icon(
                Icons.library_books_rounded,
                size: 14,
                color: AppColors.primary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(
                '분할 파일 목록 (${result.totalParts}권)',
                style: const TextStyle(
                  fontSize: AppTextSize.bodySmall,
                  fontWeight: FontWeight.w600,
                  color: AppColors.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),

          // 각 파트 파일 행
          ...result.splitParts.asMap().entries.map((entry) {
            final index = entry.key;
            final partPath = entry.value;
            final partName = partPath.split('/').last;
            return _buildPartRow(
              isDark: isDark,
              partNumber: index + 1,
              fileName: partName,
              filePath: partPath,
            );
          }),
        ],
      ),
    );
  }

  /// 분할 파트 행 하나를 빌드한다.
  Widget _buildPartRow({
    required bool isDark,
    required int partNumber,
    required String fileName,
    required String filePath,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Row(
        children: [
          // 권 번호 배지
          Container(
            width: 24,
            height: 24,
            decoration: BoxDecoration(
              color: AppColors.primary.withAlpha(26),
              borderRadius: BorderRadius.circular(AppRadius.sm),
            ),
            child: Center(
              child: Text(
                '$partNumber',
                style: const TextStyle(
                  fontSize: AppTextSize.caption,
                  fontWeight: FontWeight.w700,
                  color: AppColors.primary,
                ),
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),

          // 파일명 (말줄임 처리)
          Expanded(
            child: Text(
              fileName,
              style: TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: isDark ? Colors.white70 : AppColors.textSecondary,
              ),
              overflow: TextOverflow.ellipsis,
              maxLines: 1,
            ),
          ),

          const SizedBox(width: AppSpacing.sm),

          // 파일 열기 아이콘 버튼
          SizedBox(
            width: 28,
            height: 28,
            child: IconButton(
              onPressed: () => _fileService.openFile(filePath),
              padding: EdgeInsets.zero,
              icon: const Icon(
                Icons.open_in_new_rounded,
                size: 14,
                color: AppColors.primary,
              ),
              tooltip: '파일 열기',
            ),
          ),
        ],
      ),
    );
  }

  /// 액션 버튼 행을 빌드한다.
  Widget _buildActionButtons(BuildContext context) {
    // 분할된 경우 폴더 경로는 첫 번째 파트의 부모 디렉토리를 사용한다.
    final folderTarget = result.isSplit && result.splitParts.isNotEmpty
        ? result.splitParts.first
        : result.outputPath;

    return Column(
      children: [
        // 첫 번째 행: 파일 열기 + Finder에서 보기
        Row(
          children: [
            // 분할 없으면 원본 파일 열기, 분할이면 버튼 숨김
            if (!result.isSplit)
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _fileService.openFile(result.outputPath),
                  icon: const Icon(Icons.open_in_new_rounded, size: 16),
                  label: const Text('파일 열기'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    side: const BorderSide(color: AppColors.primary),
                    padding:
                        const EdgeInsets.symmetric(vertical: AppSpacing.md),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppRadius.md),
                    ),
                  ),
                ),
              ),
            if (!result.isSplit) const SizedBox(width: AppSpacing.md),
            Expanded(
              child: OutlinedButton.icon(
                // 분할 파일이 있으면 폴더를 열고, 없으면 파일 위치를 연다.
                onPressed: () => _fileService.revealInFinder(folderTarget),
                icon: const Icon(Icons.folder_open_rounded, size: 16),
                label: const Text('폴더 열기'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.textSecondary,
                  side: const BorderSide(color: AppColors.dropZoneBorder),
                  padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(AppRadius.md),
                  ),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        // 두 번째 행: 새 변환 버튼 (전체 너비)
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: onNewConversion,
            icon: const Icon(Icons.add_rounded, size: 18),
            label: const Text('새 파일 변환'),
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.primary,
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
