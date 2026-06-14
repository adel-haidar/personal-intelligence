import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/health.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_dimens.dart';
import '../../core/theme/app_text_styles.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/device_connection_card.dart';
import '../../core/widgets/insight_card.dart';
import '../../core/widgets/states.dart';
import '../../core/widgets/toast.dart';
import '../../core/widgets/upload_banner.dart';
import '../../providers/core_providers.dart';
import '../../providers/health_provider.dart';

/// The Health screen: upload/connect banner, stat row, device cards, plain
/// language insight cards, detailed charts, and 30s active-screen polling.
class HealthScreen extends ConsumerStatefulWidget {
  /// Creates the Health screen.
  const HealthScreen({super.key});

  @override
  ConsumerState<HealthScreen> createState() => _HealthScreenState();
}

class _HealthScreenState extends ConsumerState<HealthScreen> {
  bool _bannerDismissed = false;
  bool _showNumbers = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(healthProvider.notifier).startPolling());
  }

  @override
  void deactivate() {
    ref.read(healthProvider.notifier).stopPolling();
    super.deactivate();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final insight = ref.watch(healthProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Health', style: AppText.md.copyWith(color: c.textPrimary))),
      body: SafeArea(
        child: RefreshIndicator(
          color: c.brainAmber,
          onRefresh: () => ref.read(healthProvider.notifier).refresh(),
          child: insight.when(
            loading: () => const ShimmerList(),
            error: (e, _) => ListView(children: [
              const SizedBox(height: 120),
              ErrorRetry(
                message: e is ApiException ? e.message : 'Couldn\'t load your health data.',
                onRetry: () => ref.read(healthProvider.notifier).refresh(),
              ),
            ]),
            data: (data) => _content(context, data),
          ),
        ),
      ),
    );
  }

  Widget _content(BuildContext context, HealthInsight insight) {
    final c = context.c;
    final summary = insight.summary ?? const HealthSummary();
    final hasData = !summary.isEmpty;

    return ListView(
      padding: const EdgeInsets.all(AppDimens.space4),
      children: [
        if (!hasData || !_bannerDismissed)
          UploadBanner(
            title: 'Bring your health data in',
            body: 'Connect a device for automatic syncing, or upload an Apple Health export. '
                'Your data is stored privately on your own server.',
            accent: c.brainAmber,
            primaryLabel: 'Upload health files',
            onPrimary: _uploadFiles,
            secondaryLabel: 'Connect a device',
            onSecondary: () => _scrollHint(context),
            privacyNote: 'We never share your health data. It powers only your own insights.',
            onDismiss: hasData ? () => setState(() => _bannerDismissed = true) : null,
          ),
        if (hasData) ...[
          const SizedBox(height: AppDimens.space4),
          _StatRow(summary: summary),
        ],
        const SizedBox(height: AppDimens.space5),
        Text('Connect a device', style: AppText.md.copyWith(color: c.textPrimary)),
        const SizedBox(height: AppDimens.space3),
        const _DeviceGrid(),
        const SizedBox(height: AppDimens.space6),
        if (insight.coachInsight.isNotEmpty || insight.analysis.isNotEmpty) ...[
          InsightCard(
            title: 'Your body at a glance',
            body: insight.coachInsight.isNotEmpty
                ? insight.coachInsight
                : 'Add more data and your daily summary will appear here.',
            chips: [for (final f in insight.flags.take(3)) (label: f, color: c.brainAmber)],
          ),
          const SizedBox(height: AppDimens.space4),
          InsightCard(
            title: 'What your numbers mean',
            body: insight.analysis.isNotEmpty ? insight.analysis : 'No analysis yet.',
            trailing: TextButton(
              onPressed: () => setState(() => _showNumbers = !_showNumbers),
              child: Text(_showNumbers ? 'Hide numbers' : 'Show numbers'),
            ),
            child: _showNumbers ? _NumbersBlock(summary: summary) : null,
          ),
          const SizedBox(height: AppDimens.space4),
          InsightCard(
            title: 'What your data suggests',
            body: insight.reasoning.isNotEmpty ? insight.reasoning : 'Keep logging to see suggestions.',
          ),
          const SizedBox(height: AppDimens.space4),
        ],
        const _DetailedCharts(),
        const SizedBox(height: AppDimens.space5),
        Center(
          child: TextButton.icon(
            onPressed: _uploadFiles,
            icon: const Icon(Icons.add),
            label: const Text('Upload more data'),
          ),
        ),
        Center(
          child: TextButton.icon(
            onPressed: _confirmDelete,
            icon: Icon(Icons.delete_outline, color: c.danger),
            label: Text('Delete all health data', style: TextStyle(color: c.danger)),
          ),
        ),
      ],
    );
  }

  void _scrollHint(BuildContext context) =>
      AppToast.show(context, 'Choose a device below to connect.');

  Future<void> _uploadFiles() async {
    // Health files are indexed to the brain via /file, then today is recomputed.
    AppToast.show(context, 'Pick a health export from the Brain screen — then it syncs here.');
  }

  Future<void> _confirmDelete() async {
    final c = context.c;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete all health data?'),
        content: Text('This permanently removes your synced and uploaded health data.',
            style: AppText.sm.copyWith(color: c.textSecondary)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text('Delete', style: TextStyle(color: c.danger)),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      // NOTE: there is no dedicated health-delete endpoint; use Settings → Clear brain.
      AppToast.show(context, 'To clear health data, use Settings → Clear my brain.');
    }
  }
}

