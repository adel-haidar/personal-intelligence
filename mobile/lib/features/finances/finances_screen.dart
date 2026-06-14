import 'package:fl_chart/fl_chart.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/finance.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/utils/format.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/insight_card.dart';
import '../../core/widgets/progress_bar.dart';
import '../../core/widgets/states.dart';
import '../../core/widgets/toast.dart';
import '../../core/widgets/upload_banner.dart';
import '../../providers/finances_provider.dart';

/// The Finances screen — mirrors Health's architecture with an info-blue upload
/// banner and plain-language money insight cards.
class FinancesScreen extends ConsumerStatefulWidget {
  /// Creates the Finances screen.
  const FinancesScreen({super.key});

  @override
  ConsumerState<FinancesScreen> createState() => _FinancesScreenState();
}

class _FinancesScreenState extends ConsumerState<FinancesScreen> {
  bool _uploading = false;

  Future<void> _upload() async {
    final res = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'csv', 'xlsx'],
    );
    final file = res?.files.single;
    if (file?.path == null) return;
    setState(() => _uploading = true);
    try {
      await ref.read(financesProvider.notifier).uploadStatement(file!.path!, file.name);
      if (mounted) AppToast.show(context, '✓ Statement added — analysis will update shortly');
    } on ApiException catch (e) {
      if (mounted) AppToast.show(context, e.message, isError: true);
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final analysis = ref.watch(financesProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Finances', style: AppText.md.copyWith(color: c.textPrimary))),
      body: SafeArea(
        child: RefreshIndicator(
          color: c.brainAmber,
          onRefresh: () => ref.read(financesProvider.notifier).refresh(),
          child: analysis.when(
            loading: () => const ShimmerList(),
            error: (e, _) => ListView(children: [
              const SizedBox(height: 120),
              ErrorRetry(
                message: e is ApiException ? e.message : 'Couldn\'t load your finances.',
                onRetry: () => ref.read(financesProvider.notifier).refresh(),
              ),
            ]),
            data: (a) => _content(context, a),
          ),
        ),
      ),
    );
  }

  Widget _content(BuildContext context, FinanceAnalysis a) {
    final c = context.c;
    return ListView(
      padding: const EdgeInsets.all(AppDimens.space4),
      children: [
        if (a.isEmpty)
          UploadBanner(
            title: 'Understand your money',
            body: 'Upload a bank statement (PDF, CSV or XLSX) and get a calm, plain-language '
                'view of where your money goes. Everything stays on your server.',
            accent: c.info,
            primaryLabel: _uploading ? 'Uploading…' : 'Upload a statement',
            onPrimary: _uploading ? null : _upload,
            privacyNote: 'Your financial data is never shared. It is analysed only for you.',
          )
        else ...[
          InsightCard(
            title: 'Your money this month',
            body: a.summary ?? 'Here\'s how your income and spending compare.',
            child: _MoneyBreakdown(analysis: a),
          ),
          const SizedBox(height: AppDimens.space4),
          InsightCard(
            title: 'Savings and investments',
            body: a.savings != null
                ? 'You\'ve set aside ${Format.money(a.savings!)} so far.'
                : 'Add a statement to track your savings.',
            child: a.savings != null && a.savingsTarget != null && a.savingsTarget! > 0
                ? AppProgressBar(value: a.savings! / a.savingsTarget!, label: 'Toward your target', color: c.success)
                : null,
          ),
          const SizedBox(height: AppDimens.space4),
          InsightCard(
            title: 'What your finances suggest',
            body: a.summary ?? 'Keep your statements current to get tailored suggestions.',
          ),
          const SizedBox(height: AppDimens.space4),
          if (a.categories.isNotEmpty) _DetailCharts(analysis: a),
          const SizedBox(height: AppDimens.space5),
          Center(
            child: TextButton.icon(
              onPressed: _uploading ? null : _upload,
              icon: const Icon(Icons.add),
              label: const Text('Upload another statement'),
            ),
          ),
        ],
      ],
    );
  }
}

class _MoneyBreakdown extends StatelessWidget {
  const _MoneyBreakdown({required this.analysis});
  final FinanceAnalysis analysis;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final rows = <(String, double?, Color)>[
      ('Income', analysis.income, c.success),
      ('Spending', analysis.spending, c.warning),
      ('Net', analysis.net, c.accentPrimary),
    ];
    final maxVal = rows.map((r) => (r.$2 ?? 0).abs()).fold<double>(1, (a, b) => a > b ? a : b);
    return Column(
      children: [
        for (final (label, value, color) in rows)
          if (value != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: [
                  SizedBox(width: 72, child: Text(label, style: AppText.sm.copyWith(color: c.textSecondary))),
                  Expanded(child: AppProgressBar(value: value.abs() / maxVal, color: color)),
                  const SizedBox(width: AppDimens.space3),
                  Text(Format.money(value), style: AppText.mono(size: 12).copyWith(color: c.textPrimary)),
                ],
              ),
            ),
      ],
    );
  }
}

class _DetailCharts extends StatelessWidget {
  const _DetailCharts({required this.analysis});
  final FinanceAnalysis analysis;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final cats = analysis.categories.take(6).toList();
    final maxVal = cats.map((e) => e.amount.abs()).fold<double>(1, (a, b) => a > b ? a : b);
    return AppCard(
      padding: EdgeInsets.zero,
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: AppDimens.space4),
          title: Text('Show detailed charts', style: AppText.md.copyWith(color: c.textPrimary)),
          childrenPadding: const EdgeInsets.fromLTRB(AppDimens.space4, 0, AppDimens.space4, AppDimens.space4),
          children: [
            for (final cat in cats)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    SizedBox(
                      width: 90,
                      child: Text(cat.label, maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: AppText.sm.copyWith(color: c.textSecondary)),
                    ),
                    Expanded(
                      child: SizedBox(
                        height: 18,
                        child: BarChart(
                          BarChartData(
                            alignment: BarChartAlignment.start,
                            maxY: maxVal,
                            titlesData: const FlTitlesData(show: false),
                            borderData: FlBorderData(show: false),
                            gridData: const FlGridData(show: false),
                            barGroups: [
                              BarChartGroupData(x: 0, barRods: [
                                BarChartRodData(toY: cat.amount.abs(), color: c.accentPrimary, width: 10),
                              ]),
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: AppDimens.space2),
                    Text(Format.money(cat.amount), style: AppText.mono(size: 11).copyWith(color: c.textPrimary)),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
