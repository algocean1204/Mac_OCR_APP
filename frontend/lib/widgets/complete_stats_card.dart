// OCR 완료 결과 통계 카드 위젯
// 출력 파일명, 위치, 페이지 수, 소요 시간, 분할 권 수를 표시한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';

/// 완료 결과 통계 카드
class CompleteStatsCard extends StatelessWidget {
  /// OCR 처리 결과 데이터
  final OcrResult result;

  const CompleteStatsCard({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    // 분할된 경우 첫 번째 파트의 디렉토리를 위치로 표시한다.
    final displayPath = result.isSplit && result.splitParts.isNotEmpty
        ? result.splitParts.first
        : result.outputPath;
    final fileName = displayPath.split('/').last;
    final outputDir = displayPath.contains('/')
        ? displayPath.substring(0, displayPath.lastIndexOf('/'))
        : displayPath;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF262D3D) : AppColors.backgroundPrimary,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        children: [
          // 분할 없으면 파일명 표시, 분할이면 분할 정보 표시
          if (!result.isSplit) ...[
            _buildStatRow(
              label: '파일',
              value: fileName,
              icon: Icons.insert_drive_file_rounded,
              isDark: isDark,
            ),
            const Divider(height: 1, color: AppColors.divider),
          ],
          if (result.isSplit) ...[
            _buildStatRow(
              label: '분할',
              value: '${result.totalParts}권으로 분할됨',
              icon: Icons.library_books_rounded,
              isDark: isDark,
              valueColor: AppColors.primary,
            ),
            const Divider(height: 1, color: AppColors.divider),
          ],
          _buildStatRow(
            label: '위치',
            value: outputDir,
            icon: Icons.folder_rounded,
            isDark: isDark,
          ),
          const Divider(height: 1, color: AppColors.divider),
          _buildStatRow(
            label: '페이지',
            value: result.skippedPages > 0
                ? '${result.totalPages}페이지 (${result.skippedPages}페이지 스킵)'
                : '${result.totalPages}페이지',
            icon: Icons.pages_rounded,
            isDark: isDark,
            valueColor: result.skippedPages > 0 ? AppColors.warning : null,
          ),
          const Divider(height: 1, color: AppColors.divider),
          _buildStatRow(
            label: '소요',
            value: result.formattedElapsedTime,
            icon: Icons.timer_rounded,
            isDark: isDark,
          ),
        ],
      ),
    );
  }

  /// 통계 행 하나를 빌드한다.
  Widget _buildStatRow({
    required String label,
    required String value,
    required IconData icon,
    required bool isDark,
    Color? valueColor,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        children: [
          Icon(
            icon,
            size: 16,
            color: isDark ? Colors.white38 : AppColors.textTertiary,
          ),
          const SizedBox(width: AppSpacing.sm),
          SizedBox(
            width: 52,
            child: Text(
              label,
              style: TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: isDark ? Colors.white38 : AppColors.textTertiary,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                fontSize: AppTextSize.bodySmall,
                fontWeight: FontWeight.w500,
                color: valueColor ??
                    (isDark ? Colors.white70 : AppColors.textSecondary),
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
