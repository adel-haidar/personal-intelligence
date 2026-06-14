import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api/api_endpoints.dart';
import '../core/models/finance.dart';
import 'core_providers.dart';

/// Loads the latest banking analysis (`/banking/analysis/latest`).
///
/// Returns an empty [FinanceAnalysis] when the server has nothing yet (404 /
/// empty), so the screen shows its upload banner rather than an error.
class FinancesController extends AsyncNotifier<FinanceAnalysis> {
  @override
  Future<FinanceAnalysis> build() => _load();

  Future<FinanceAnalysis> _load() async {
    try {
      final data = await ref.read(apiClientProvider).get(ApiEndpoints.bankingLatest);
      if (data is Map) return FinanceAnalysis.fromJson(Map<String, dynamic>.from(data));
      return const FinanceAnalysis();
    } catch (_) {
      // No analysis yet is a normal empty state, not an error.
      return const FinanceAnalysis();
    }
  }

  /// Pull-to-refresh.
  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(_load);
  }

  /// Uploads a statement (PDF/CSV/XLSX) to be indexed into the brain.
  ///
  /// There is no dedicated `/finances/upload`; the file is sent to the generic
  /// `/file` route so the deterministic BankAdviser pipeline can pick it up.
  Future<void> uploadStatement(String path, String filename) async {
    await ref.read(apiClientProvider).uploadFiles(
      ApiEndpoints.fileUpload,
      fileField: 'file',
      files: [await MultipartFile.fromFile(path, filename: filename)],
    );
    await refresh();
  }
}

/// Finances provider.
final financesProvider = AsyncNotifierProvider<FinancesController, FinanceAnalysis>(FinancesController.new);
