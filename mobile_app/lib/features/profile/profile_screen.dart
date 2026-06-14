import 'package:flutter/material.dart';

import '../auth/auth_repository.dart';
import '../common/placeholder_screen.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key, required this.user});

  final CurrentUser user;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderScreen(title: 'Профиль');
  }
}
