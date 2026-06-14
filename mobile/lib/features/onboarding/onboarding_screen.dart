import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api_endpoints.dart';
import '../../core/router/app_router.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/toast.dart';
import '../../providers/auth_provider.dart';
import '../../providers/brain_provider.dart';
import '../../providers/core_providers.dart';

/// The 5-step onboarding wizard. Each step persists progress via
/// `PATCH /auth/onboarding`; the final step marks onboarding complete.
class OnboardingScreen extends ConsumerStatefulWidget {
  /// Creates the wizard.
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _page = PageController();
  int _index = 0;
  static const _steps = 5;

  Future<void> _persistStep(int step, {bool completed = false}) async {
    try {
      await ref.read(apiClientProvider).patch(
        ApiEndpoints.onboarding,
        body: {'onboarding_step': step, if (completed) 'onboarding_completed': true},
      );
    } catch (_) {/* best-effort; don't block the wizard on a flaky PATCH */}
  }

  void _next() {
    if (_index < _steps - 1) {
      setState(() => _index++);
      _page.animateToPage(_index, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      _persistStep(_index);
    }
  }

  Future<void> _finish() async {
    await _persistStep(_steps, completed: true);
    await ref.read(authControllerProvider.notifier).refreshUser();
    if (mounted) context.go(Routes.dashboard);
  }

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: LinearProgressIndicator(
                    value: (_index + 1) / _steps,
                    minHeight: 3,
                    backgroundColor: c.backgroundRaised,
                    valueColor: AlwaysStoppedAnimation(c.brainAmber),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppDimens.space4, vertical: AppDimens.space2),
                  child: Text('Step ${_index + 1} of $_steps',
                      style: AppText.mono(size: 12).copyWith(color: c.textTertiary)),
                ),
              ],
            ),
            Expanded(
              child: PageView(
                controller: _page,
                physics: const NeverScrollableScrollPhysics(),
                children: [
                  _WelcomeStep(onNext: _next),
                  _ExportStep(onNext: _next),
                  _IntroStep(onNext: _next),
                  _ConnectStep(onNext: _next),
                  _CompleteStep(onFinish: _finish),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StepScaffold extends StatelessWidget {
  const _StepScaffold({required this.title, required this.children, this.tinted = false});
  final String title;
  final List<Widget> children;

  /// Step 1's subtle arrival tint (warm cream in light, indigo wash in dark).
  final bool tinted;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return Container(
      color: tinted ? (c.isDark ? c.accentSurface : c.brainAmberSurface) : null,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppDimens.space6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: AppText.xxl.copyWith(color: c.textPrimary)),
            const SizedBox(height: AppDimens.space5),
            ...children,
          ],
        ),
      ),
    );
  }
}

class _WelcomeStep extends StatelessWidget {
  const _WelcomeStep({required this.onNext});
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    TextStyle body() => AppText.serif(size: 16).copyWith(color: c.textSecondary);
    return _StepScaffold(
      tinted: true,
      title: 'Your private internet starts here.',
      children: [
        Text(
          'This app is built around your brain — a private memory only you can read. '
          'Everything you share makes your AI understand you better.',
          style: body(),
        ),
        const SizedBox(height: AppDimens.space4),
        Text(
          'Your brain powers everything else: the feed you read, the videos you watch, '
          'and the health and finance insights you get.',
          style: body(),
        ),
        const SizedBox(height: AppDimens.space4),
        Text(
          'It lives on your server. We have no access to it, and neither does anyone else.',
          style: body(),
        ),
        const SizedBox(height: AppDimens.space8),
        AppButton(label: 'Set up my brain →', onPressed: onNext, expand: true),
      ],
    );
  }
}

class _ExportStep extends ConsumerStatefulWidget {
  const _ExportStep({required this.onNext});
  final VoidCallback onNext;
  @override
  ConsumerState<_ExportStep> createState() => _ExportStepState();
}

class _ExportStepState extends ConsumerState<_ExportStep> {
  int _tab = 0;
  bool _copied = false;
  static const _providers = ['Claude', 'ChatGPT', 'Gemini', 'Other'];

