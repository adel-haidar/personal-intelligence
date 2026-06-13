"""PULSE post generation batch job (Phase 3, Task 5)."""

import uuid
import logging
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from private_internet.database import _connect
from private_internet.content.creator_selector import CreatorSelector
from private_internet.content.post_generator import PostTextGenerator
from private_internet.content.image_generator import PostImageGenerator
from private_internet.content.asset_store import AssetStore

logger = logging.getLogger(__name__)


async def generate_posts_batch(count: int = 3, *, user_id: str) -> dict:
    """
    Generate posts for a single user from that user's own topics.
    # MUST SCOPE BY USER

    1. Query content_topics ordered by weight DESC, last_used_at ASC NULLS FIRST
       (prefer untouched high-weight topics)
    2. For each topic: select creator + tone, generate text + image,
       upload image to S3, insert into content_posts, bump topic usage.
    3. Log: N posts created, total Bedrock tokens used.

    Image failure is non-fatal: the post is still created with image_url=NULL.
    """
    assert user_id is not None, "user_id must be set before any content operation"
    logger.info(f"[user:{user_id[:8]}] Starting generate_posts_batch (count={count})")

    selector = CreatorSelector()
    text_generator = PostTextGenerator()
    image_generator = PostImageGenerator()
    asset_store = AssetStore()

    conn = _connect()
    created = 0
    failed = 0
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT * FROM content_topics
               WHERE user_id = %s
               ORDER BY weight DESC, last_used_at ASC NULLS FIRST
               LIMIT %s""",
            (user_id, count),
        )
        topics = [dict(r) for r in cur.fetchall()]
        cur.close()

        if not topics:
            logger.info("No topics available — run the topic intelligence job first.")
            return {"created": 0, "failed": 0}

        for topic in topics:
            try:
                # a/b. Pick creator + tone
                creator = selector.select_for_topic(conn, topic)
                tone = selector.select_tone(creator, topic)

                # Fetch research for the prompt
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """SELECT * FROM content_research
                       WHERE user_id = %s AND topic_id = %s
                       ORDER BY fetched_at DESC LIMIT 5""",
                    (user_id, topic["id"]),
                )
                research = [dict(r) for r in cur.fetchall()]
                cur.close()

                # c. Generate post text
                post = await text_generator.generate(topic, creator, tone, research)
                total_input_tokens += post.usage.get("inputTokens", 0)
                total_output_tokens += post.usage.get("outputTokens", 0)

                post_id = str(uuid.uuid4())

                # d/e. Generate + upload image (non-fatal on failure)
                image_url = None
                image_prompt = None
                try:
                    image_bytes, image_prompt = await image_generator.generate_for_post(
                        topic, creator, post.body
                    )
                    image_url = asset_store.upload_post_image(image_bytes, post_id)
                except Exception as e:
                    logger.warning(
                        f"Image generation failed for topic '{topic['name']}' — "
                        f"creating post without image: {e}"
                    )

                # f. Insert the post
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO content_posts
                       (id, creator_id, topic_id, body, image_url, image_prompt, tone, user_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (post_id, creator["id"], topic["id"], post.body, image_url, image_prompt,
                     tone, user_id),
                )

                # g. Bump topic usage
                cur.execute(
                    """UPDATE content_topics
                       SET used_count = used_count + 1, last_used_at = %s
                       WHERE id = %s AND user_id = %s""",
                    (datetime.now(timezone.utc), topic["id"], user_id),
                )
                conn.commit()
                cur.close()

                created += 1
                logger.info(
                    f"Created post {post_id} — creator='{creator['slug']}', "
                    f"tone={tone}, topic='{topic['name']}', image={'yes' if image_url else 'no'}"
                )
            except Exception as e:
                conn.rollback()
                failed += 1
                logger.error(f"Failed to create post for topic '{topic.get('name')}': {e}", exc_info=True)
    finally:
        conn.close()

    logger.info(
        f"generate_posts_batch completed. Created: {created}, Failed: {failed}, "
        f"Bedrock tokens: {total_input_tokens} in / {total_output_tokens} out"
    )
    return {
        "created": created,
        "failed": failed,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }
