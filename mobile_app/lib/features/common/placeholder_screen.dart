import 'package:flutter/material.dart';

import '../../core/theme.dart';

class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.construction_rounded, size: 56, color: colors.text3),
          const SizedBox(height: 16),
          Text(
            'Раздел «$title»',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w600,
              color: colors.text2,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'в разработке',
            style: TextStyle(fontSize: 14, color: colors.text3),
          ),
        ],
      ),
    );
  }
}
