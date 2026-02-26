// 파일 선택 완료 후 표시되는 뷰
// 선택된 파일 정보, 분할 권 수 입력 필드, 변환 시작 버튼을 표시한다.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../constants/app_constants.dart';

/// 파일 선택 완료 뷰
class FileSelectedView extends StatefulWidget {
  /// 선택된 PDF 파일 경로
  final String filePath;

  /// 변환 시작 버튼 클릭 콜백 -- 분할 권 수를 인자로 전달한다.
  final void Function(int splitCount) onStartOcr;

  /// 파일 선택 취소 (다른 파일 선택) 콜백
  final VoidCallback onClearFile;

  const FileSelectedView({
    super.key,
    required this.filePath,
    required this.onStartOcr,
    required this.onClearFile,
  });

  @override
  State<FileSelectedView> createState() => _FileSelectedViewState();
}

class _FileSelectedViewState extends State<FileSelectedView> {
  /// 분할 권 수 상태 (기본 1 = 분할하지 않음)
  int _splitCount = 1;

  /// 숫자 입력 컨트롤러
  late TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    // 기본값 1로 초기화
    _controller = TextEditingController(text: '1');
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// 분할 권 수를 변경한다. 최소 1로 제한한다.
  void _setSplitCount(int value) {
    final clamped = value.clamp(1, 9999);
    setState(() {
      _splitCount = clamped;
      _controller.text = clamped.toString();
      // 텍스트 커서를 끝으로 이동
      _controller.selection = TextSelection.fromPosition(
        TextPosition(offset: _controller.text.length),
      );
    });
  }

  /// 텍스트 필드 입력값을 파싱하여 상태에 반영한다.
  void _onTextChanged(String value) {
    final parsed = int.tryParse(value);
    if (parsed != null && parsed >= 1) {
      setState(() => _splitCount = parsed.clamp(1, 9999));
    }
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final fileName = widget.filePath.split('/').last;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: isDark ? const Color(0xFF1E2430) : AppColors.backgroundCard,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          // 파일 정보 행
          _buildFileInfo(isDark, fileName),

          const SizedBox(height: AppSpacing.xl),

          // 분할 권 수 입력 섹션
          _buildSplitInput(isDark),

          const SizedBox(height: AppSpacing.xl),

          // 변환 시작 버튼
          _buildStartButton(),
        ],
      ),
    );
  }

  /// 파일 정보 행을 빌드한다.
  Widget _buildFileInfo(bool isDark, String fileName) {
    return Row(
      children: [
        // PDF 아이콘
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: AppColors.primaryLight,
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
          child: const Icon(
            Icons.picture_as_pdf_rounded,
            color: AppColors.primary,
            size: 24,
          ),
        ),
        const SizedBox(width: AppSpacing.md),

        // 파일명 및 경로
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                fileName,
                style: TextStyle(
                  fontSize: AppTextSize.body,
                  fontWeight: FontWeight.w600,
                  color: isDark ? Colors.white : AppColors.textPrimary,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(
                widget.filePath,
                style: TextStyle(
                  fontSize: AppTextSize.caption,
                  color: isDark ? Colors.white38 : AppColors.textTertiary,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ),
        ),

        // 파일 제거 버튼
        IconButton(
          onPressed: widget.onClearFile,
          icon: const Icon(Icons.close_rounded),
          color: isDark ? Colors.white38 : AppColors.textTertiary,
          tooltip: '파일 제거',
        ),
      ],
    );
  }

  /// 분할 권 수 입력 섹션을 빌드한다.
  Widget _buildSplitInput(bool isDark) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isDark
            ? const Color(0xFF262D3D)
            : AppColors.backgroundPrimary,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 섹션 레이블
          Text(
            '몇 권으로 나눌까요?',
            style: TextStyle(
              fontSize: AppTextSize.bodySmall,
              fontWeight: FontWeight.w600,
              color: isDark ? Colors.white70 : AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // 숫자 스테퍼 행
          Row(
            children: [
              // 감소 버튼
              _buildStepperButton(
                icon: Icons.remove_rounded,
                onPressed: _splitCount > 1
                    ? () => _setSplitCount(_splitCount - 1)
                    : null,
                isDark: isDark,
              ),

              const SizedBox(width: AppSpacing.sm),

              // 숫자 입력 필드
              SizedBox(
                width: 72,
                child: TextField(
                  controller: _controller,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  // 양의 정수만 허용
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                  ],
                  onChanged: _onTextChanged,
                  style: TextStyle(
                    fontSize: AppTextSize.heading3,
                    fontWeight: FontWeight.w700,
                    color: isDark ? Colors.white : AppColors.textPrimary,
                  ),
                  decoration: InputDecoration(
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(
                      vertical: AppSpacing.sm,
                      horizontal: AppSpacing.sm,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.sm),
                      borderSide: const BorderSide(color: AppColors.divider),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.sm),
                      borderSide: const BorderSide(color: AppColors.divider),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.sm),
                      borderSide: const BorderSide(
                        color: AppColors.primary,
                        width: 1.5,
                      ),
                    ),
                    filled: true,
                    fillColor: isDark
                        ? const Color(0xFF1E2430)
                        : AppColors.backgroundCard,
                  ),
                ),
              ),

              const SizedBox(width: AppSpacing.sm),

              // 증가 버튼
              _buildStepperButton(
                icon: Icons.add_rounded,
                onPressed: () => _setSplitCount(_splitCount + 1),
                isDark: isDark,
              ),

              const SizedBox(width: AppSpacing.md),

              // 현재 설정 설명 텍스트
              Expanded(
                child: Text(
                  _splitCount == 1
                      ? '1 = 분할하지 않음'
                      : '$_splitCount권으로 분할',
                  style: TextStyle(
                    fontSize: AppTextSize.caption,
                    color: _splitCount > 1
                        ? AppColors.primary
                        : (isDark ? Colors.white38 : AppColors.textTertiary),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 스테퍼 버튼 하나를 빌드한다.
  Widget _buildStepperButton({
    required IconData icon,
    required VoidCallback? onPressed,
    required bool isDark,
  }) {
    return SizedBox(
      width: 36,
      height: 36,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          padding: EdgeInsets.zero,
          side: BorderSide(
            color: onPressed == null
                ? AppColors.divider
                : AppColors.dropZoneBorder,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.sm),
          ),
          foregroundColor: onPressed == null
              ? (isDark ? Colors.white24 : AppColors.textTertiary)
              : AppColors.primary,
        ),
        child: Icon(icon, size: 18),
      ),
    );
  }

  /// 변환 시작 버튼을 빌드한다.
  Widget _buildStartButton() {
    return SizedBox(
      width: double.infinity,
      child: FilledButton.icon(
        // 분할 권 수를 콜백으로 전달한다.
        onPressed: () => widget.onStartOcr(_splitCount),
        icon: const Icon(Icons.text_fields_rounded, size: 20),
        label: Text(
          _splitCount > 1 ? '변환 및 분할 시작' : '변환 시작',
          style: const TextStyle(
            fontSize: AppTextSize.body,
            fontWeight: FontWeight.w600,
          ),
        ),
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primary,
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.md),
          ),
        ),
      ),
    );
  }
}
