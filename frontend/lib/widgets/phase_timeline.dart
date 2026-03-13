// 3단계 파이프라인 진행 타임라인 위젯
// 현재 활성 단계를 하이라이트하고, 완료된 단계에 체크 표시한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';

/// 현재 파이프라인 단계를 나타내는 열거형
enum PipelinePhase {
  ocr,           // 1단계: OCR 처리
  postProcess,   // 2단계: 앙상블 후처리
  pdfGeneration, // 3단계: PDF 생성
}

/// 3단계 파이프라인 진행 타임라인
class PhaseTimeline extends StatelessWidget {
  /// 현재 활성 단계
  final PipelinePhase currentPhase;

  const PhaseTimeline({super.key, required this.currentPhase});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Row(
      children: [
        _buildStep(
          label: 'OCR',
          phase: PipelinePhase.ocr,
          isDark: isDark,
        ),
        _buildConnector(
          completed: currentPhase.index > PipelinePhase.ocr.index,
          isDark: isDark,
        ),
        _buildStep(
          label: '후처리',
          phase: PipelinePhase.postProcess,
          isDark: isDark,
        ),
        _buildConnector(
          completed: currentPhase.index > PipelinePhase.postProcess.index,
          isDark: isDark,
        ),
        _buildStep(
          label: 'PDF',
          phase: PipelinePhase.pdfGeneration,
          isDark: isDark,
        ),
      ],
    );
  }

  /// 개별 단계 아이콘 + 레이블을 빌드한다.
  Widget _buildStep({
    required String label,
    required PipelinePhase phase,
    required bool isDark,
  }) {
    final isActive = currentPhase == phase;
    final isCompleted = currentPhase.index > phase.index;

    final Color circleColor;
    final Color textColor;
    final Widget icon;

    if (isCompleted) {
      circleColor = AppColors.success;
      textColor = AppColors.success;
      icon = const Icon(Icons.check_rounded, size: 14, color: Colors.white);
    } else if (isActive) {
      circleColor = AppColors.primary;
      textColor = AppColors.primary;
      icon = const Icon(Icons.circle, size: 8, color: Colors.white);
    } else {
      circleColor = isDark ? const Color(0xFF3A4155) : AppColors.divider;
      textColor = isDark ? Colors.white38 : AppColors.textTertiary;
      icon = const SizedBox.shrink();
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AnimatedContainer(
          duration: AppDuration.normal,
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            color: circleColor,
            shape: BoxShape.circle,
          ),
          child: Center(child: icon),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: AppTextSize.caption,
            fontWeight: isActive ? FontWeight.w600 : FontWeight.normal,
            color: textColor,
          ),
        ),
      ],
    );
  }

  /// 단계 사이 연결선을 빌드한다.
  Widget _buildConnector({required bool completed, required bool isDark}) {
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.only(bottom: 18),
        child: AnimatedContainer(
          duration: AppDuration.normal,
          height: 2,
          margin: const EdgeInsets.symmetric(horizontal: 4),
          decoration: BoxDecoration(
            color: completed
                ? AppColors.success
                : (isDark ? const Color(0xFF3A4155) : AppColors.divider),
            borderRadius: BorderRadius.circular(1),
          ),
        ),
      ),
    );
  }
}
