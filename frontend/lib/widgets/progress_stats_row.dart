// OCR 진행률 통계 행 위젯
// 경과 시간, 예상 잔여 시간, 메모리 사용량을 가로로 나열하여 표시한다.

import 'package:flutter/material.dart';

import '../constants/app_constants.dart';

/// 진행률 통계 정보를 가로 행으로 표시하는 위젯
class ProgressStatsRow extends StatelessWidget {
  /// 경과 시간 (초)
  final double elapsedSeconds;

  /// 예상 잔여 시간 (초)
  final double estimatedRemainingSeconds;

  /// 메모리 사용량 (MB)
  final double memoryMb;

  const ProgressStatsRow({
    super.key,
    required this.elapsedSeconds,
    required this.estimatedRemainingSeconds,
    required this.memoryMb,
  });

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Row(
      children: [
        Expanded(
          child: _buildStatItem(
            icon: Icons.timer_outlined,
            label: '경과 시간',
            value: _formatTime(elapsedSeconds),
            isDark: isDark,
          ),
        ),
        Expanded(
          child: _buildStatItem(
            icon: Icons.hourglass_bottom_rounded,
            label: '예상 잔여',
            value: estimatedRemainingSeconds > 0
                ? '약 ${_formatTime(estimatedRemainingSeconds)}'
                : '계산 중...',
            isDark: isDark,
          ),
        ),
        Expanded(
          child: _buildStatItem(
            icon: Icons.memory_rounded,
            label: '메모리',
            value: memoryMb > 0
                ? '${(memoryMb / 1024).toStringAsFixed(1)} GB'
                : '-',
            isDark: isDark,
          ),
        ),
      ],
    );
  }

  /// 통계 아이템 하나를 빌드한다.
  Widget _buildStatItem({
    required IconData icon,
    required String label,
    required String value,
    required bool isDark,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(
              icon,
              size: 12,
              color: isDark ? Colors.white38 : AppColors.textTertiary,
            ),
            const SizedBox(width: 4),
            Text(
              label,
              style: TextStyle(
                fontSize: AppTextSize.caption,
                color: isDark ? Colors.white38 : AppColors.textTertiary,
              ),
            ),
          ],
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: TextStyle(
            fontSize: AppTextSize.bodySmall,
            fontWeight: FontWeight.w500,
            color: isDark ? Colors.white70 : AppColors.textSecondary,
          ),
        ),
      ],
    );
  }

  /// 초 단위 시간을 읽기 쉬운 형태로 포맷한다.
  String _formatTime(double seconds) {
    final totalSeconds = seconds.floor();
    final mins = totalSeconds ~/ 60;
    final secs = totalSeconds % 60;
    if (mins > 0) {
      return '$mins분 ${secs.toString().padLeft(2, '0')}초';
    }
    return '$secs초';
  }
}
