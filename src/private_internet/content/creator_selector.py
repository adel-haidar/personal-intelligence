"""Creator persona selection for the PULSE post pipeline.

After migration 0015, `content_creators` has a nullable `user_id` column:
  - NULL  = global persona, visible to ALL users
  - non-NULL = persona generated specifically for that user

`select_for_topic` now requires a `user_id` and filters to:
  WHERE is_active AND (user_id = <caller> OR user_id IS NULL)

so each user sees their own AI-generated personas PLUS the neutral global
basics, but never another user's personas.
"""

import random
import logging
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

ALL_TONES = ["informative", "satirical", "supportive", "critical"]

# Valid tones per global creator slug. Used as a fallback when a creator row
# does not carry a `valid_tones` list (e.g. the old global defaults).
# Per-user generated personas store their valid_tones in the DB row itself.
_TONE_MAP: dict[str, list[str]] = {
    # Global neutral basics (user_id IS NULL in content_creators)
    "global-science-desk": ["informative", "critical"],
    "world-sport-desk": ["supportive", "informative"],
    "curious-mind": ["informative", "supportive"],
}

# How much each affinity keyword hit contributes to the selection score.
_AFFINITY_WEIGHT = 0.4
# Penalty if the creator already posted about this topic in the last 7 days.
_RECENCY_PENALTY = 0.5


class CreatorSelector:
    def select_for_topic(self, db, topic: dict, *, user_id: str) -> dict:
        """Pick the best creator (row dict) for a topic.

        Scoped to the caller:
          1. Filter active creators visible to this user
             (own user_id OR global user_id=NULL), score >= 0.3
          2. Score each by affinity match + RL score - recency penalty
          3. Multiply by random.uniform(0.85, 1.0) for editorial variety
          4. Fallback: if no creator scores > 0.1, return highest overall score

        # MUST SCOPE BY USER
        """
        assert user_id is not None, "user_id must be set before any content operation"
        cur = db.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM content_creators
                   WHERE is_active = TRUE
                     AND score >= 0.3
                     AND (user_id = %s OR user_id IS NULL)""",
                (user_id,),
            )
            creators = [dict(r) for r in cur.fetchall()]
            if not creators:
                # All visible creators retired/low-score — fall back to best one
                cur.execute(
                    """SELECT * FROM content_creators
                       WHERE is_active = TRUE
                         AND (user_id = %s OR user_id IS NULL)
                       ORDER BY score DESC LIMIT 1""",
                    (user_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("No active creators available for user")
                return dict(row)

            # Creators that posted about this topic for this user in the last 7 days
            cur.execute(
                """SELECT DISTINCT creator_id FROM content_posts
                   WHERE topic_id = %s AND user_id = %s
                     AND created_at >= now() - INTERVAL '7 days'""",
                (topic["id"], user_id),
            )
            recent_creator_ids = {r["creator_id"] for r in cur.fetchall()}
        finally:
            cur.close()

        topic_terms = self._topic_terms(topic)

        best_creator = None
        best_score = float("-inf")
        for creator in creators:
            affinity_hits = self._affinity_match(topic_terms, creator.get("topic_affinities") or [])
            score = affinity_hits * _AFFINITY_WEIGHT + float(creator.get("score") or 0.0)
            if creator["id"] in recent_creator_ids:
                score -= _RECENCY_PENALTY
            score *= random.uniform(0.85, 1.0)
            if score > best_score:
                best_score = score
                best_creator = creator

        if best_score <= 0.1:
            # Nothing matched meaningfully — fall back to highest RL score
            best_creator = max(creators, key=lambda c: float(c.get("score") or 0.0))
            logger.info(
                f"[user:{user_id[:8]}] No creator scored > 0.1 for topic "
                f"'{topic.get('name')}'; falling back to '{best_creator['slug']}'"
            )

        return best_creator

    def select_tone(self, creator: dict, topic: dict) -> str:
        """Pick a tone for the creator, with 20% chance of variety flip.

        Tone source priority:
          1. `valid_tones` in the creator DB row (set for per-user personas)
          2. `_TONE_MAP` keyed by slug (legacy / global basics)
          3. `ALL_TONES` as a last resort
        """
        valid = (
            creator.get("valid_tones")
            or _TONE_MAP.get(creator.get("slug", ""), [])
            or ALL_TONES
        )
        tone = random.choice(valid)
        if random.random() < 0.2:
            others = [t for t in ALL_TONES if t != tone]
            if others:
                tone = random.choice(others)
        return tone

    @staticmethod
    def _topic_terms(topic: dict) -> list[str]:
        """Lowercased keywords + name tokens for affinity matching."""
        terms = [k.lower() for k in (topic.get("keywords") or [])]
        terms += [w.lower() for w in (topic.get("name") or "").split() if len(w) > 3]
        return terms

    @staticmethod
    def _affinity_match(topic_terms: list[str], affinities: list[str]) -> int:
        """Count creator affinities that appear in (or contain) any topic term."""
        hits = 0
        for affinity in affinities:
            a = affinity.lower()
            if any(a in term or term in a for term in topic_terms):
                hits += 1
        return hits