  String get _prompt =>
      'Summarise everything you know about me — my background, work, goals, '
      'preferences, communication style, and important context — as a single '
      'detailed document I can export. Be specific and thorough.';

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _prompt));
    setState(() => _copied = true);
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  Future<void> _upload() async {
    final res = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['txt', 'md', 'pdf'],
    );
    final path = res?.files.single.path;
    if (path == null) return;
    try {
      await ref.read(brainRepositoryProvider).uploadFile(path, res!.files.single.name);
      if (mounted) AppToast.show(context, '✓ Added to your brain');
    } catch (e) {
      if (mounted) AppToast.show(context, '$e', isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return _StepScaffold(
      title: 'Bring your AI memory',
      children: [
        Text('If you already use an AI, export what it knows about you and add it here.',
            style: AppText.serif(size: 15).copyWith(color: c.textSecondary)),
        const SizedBox(height: AppDimens.space4),
        Wrap(
          spacing: AppDimens.space2,
          children: [
            for (var i = 0; i < _providers.length; i++)
              ChoiceChip(
                label: Text(_providers[i]),
                selected: _tab == i,
                selectedColor: c.brainAmberSurface,
                side: BorderSide(color: _tab == i ? c.brainAmber : c.borderSubtle),
                labelStyle: AppText.sm.copyWith(
                  color: _tab == i ? c.brainAmber : c.textSecondary,
                  fontWeight: _tab == i ? FontWeight.w600 : FontWeight.w400,
                ),
                onSelected: (_) => setState(() => _tab = i),
              ),
          ],
        ),
        const SizedBox(height: AppDimens.space4),
        Container(
          width: double.infinity,
          constraints: const BoxConstraints(maxHeight: 140),
          padding: const EdgeInsets.all(AppDimens.space4),
          decoration: BoxDecoration(
            color: c.backgroundInput,
            borderRadius: BorderRadius.circular(AppDimens.inputRadius),
            border: Border.all(color: c.borderSubtle),
          ),
          child: SingleChildScrollView(
            child: Text(_prompt, style: AppText.mono(size: 12).copyWith(color: c.textPrimary)),
          ),
        ),
        const SizedBox(height: AppDimens.space3),
        AppButton(
          label: _copied ? '✓ Copied' : 'Copy prompt',
          icon: _copied ? Icons.check : Icons.copy,
          variant: AppButtonVariant.outlined,
          onPressed: _copy,
        ),
        const SizedBox(height: AppDimens.space5),
        Row(children: [
          Expanded(child: Divider(color: c.borderSubtle)),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppDimens.space3),
            child: Text('or', style: AppText.sm.copyWith(color: c.textTertiary)),
          ),
          Expanded(child: Divider(color: c.borderSubtle)),
        ]),
        const SizedBox(height: AppDimens.space5),
        AppButton(label: 'Upload the file', icon: Icons.upload_file, onPressed: _upload, expand: true),
        const SizedBox(height: AppDimens.space6),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            TextButton(onPressed: widget.onNext, child: const Text('Skip')),
            AppButton(label: 'Continue →', onPressed: widget.onNext),
          ],
        ),
      ],
    );
  }
}

class _IntroStep extends ConsumerStatefulWidget {
  const _IntroStep({required this.onNext});
  final VoidCallback onNext;
  @override
  ConsumerState<_IntroStep> createState() => _IntroStepState();
}

class _IntroStepState extends ConsumerState<_IntroStep> {
  final _controller = TextEditingController();
  bool _saved = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final text = _controller.text.trim();
    if (text.isNotEmpty) {
      try {
        await ref.read(brainRepositoryProvider).addText(text, title: 'My introduction');
        setState(() => _saved = true);
      } catch (_) {/* still allow continuing */}
    }
    widget.onNext();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return _StepScaffold(
      title: 'Write your introduction',
      children: [
        Text('Tell your brain who you are, in your own words.',
            style: AppText.serif(size: 15).copyWith(color: c.textSecondary)),
        const SizedBox(height: AppDimens.space4),
        ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 200),
          child: TextField(
            controller: _controller,
            maxLines: null,
            minLines: 8,
            style: AppText.serif().copyWith(color: c.textPrimary),
            onChanged: (_) => setState(() => _saved = false),
            decoration: const InputDecoration(
              hintText: 'I\'m a … I care about … I\'m working towards …',
            ),
          ),
        ),
        const SizedBox(height: 6),
        Align(
          alignment: Alignment.centerRight,
          child: Text(
            _saved ? '✓ Saved' : '${_controller.text.length} chars',
            style: AppText.mono(size: 11).copyWith(color: _saved ? c.brainAmber : c.textTertiary),
          ),
        ),
        const SizedBox(height: AppDimens.space6),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            TextButton(onPressed: widget.onNext, child: const Text('Skip')),
            AppButton(label: 'Continue →', onPressed: _continue),
          ],
        ),
      ],
    );
  }
}

