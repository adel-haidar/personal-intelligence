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
import '../../core/widgets/toast.dart';
import '../../providers/auth_provider.dart';
import '../../providers/core_providers.dart';

/// Account creation. On success either signs in (if the server returns a token)
/// or prompts to verify email, then returns to login.
class RegisterScreen extends ConsumerStatefulWidget {
  /// Creates the register screen.
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _loading = false;
  String? _error;
  String _pw = '';

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  /// 0–3 strength based on length + character classes.
  int get _strength {
    var s = 0;
    if (_pw.length >= 8) s++;
    if (RegExp(r'[A-Z]').hasMatch(_pw) && RegExp(r'[a-z]').hasMatch(_pw)) s++;
    if (RegExp(r'[0-9!@#$%^&*]').hasMatch(_pw)) s++;
    return s;
  }

  Future<void> _submit() async {
    if (_password.text != _confirm.text) {
      setState(() => _error = 'Passwords don\'t match.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await ref.read(authRepositoryProvider).register(
            displayName: _name.text,
            email: _email.text,
            password: _password.text,
          );
      // Some deployments return a token directly; otherwise verification is needed.
      if (result['token'] is String) {
        await ref.read(authControllerProvider.notifier).login(
              email: _email.text,
              password: _password.text,
            );
        if (mounted) context.go(Routes.dashboard);
        return;
      }
      if (mounted) {
        AppToast.show(context, 'Account created. Check your email to verify, then sign in.');
        context.go(Routes.login);
      }
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
      appBar: AppBar(),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(AppDimens.space6),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('Create your account', style: AppText.lg.copyWith(color: c.textPrimary)),
                  const SizedBox(height: AppDimens.space6),
                  AppInput(label: 'Display name', controller: _name, textInputAction: TextInputAction.next),
                  const SizedBox(height: AppDimens.space4),
                  AppInput(
                    label: 'Email',
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    textInputAction: TextInputAction.next,
                  ),
                  const SizedBox(height: AppDimens.space4),
                  AppInput(
                    label: 'Password',
                    controller: _password,
                    obscure: true,
                    onChanged: (v) => setState(() => _pw = v),
                  ),
                  const SizedBox(height: AppDimens.space2),
                  _StrengthDots(strength: _strength),
                  const SizedBox(height: AppDimens.space4),
                  AppInput(
                    label: 'Confirm password',
                    controller: _confirm,
                    obscure: true,
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _submit(),
                  ),
                  const SizedBox(height: AppDimens.space6),
                  AppButton(label: 'Create account', onPressed: _submit, loading: _loading, expand: true),
                  if (_error != null) ...[
                    const SizedBox(height: AppDimens.space4),
                    Text(_error!, textAlign: TextAlign.center, style: AppText.sm.copyWith(color: c.brainAmber)),
                  ],
                  const SizedBox(height: AppDimens.space5),
                  Text(
                    'Your data stays on this server. We have no access to it.',
                    textAlign: TextAlign.center,
                    style: AppText.xs.copyWith(color: c.textTertiary),
                  ),
                  const SizedBox(height: AppDimens.space3),
                  Center(
                    child: TextButton(
                      onPressed: () => context.go(Routes.login),
                      child: Text('Already have an account? Sign in →',
                          style: AppText.sm.copyWith(color: c.accentPrimary)),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _StrengthDots extends StatelessWidget {
  const _StrengthDots({required this.strength});
  final int strength;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    Color colorFor(int i) {
      if (i >= strength) return c.borderMedium;
      return strength >= 3 ? c.success : c.brainAmber;
    }

    return Row(
      children: [
        for (var i = 0; i < 3; i++)
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 300),
              width: 10,
              height: 10,
              decoration: BoxDecoration(color: colorFor(i), shape: BoxShape.circle),
            ),
          ),
      ],
    );
  }
}
