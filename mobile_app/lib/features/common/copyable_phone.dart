import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme.dart';

/// A compact read-only phone display with a one-tap copy button.
///
/// Usage:
/// ```dart
/// CopyablePhone(phone)
/// CopyablePhone(phone, style: TextStyle(fontSize: 12))
/// ```
///
/// - Renders nothing when [phone] is null or empty.
/// - Shows the phone string followed by a small [Icons.copy] icon button
///   coloured with [context.colors.primary].
/// - On icon tap: copies [phone] to clipboard and shows a SnackBar
///   "Телефон скопирован".
/// - The text is wrapped in [Flexible] so the Row never overflows.
class CopyablePhone extends StatelessWidget {
  const CopyablePhone(this.phone, {super.key, this.style});

  final String? phone;

  /// Optional text style for the phone number. Falls back to
  /// [context.colors.text2] at fontSize 13 when null.
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    final p = phone;
    if (p == null || p.isEmpty) return const SizedBox.shrink();

    final c = context.colors;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Flexible(
          child: Text(
            p,
            style: style ??
                TextStyle(
                  fontSize: 13,
                  color: c.text2,
                ),
          ),
        ),
        IconButton(
          icon: const Icon(Icons.copy, size: 16),
          color: c.primary,
          padding: const EdgeInsets.symmetric(horizontal: 4),
          constraints: const BoxConstraints(),
          tooltip: 'Скопировать телефон',
          onPressed: () {
            Clipboard.setData(ClipboardData(text: p));
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Телефон скопирован'),
                duration: Duration(seconds: 2),
              ),
            );
          },
        ),
      ],
    );
  }
}
