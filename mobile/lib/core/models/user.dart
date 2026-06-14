import 'json_utils.dart';

/// A platform user as returned by `/auth/login` (`user`) and `/auth/me`.
///
/// The backend serialises the row with private columns stripped; unknown extra
/// fields are ignored here.
class AppUser {
  /// Constructs a user.
  const AppUser({
    required this.id,
    required this.email,
    required this.displayName,
    this.avatarUrl,
    this.plan = 'free',
    this.isAdmin = false,
    this.onboardingCompleted = false,
    this.onboardingStep = 0,
    this.languagePreference,
    this.emailVerified = false,
  });

  final String id;
  final String email;
  final String displayName;
  final String? avatarUrl;
  final String plan;
  final bool isAdmin;
  final bool onboardingCompleted;
  final int onboardingStep;
  final String? languagePreference;
  final bool emailVerified;

  /// Decodes a user row.
  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: asStr(json['id']),
        email: asStr(json['email']),
        displayName: asStr(json['display_name'], asStr(json['email']).split('@').first),
        avatarUrl: asStrOrNull(json['avatar_url']),
        plan: asStr(json['plan'], 'free'),
        isAdmin: asBool(json['is_admin']),
        onboardingCompleted: asBool(json['onboarding_completed']),
        onboardingStep: asInt(json['onboarding_step']) ?? 0,
        languagePreference: asStrOrNull(json['language_preference']),
        emailVerified: asBool(json['email_verified']),
      );

  /// First name for greetings ("Good morning, Adel.").
  String get firstName => displayName.trim().split(RegExp(r'\s+')).first;
}
