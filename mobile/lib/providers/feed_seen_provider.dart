import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Tracks whether the user has opened PULSE / SIGNAL / STORIES this session.
///
/// Drives the amber presence dots on the Pulse and More nav icons. This is a
/// *presence* indicator, not a count — and the dot clears the first time the
/// tab is opened. Session-scoped (resets on cold start), since the backend has
/// no per-user "unseen content" signal.
class FeedSeen {
  /// Constructs the seen state.
  const FeedSeen({this.pulse = false, this.signal = false, this.stories = false});

  /// Whether PULSE has been opened.
  final bool pulse;

  /// Whether SIGNAL has been opened.
  final bool signal;

  /// Whether STORIES has been opened.
  final bool stories;

  /// Returns a copy with overrides.
  FeedSeen copyWith({bool? pulse, bool? signal, bool? stories}) => FeedSeen(
        pulse: pulse ?? this.pulse,
        signal: signal ?? this.signal,
        stories: stories ?? this.stories,
      );
}

/// Holds [FeedSeen] and exposes the mark-as-seen actions.
class FeedSeenController extends Notifier<FeedSeen> {
  @override
  FeedSeen build() => const FeedSeen();

  /// Marks PULSE opened (clears its dot).
  void markPulseSeen() {
    if (!state.pulse) state = state.copyWith(pulse: true);
  }

  /// Marks SIGNAL opened (clears the More dot).
  void markSignalSeen() {
    if (!state.signal) state = state.copyWith(signal: true);
  }

  /// Marks STORIES opened (clears the More dot).
  void markStoriesSeen() {
    if (!state.stories) state = state.copyWith(stories: true);
  }
}

/// Nav presence-dot state.
final feedSeenProvider = NotifierProvider<FeedSeenController, FeedSeen>(FeedSeenController.new);
