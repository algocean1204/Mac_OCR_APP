// 홈 화면 뷰 빌더 -- 상태별 위젯 생성 로직
// home_screen.dart 에서 빌드 메서드를 분리하여 파일 크기를 줄인다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';
import '../models/ocr_state.dart';
import '../widgets/drop_zone.dart';
import '../widgets/file_selected_view.dart';
import '../widgets/model_download_view.dart';
import '../widgets/progress_view.dart';
import '../widgets/complete_view.dart';
import '../widgets/error_view.dart';
import '../widgets/toast_notification.dart';
import 'home_state_handler.dart';

/// 홈 화면의 각 상태에 맞는 위젯을 생성하는 빌더 클래스
class HomeScreenBuilder {
  /// 현재 상태에 맞는 메인 뷰를 반환한다.
  static Widget buildStateView({
    required BuildContext context,
    required OcrAppState appState,
    required String? selectedFilePath,
    required DownloadProgress? downloadProgress,
    required ProcessingProgress? processingProgress,
    // PDF 분할 진행 중 상태 (null이면 분할 없음 또는 분할 전)
    required SplitProgress? splitProgress,
    required OcrResult? ocrResult,
    required String? errorMessage,
    required String? errorCode,
    required bool isRecoverable,
    // 모델 초기 설정 중 메시지 (서드파티 stderr 출력 감지 시)
    String? modelSetupMessage,
    required void Function(String) onFileSelected,
    required VoidCallback onClearFile,
    required void Function(int splitCount) onStartOcr,
    required VoidCallback onCancel,
    required VoidCallback onRetry,
    required VoidCallback onReset,
  }) {
    Widget view;

    switch (appState) {
      case OcrAppState.idle:
        view = DropZone(
          key: const ValueKey('idle'),
          onFileSelected: onFileSelected,
          onInvalidFile: (msg) => ToastNotification.showError(context, msg),
        );

      case OcrAppState.fileSelected:
        view = FileSelectedView(
          key: const ValueKey('fileSelected'),
          filePath: selectedFilePath!,
          // 분할 권 수를 포함한 콜백을 그대로 위임한다.
          onStartOcr: onStartOcr,
          onClearFile: onClearFile,
        );

      case OcrAppState.downloadingModel:
        view = ModelDownloadView(
          key: const ValueKey('downloading'),
          progress: downloadProgress,
        );

      case OcrAppState.processing:
        view = processingProgress == null
            ? _LoadingInitView(
                key: const ValueKey('processing_init'),
                modelSetupMessage: modelSetupMessage,
              )
            : ProgressView(
                key: const ValueKey('processing'),
                progress: processingProgress,
                // 분할 진행 상태를 넘겨 분할 중 UI를 표시한다.
                splitProgress: splitProgress,
                onCancel: onCancel,
              );

      case OcrAppState.complete:
        view = ocrResult == null
            ? const SizedBox.shrink(key: ValueKey('complete_empty'))
            : CompleteView(
                key: const ValueKey('complete'),
                result: ocrResult,
                onNewConversion: onReset,
              );

      case OcrAppState.error:
        view = ErrorView(
          key: const ValueKey('error'),
          errorMessage: errorMessage ?? '알 수 없는 오류가 발생했습니다.',
          errorCode: errorCode,
          isRecoverable: isRecoverable,
          onRetry: isRecoverable ? onRetry : null,
          onNewFile: onReset,
        );
    }

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: view,
      ),
    );
  }

  /// 앱 헤더 (로고 + 앱명 + 현재 상태 설명)를 빌드한다.
  static Widget buildHeader(BuildContext context, OcrAppState appState) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.primary,
            borderRadius: BorderRadius.circular(AppRadius.sm),
          ),
          child: const Icon(
            Icons.document_scanner_rounded,
            color: Colors.white,
            size: 20,
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              AppInfo.appName,
              style: TextStyle(
                fontSize: AppTextSize.heading3,
                fontWeight: FontWeight.bold,
                color: isDark ? Colors.white : AppColors.textPrimary,
              ),
            ),
            Text(
              HomeStateHandler.getStateDescription(appState),
              style: const TextStyle(
                fontSize: AppTextSize.caption,
                color: AppColors.textTertiary,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// 모델 로드 초기화 중 표시하는 로딩 뷰
/// 서드파티 라이브러리의 모델 다운로드/로드 관련 stderr 출력이 감지되면
/// "초기 모델 설정 중... (최초 1회만 진행)" 메시지를 추가로 표시한다.
class _LoadingInitView extends StatelessWidget {
  /// 모델 초기 설정 중 메시지 (null이면 기본 메시지만 표시)
  final String? modelSetupMessage;

  const _LoadingInitView({super.key, this.modelSetupMessage});

  @override
  Widget build(BuildContext context) {
    final isSettingUp = modelSetupMessage != null;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const CircularProgressIndicator(
          valueColor: AlwaysStoppedAnimation<Color>(AppColors.primary),
        ),
        const SizedBox(height: AppSpacing.lg),
        Text(
          isSettingUp ? '초기 모델 설정 중...' : 'AI 모델 로드 중...',
          style: const TextStyle(
            fontSize: AppTextSize.body,
            color: AppColors.textSecondary,
          ),
        ),
        // 모델 설정 감지 시 안내 메시지 표시
        if (isSettingUp) ...[
          const SizedBox(height: AppSpacing.sm),
          const Text(
            '(최초 1회만 진행)',
            style: TextStyle(
              fontSize: AppTextSize.caption,
              color: AppColors.textTertiary,
            ),
          ),
        ],
      ],
    );
  }
}