class _ConnectStep extends StatelessWidget {
  const _ConnectStep({required this.onNext});
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return _StepScaffold(
      title: 'Connect devices & documents',
      children: [
        Text('Add health devices and documents now, or later from each screen.',
            style: AppText.serif(size: 15).copyWith(color: c.textSecondary)),
        const SizedBox(height: AppDimens.space4),
        ExpansionTile(
          title: Text('Health devices', style: AppText.md.copyWith(color: c.textPrimary)),
          childrenPadding: const EdgeInsets.only(bottom: AppDimens.space3),
          children: [
            Text(
              'Apple Health, Samsung Health and Health Connect sync in the background once '
              'you grant access on the Health screen. Cloud devices (Garmin, WHOOP, Oura) '
              'connect there too.',
              style: AppText.sm.copyWith(color: c.textSecondary),
            ),
          ],
        ),
        ExpansionTile(
          title: Text('Documents', style: AppText.md.copyWith(color: c.textPrimary)),
          childrenPadding: const EdgeInsets.only(bottom: AppDimens.space3),
          children: [
            Text(
              'Upload financial statements, your CV, or medical records from the Finances, '
              'Brain and Health screens — they\'re indexed privately into your brain.',
              style: AppText.sm.copyWith(color: c.textSecondary),
            ),
          ],
        ),
        const SizedBox(height: AppDimens.space6),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            TextButton(onPressed: onNext, child: const Text('Skip')),
            AppButton(label: 'Continue →', onPressed: onNext),
          ],
        ),
      ],
    );
  }
}

class _CompleteStep extends StatelessWidget {
  const _CompleteStep({required this.onFinish});
  final VoidCallback onFinish;

  static const _items = [
    'Your brain is created',
    'Your introduction is saved',
    'Your modules are ready',
  ];

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return _StepScaffold(
      title: 'Your brain is ready.',
      children: [
        Text('Everything you do from here makes it smarter.',
            style: AppText.serif(size: 16).copyWith(color: c.textSecondary)),
        const SizedBox(height: AppDimens.space6),
        for (var i = 0; i < _items.length; i++)
          _ChecklistRow(label: _items[i], delayMs: 200 * i),
        const SizedBox(height: AppDimens.space8),
        AppButton(label: 'Open my dashboard →', onPressed: onFinish, expand: true),
      ],
    );
  }
}

class _ChecklistRow extends StatefulWidget {
  const _ChecklistRow({required this.label, required this.delayMs});
  final String label;
  final int delayMs;
  @override
  State<_ChecklistRow> createState() => _ChecklistRowState();
}

class _ChecklistRowState extends State<_ChecklistRow> {
  bool _shown = false;

  @override
  void initState() {
    super.initState();
    Future.delayed(Duration(milliseconds: widget.delayMs), () {
      if (mounted) setState(() => _shown = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    return AnimatedOpacity(
      opacity: _shown ? 1 : 0,
      duration: const Duration(milliseconds: 300),
      child: AnimatedSlide(
        offset: _shown ? Offset.zero : const Offset(0, 0.2),
        duration: const Duration(milliseconds: 300),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppDimens.space2),
          child: Row(
            children: [
              Icon(Icons.check_circle, color: c.success, size: 20),
              const SizedBox(width: AppDimens.space3),
              Text(widget.label, style: AppText.base.copyWith(color: c.textPrimary)),
            ],
          ),
        ),
      ),
    );
  }
}
