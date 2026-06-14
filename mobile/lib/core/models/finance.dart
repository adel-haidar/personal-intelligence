import 'json_utils.dart';

/// One labelled monetary line in a finance breakdown (income / category).
class FinanceLine {
  /// Constructs a line.
  const FinanceLine({required this.label, required this.amount});

  final String label;
  final double amount;
}

/// A best-effort view over the banking analysis (`/banking/analysis/latest`).
///
/// The deterministic BankAdviser pipeline returns a rich nested result; rather
/// than couple tightly to every field, we extract the headline numbers and a
/// plain-language summary, and keep the raw map for the detail view. Fields are
/// nullable because an account may have no analysis yet.
class FinanceAnalysis {
  /// Constructs an analysis view.
  const FinanceAnalysis({
    this.income,
    this.spending,
    this.net,
    this.savings,
    this.savingsTarget,
    this.summary,
    this.categories = const [],
    this.generatedAt,
    this.raw = const {},
  });

  final double? income;
  final double? spending;
  final double? net;
  final double? savings;
  final double? savingsTarget;
  final String? summary;
  final List<FinanceLine> categories;
  final DateTime? generatedAt;

  /// The untouched server payload, for the "show details" section.
  final Map<String, dynamic> raw;

  /// True when the server has no analysis to show.
  bool get isEmpty => income == null && spending == null && summary == null && categories.isEmpty;

  /// Decodes an analysis, tolerating several plausible field names.
  factory FinanceAnalysis.fromJson(Map<String, dynamic> json) {
    final cats = <FinanceLine>[];
    final rawCats = json['categories'] ?? json['spending_by_category'] ?? json['breakdown'];
    if (rawCats is List) {
      for (final c in rawCats) {
        if (c is Map) {
          cats.add(FinanceLine(
            label: asStr(c['label'] ?? c['name'] ?? c['category']),
            amount: asDouble(c['amount'] ?? c['total'] ?? c['value']) ?? 0,
          ));
        }
      }
    } else if (rawCats is Map) {
      rawCats.forEach((k, v) => cats.add(FinanceLine(label: k.toString(), amount: asDouble(v) ?? 0)));
    }
    return FinanceAnalysis(
      income: asDouble(json['income'] ?? json['total_income'] ?? json['monthly_income']),
      spending: asDouble(json['spending'] ?? json['total_spending'] ?? json['expenses']),
      net: asDouble(json['net'] ?? json['net_cashflow'] ?? json['balance']),
      savings: asDouble(json['savings'] ?? json['total_savings']),
      savingsTarget: asDouble(json['savings_target'] ?? json['target']),
      summary: asStrOrNull(json['summary'] ?? json['advice'] ?? json['headline']),
      categories: cats,
      generatedAt: asDate(json['generated_at'] ?? json['created_at']),
      raw: json,
    );
  }
}
