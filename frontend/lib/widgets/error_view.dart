// 에러 발생 시 표시되는 뷰
// 에러 메시지, 재시도 버튼, 새 파일 선택 버튼을 표시한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';

/// OCR 에러 뷰
class ErrorView extends StatelessWidget {
  /// 사용자에게 표시할 에러 메시지
  final String errorMessage;

  /// 에러 코드 (디버깅용, null이면 표시 안 함)
  final String? errorCode;

  /// 재시도 가능 여부 -- true면 재시도 버튼 표시
  final bool isRecoverable;

  /// 재시도 버튼 클릭 콜백
  final VoidCallback? onRetry;

  /// 새 파일 선택 콜백 (IDLE 상태로 복귀)
  final VoidCallback onNewFile;

  const ErrorView({
    super.key,
    required this.errorMessage,
    this.errorCode,
    this.isRecoverable = false,
    this.onRetry,
    required this.onNewFile,
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF2A1A1A) : const Color(0xFFFFF5F5),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(
          color: AppColors.error.withAlpha(128),
          width: 1.5,
        ),
      ),
      child: Column(
        children: [
          // 에러 아이콘
          _buildErrorIcon(),
          const SizedBox(height: AppSpacing.lg),

          // 에러 제목
          Text(
            '처리 중 오류가 발생했습니다',
            style: TextStyle(
              fontSize: AppTextSize.heading3,
              fontWeight: FontWeight.w600,
              color: isDark ? Colors.white : AppColors.textPrimary,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.md),

          // 에러 메시지 카드
          _buildErrorMessageCard(isDark),
          const SizedBox(height: AppSpacing.xl),

          // 액션 버튼들
          _buildActionButtons(),
        ],
      ),
    );
  }

  /// 에러 아이콘을 빌드한다.
  Widget _buildErrorIcon() {
    return Container(
      width: 72,
      height: 72,
      decoration: BoxDecoration(
        color: AppColors.error.withAlpha(26),
        shape: BoxShape.circle,
      ),
      child: const Icon(
        Icons.error_outline_rounded,
        size: 44,
        color: AppColors.error,
      ),
    );
  }

  /// 에러 메시지 카드를 빌드한다.
  Widget _buildErrorMessageCard(bool isDark) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF1A0F0F) : const Color(0xFFFEECEC),
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 에러 코드 (있는 경우)
          if (errorCode != null) ...[
            Text(
              '에러 코드: $errorCode',
              style: const TextStyle(
                fontSize: AppTextSize.caption,
                fontWeight: FontWeight.w600,
                color: AppColors.error,
                fontFamily: 'monospace',
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
          ],

          // 에러 메시지
          Text(
            errorMessage,
            style: TextStyle(
              fontSize: AppTextSize.bodySmall,
              color: isDark ? Colors.white70 : AppColors.textSecondary,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }

  /// 액션 버튼들을 빌드한다.
  Widget _buildActionButtons() {
    return Column(
      children: [
        // 재시도 버튼 (복구 가능한 경우만)
        if (isRecoverable && onRetry != null) ...[
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded, size: 18),
              label: const Text('재시도'),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.error,
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
        ],

        // 새 파일 선택 버튼
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: onNewFile,
            icon: const Icon(Icons.folder_open_rounded, size: 18),
            label: const Text('새 파일 선택'),
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
    );
  }
}
