// PDF 드래그 앤 드롭 영역 위젯
// 파일 드롭 및 파일 선택 버튼을 제공한다.
// 드래그 오버 시 시각적 피드백을 제공하고, PDF가 아닌 파일은 거부한다.

import 'package:flutter/material.dart';
import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';

import '../constants/app_constants.dart';

/// 드롭존 위젯 -- PDF 파일 입력의 진입점
class DropZone extends StatefulWidget {
  /// 유효한 PDF 파일이 드롭되거나 선택된 경우 콜백
  final void Function(String path) onFileSelected;

  /// 잘못된 파일이 드롭된 경우 콜백 (사용자에게 토스트 표시용)
  final void Function(String message)? onInvalidFile;

  const DropZone({
    super.key,
    required this.onFileSelected,
    this.onInvalidFile,
  });

  @override
  State<DropZone> createState() => _DropZoneState();
}

class _DropZoneState extends State<DropZone> {
  /// 드래그 중 여부 -- 테두리 색상 변경에 사용
  bool _isDragging = false;

  /// 파일 선택 중 여부 -- 버튼 중복 클릭 방지
  bool _isPickingFile = false;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return DropTarget(
      onDragEntered: (_) => setState(() => _isDragging = true),
      onDragExited: (_) => setState(() => _isDragging = false),
      onDragDone: _handleDrop,
      child: AnimatedContainer(
        duration: AppDuration.fast,
        width: double.infinity,
        constraints: const BoxConstraints(minHeight: 220),
        decoration: BoxDecoration(
          color: _isDragging
              ? AppColors.dropZoneBackgroundActive
              : (isDark ? const Color(0xFF1E2430) : AppColors.dropZoneBackground),
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(
            color: _isDragging
                ? AppColors.dropZoneBorderActive
                : AppColors.dropZoneBorder,
            width: _isDragging ? 2.0 : 1.5,
            // 점선 테두리는 CustomPainter로 구현
          ),
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.lg),
          child: _buildDropZoneContent(isDark),
        ),
      ),
    );
  }

  /// 드롭존 내부 콘텐츠를 빌드한다.
  Widget _buildDropZoneContent(bool isDark) {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.xl),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // PDF 파일 아이콘
          _buildFileIcon(),
          const SizedBox(height: AppSpacing.lg),

          // 안내 텍스트
          Text(
            _isDragging ? '파일을 놓으세요' : 'PDF 파일을 여기에 드래그하세요',
            style: TextStyle(
              fontSize: AppTextSize.heading3,
              fontWeight: FontWeight.w600,
              color: _isDragging
                  ? AppColors.primary
                  : (isDark ? Colors.white70 : AppColors.textSecondary),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),

          Text(
            '또는',
            style: TextStyle(
              fontSize: AppTextSize.bodySmall,
              color: isDark ? Colors.white38 : AppColors.textTertiary,
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // 파일 선택 버튼
          _buildSelectFileButton(),
        ],
      ),
    );
  }

  /// PDF 아이콘 위젯을 빌드한다.
  Widget _buildFileIcon() {
    return AnimatedContainer(
      duration: AppDuration.normal,
      width: 72,
      height: 72,
      decoration: BoxDecoration(
        color: _isDragging
            ? AppColors.primary.withAlpha(26)
            : AppColors.primaryLight,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Icon(
        Icons.picture_as_pdf_rounded,
        size: 36,
        color: _isDragging ? AppColors.primary : AppColors.primary.withAlpha(204),
      ),
    );
  }

  /// 파일 선택 버튼을 빌드한다.
  Widget _buildSelectFileButton() {
    return OutlinedButton.icon(
      onPressed: _isPickingFile ? null : _pickFile,
      icon: const Icon(Icons.folder_open_rounded, size: 18),
      label: const Text('파일 선택'),
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.primary,
        side: const BorderSide(color: AppColors.primary),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.md,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
      ),
    );
  }

  /// 파일 선택 대화상자를 열어 PDF 파일을 선택한다.
  Future<void> _pickFile() async {
    if (_isPickingFile) return;

    setState(() => _isPickingFile = true);

    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf'],
        dialogTitle: 'PDF 파일 선택',
      );

      if (result != null && result.files.single.path != null) {
        widget.onFileSelected(result.files.single.path!);
      }
    } finally {
      if (mounted) {
        setState(() => _isPickingFile = false);
      }
    }
  }

  /// 드롭된 파일을 처리한다.
  void _handleDrop(DropDoneDetails details) {
    setState(() => _isDragging = false);

    if (details.files.isEmpty) return;

    // 첫 번째 드롭 파일만 처리 (다중 파일 지원 안 함)
    final file = details.files.first;
    final path = file.path;

    // PDF 확장자 검사
    if (!path.toLowerCase().endsWith('.pdf')) {
      widget.onInvalidFile?.call('PDF 파일만 지원합니다. (.pdf)');
      return;
    }

    widget.onFileSelected(path);
  }
}
