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
          const SizedBox(height: AppSpacing.md),

          // 에러 코드에 기반한 문제 해결 안내
          _buildTroubleshootingTips(isDark),
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

  /// 에러 코드에 기반한 문제 해결 안내를 빌드한다.
  Widget _buildTroubleshootingTips(bool isDark) {
    final tips = _getTipsForError(errorCode);
    if (tips.isEmpty) return const SizedBox.shrink();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF1E2430) : AppColors.primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.lightbulb_outline_rounded,
                size: 14,
                color: isDark ? Colors.white54 : AppColors.primary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(
                '해결 방법',
                style: TextStyle(
                  fontSize: AppTextSize.bodySmall,
                  fontWeight: FontWeight.w600,
                  color: isDark ? Colors.white70 : AppColors.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          ...tips.map((tip) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '• ',
                      style: TextStyle(
                        fontSize: AppTextSize.bodySmall,
                        color: isDark ? Colors.white54 : AppColors.textSecondary,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        tip,
                        style: TextStyle(
                          fontSize: AppTextSize.bodySmall,
                          color:
                              isDark ? Colors.white54 : AppColors.textSecondary,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  /// 에러 코드에 따른 해결 팁 목록을 반환한다.
  List<String> _getTipsForError(String? code) {
    switch (code) {
      case 'E010':
        return [
          'PDF 파일이 손상되지 않았는지 확인하세요.',
          '다른 PDF 뷰어에서 정상적으로 열리는지 확인하세요.',
        ];
      case 'E020':
        return [
          '메모리 부족일 수 있습니다. 다른 앱을 종료하고 재시도하세요.',
          '페이지 수가 많은 경우 분할 기능을 사용해보세요.',
        ];
      case 'E030':
        return [
          '인터넷 연결을 확인하세요.',
          '디스크 공간이 충분한지 확인하세요 (약 5GB 필요).',
        ];
      case 'E040':
        return [
          '메모리가 부족합니다. 실행 중인 다른 앱을 종료하세요.',
          'PDF를 분할하여 처리해보세요.',
        ];
      case 'E050':
        return [
          '앱을 재시작하세요.',
          '문제가 지속되면 앱을 재설치하세요.',
        ];
      default:
        return [
          '앱을 재시작한 후 다시 시도하세요.',
          '문제가 지속되면 GitHub 이슈를 작성해주세요.',
        ];
    }
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
