// AI 모델 다운로드 진행률 표시 뷰
// 최초 실행 시 약 4-5GB 모델을 다운로드하는 동안 표시된다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';

/// 모델 다운로드 진행률 뷰
class ModelDownloadView extends StatelessWidget {
  /// 현재 다운로드 진행 데이터
  final DownloadProgress? progress;

  const ModelDownloadView({
    super.key,
    this.progress,
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
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 헤더 -- 다운로드 아이콘 + 제목
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: AppColors.primaryLight,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: const Icon(
                  Icons.cloud_download_rounded,
                  color: AppColors.primary,
                  size: 22,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AI 모델 다운로드 중',
                      style: TextStyle(
                        fontSize: AppTextSize.heading3,
                        fontWeight: FontWeight.w600,
                        color: isDark ? Colors.white : AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '최초 1회만 필요합니다 (약 4-5GB)',
                      style: TextStyle(
                        fontSize: AppTextSize.bodySmall,
                        color: isDark ? Colors.white54 : AppColors.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xl),

          // 진행률 바
          _buildProgressBar(),
          const SizedBox(height: AppSpacing.md),

          // 진행률 수치 텍스트
          _buildProgressText(isDark),
          const SizedBox(height: AppSpacing.lg),

          // 안내 메시지
          _buildInfoMessage(isDark),
        ],
      ),
    );
  }

  /// 진행률 바를 빌드한다.
  Widget _buildProgressBar() {
    final progressValue = progress != null ? (progress!.percent / 100.0) : null;

    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: LinearProgressIndicator(
        value: progressValue,
        minHeight: 8,
        backgroundColor: AppColors.divider,
        valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
      ),
    );
  }

  /// 다운로드 수치 텍스트를 빌드한다.
  Widget _buildProgressText(bool isDark) {
    if (progress == null) {
      // 진행률 데이터가 없으면 준비 중 메시지 표시
      return Text(
        '다운로드 준비 중...',
        style: TextStyle(
          fontSize: AppTextSize.bodySmall,
          color: isDark ? Colors.white54 : AppColors.textSecondary,
        ),
      );
    }

    final downloaded = _formatMb(progress!.downloadedMb);
    final total = _formatMb(progress!.totalMb);
    final percent = progress!.percent.toStringAsFixed(1);

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          '$downloaded / $total',
          style: TextStyle(
            fontSize: AppTextSize.bodySmall,
            color: isDark ? Colors.white54 : AppColors.textSecondary,
          ),
        ),
        Text(
          '$percent%',
          style: const TextStyle(
            fontSize: AppTextSize.bodySmall,
            fontWeight: FontWeight.w600,
            color: AppColors.primary,
          ),
        ),
      ],
    );
  }

  /// 안내 메시지를 빌드한다.
  Widget _buildInfoMessage(bool isDark) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark
            ? AppColors.primary.withAlpha(26)
            : AppColors.primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.info_outline_rounded,
            size: 16,
            color: AppColors.primary,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              '다운로드 완료 후 OCR 처리가 자동으로 시작됩니다.\n'
              '이후 실행 시에는 오프라인으로 사용 가능합니다.',
              style: TextStyle(
                fontSize: AppTextSize.bodySmall,
                color: isDark ? Colors.white70 : AppColors.textSecondary,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// MB 단위 숫자를 읽기 쉬운 문자열로 포맷한다.
  String _formatMb(double mb) {
    if (mb >= 1024) {
      return '${(mb / 1024).toStringAsFixed(1)} GB';
    }
    return '${mb.toStringAsFixed(0)} MB';
  }
}