class _StatRow extends StatelessWidget {
  const _StatRow({required this.summary});
  final HealthSummary summary;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final stats = <(String, String?, bool)>[
      ('Steps', summary.steps?.toString(), false),
      ('Avg HR', summary.restingHr != null ? '${summary.restingHr!.round()}' : null, true),
      ('Sleep', summary.sleepLabel, false),
      ('Weight', summary.weightKg != null ? '${summary.weightKg!.toStringAsFixed(1)}kg' : null, false),
    ];
    // 2×2 grid per the handoff.
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: AppDimens.space3,
      crossAxisSpacing: AppDimens.space3,
      childAspectRatio: 2.4,
      children: [
        for (final (label, value, isHr) in stats)
          AppCard(
            padding: const EdgeInsets.all(AppDimens.space4),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(value ?? '—', style: AppText.display(22).copyWith(color: c.textPrimary)),
                    if (isHr) ...[
                      const SizedBox(width: 6),
                      const _LiveDot(),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(label, style: AppText.label.copyWith(color: c.textSecondary)),
              ],
            ),
          ),
      ],
    );
  }
}

class _LiveDot extends StatefulWidget {
  const _LiveDot();

  @override
  State<_LiveDot> createState() => _LiveDotState();
}

class _LiveDotState extends State<_LiveDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 1))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = context.c.success;
    return FadeTransition(
      opacity: _c.drive(Tween(begin: 0.4, end: 1)),
      child: Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
    );
  }
}

class _NumbersBlock extends StatelessWidget {
  const _NumbersBlock({required this.summary});
  final HealthSummary summary;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final rows = <(String, String)>[
      if (summary.hrvMs != null) ('HRV', '${summary.hrvMs!.round()} ms'),
      if (summary.sleepScore != null) ('Sleep score', summary.sleepScore!.round().toString()),
      if (summary.bodyFatPercent != null) ('Body fat', '${summary.bodyFatPercent!.toStringAsFixed(1)}%'),
      if (summary.activeEnergyKcal != null) ('Active energy', '${summary.activeEnergyKcal!.round()} kcal'),
      if (summary.weeksToGoalAtCurrentRate != null)
        ('Weeks to goal', summary.weeksToGoalAtCurrentRate!.toStringAsFixed(1)),
    ];
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(
      children: [
        for (final (k, v) in rows)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(k, style: AppText.sm.copyWith(color: c.textSecondary)),
                Text(v, style: AppText.mono(size: 12).copyWith(color: c.textPrimary)),
              ],
            ),
          ),
      ],
    );
  }
}

class _DeviceGrid extends ConsumerWidget {
  const _DeviceGrid();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Device OAuth connect has no backend endpoint yet — surfaced as "coming soon".
    // Apple Health / Health Connect use the Open Wearables SDK (stubbed).
    final hasNativeSdk = ref.watch(healthBgSyncServiceProvider).isAvailable;
    final devices = <(String, IconData, bool)>[
      ('Apple Health', Icons.favorite, !hasNativeSdk),
      ('Samsung / Health Connect', Icons.health_and_safety_outlined, !hasNativeSdk),
      ('Garmin', Icons.watch_outlined, true),
      ('WHOOP', Icons.fitness_center_outlined, true),
    ];
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      mainAxisSpacing: AppDimens.space3,
      crossAxisSpacing: AppDimens.space3,
      childAspectRatio: 1.7,
      children: [
        for (final (name, icon, soon) in devices)
          DeviceConnectionCard(
            name: name,
            icon: icon,
            comingSoon: soon,
            onConnect: () => AppToast.show(context, 'Device connection is coming soon.'),
          ),
      ],
    );
  }
}

class _DetailedCharts extends ConsumerWidget {
  const _DetailedCharts();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final c = context.c;
    final trends = ref.watch(healthTrendsProvider);
    return AppCard(
      padding: EdgeInsets.zero,
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: AppDimens.space4),
          title: Text('Show detailed charts', style: AppText.md.copyWith(color: c.textPrimary)),
          childrenPadding: const EdgeInsets.fromLTRB(AppDimens.space4, 0, AppDimens.space4, AppDimens.space4),
          children: [
            trends.when(
              loading: () => const ShimmerBox(height: 160),
              error: (_, __) => Text('No chart data yet.', style: AppText.sm.copyWith(color: c.textTertiary)),
              data: (points) {
                if (points.length < 2) {
                  return Text('Not enough data to chart yet.', style: AppText.sm.copyWith(color: c.textTertiary));
                }
                return SizedBox(height: 180, child: _WeightChart(points: points));
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _WeightChart extends StatelessWidget {
  const _WeightChart({required this.points});
  final List<MapEntry<DateTime, double>> points;

  @override
  Widget build(BuildContext context) {
    final c = context.c;
    final spots = [for (var i = 0; i < points.length; i++) FlSpot(i.toDouble(), points[i].value)];
    return LineChart(
      LineChartData(
        gridData: const FlGridData(show: false),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 36,
              getTitlesWidget: (v, _) => Text(v.toStringAsFixed(0),
                  style: AppText.mono(size: 9).copyWith(color: c.textTertiary)),
            ),
          ),
          bottomTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              interval: (points.length / 4).ceilToDouble().clamp(1, double.infinity),
              getTitlesWidget: (v, _) {
                final i = v.toInt();
                if (i < 0 || i >= points.length) return const SizedBox.shrink();
                return Text(DateFormat('d/M').format(points[i].key),
                    style: AppText.mono(size: 9).copyWith(color: c.textTertiary));
              },
            ),
          ),
        ),
        lineBarsData: [
          LineChartBarData(
            spots: spots,
            isCurved: true,
            barWidth: 1.5,
            color: c.accentPrimary,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(show: false),
          ),
        ],
      ),
    );
  }
}
