import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_exception.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_input.dart';
import '../../core/widgets/brain_pulse.dart';
import '../../providers/auth_provider.dart';
import '../../providers/theme_provider.dart';

/// Email/password sign-in.
class LoginScreen extends ConsumerStatefulWidget {
  /// Creates the login screen.
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).login(
            email: _email.text,
            password: _password.text,
          );
      if (mounted) context.go(Routes.dashboard);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (_) {
      setState(() => _error = 'Something went wrong. Please try again.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Scaffold(
      body: SafeArea(
        child: Stack(
          children: [
            Align(
              alignment: Alignment.topRight,
              child: Padding(
                padding: const EdgeInsets.all(AppDimens.space2),
                child: IconButton(
                  icon: Icon(c.isDark ? Icons.light_mode_outlined : Icons.dark_mode_outlined),
                  onPressed: () => ref.read(themeControllerProvider.notifier).toggle(),
                ),
              ),
            ),
            Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(AppDimens.space6),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 420),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Center(child: BrainPulse(size: 64)),
                      const SizedBox(height: AppDimens.space5),
                      Text('Private Internet',
                          textAlign: TextAlign.center, style: AppText.lg.copyWith(color: c.textPrimary)),
                      const SizedBox(height: AppDimens.space2),
                      Text('Your AI. Your server. Your rules.',
                          textAlign: TextAlign.center, style: AppText.sm.copyWith(color: c.textSecondary)),
                      const SizedBox(height: AppDimens.space8),
                      AppInput(
                        label: 'Email',
                        hint: 'you@example.com',
                        controller: _email,
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                      ),
                      const SizedBox(height: AppDimens.space4),
                      AppInput(
                        label: 'Password',
                        controller: _password,
                        obscure: true,
                        textInputAction: TextInputAction.done,
                        onSubmitted: (_) => _submit(),
                      ),
                      const SizedBox(height: AppDimens.space6),
                      AppButton(label: 'Sign in', onPressed: _submit, loading: _loading, expand: true),
                      if (_error != null) ...[
                        const SizedBox(height: AppDimens.space4),
                        Text(_error!,
                            textAlign: TextAlign.center,
                            style: AppText.sm.copyWith(color: c.brainAmber)),
                      ],
                      const SizedBox(height: AppDimens.space5),
                      Center(
                        child: TextButton(
                          onPressed: () => context.push(Routes.register),
                          child: Text('Create an account',
                              style: AppText.sm.copyWith(color: c.accentPrimary)),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
