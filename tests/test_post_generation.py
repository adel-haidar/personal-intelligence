import base64
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from private_internet.content.creator_selector import CreatorSelector, ALL_TONES, _TONE_MAP
from private_internet.content.post_generator import PostTextGenerator, GeneratedPost
from private_internet.content.image_generator import PostImageGenerator
from private_internet.content.asset_store import AssetStore
from private_internet.content.jobs.post_job import generate_posts_batch


# ── Fixtures ───────────────────────────────────────────────────

def _creator(slug="felix-bergmann", score=0.7, affinities=None, creator_id=None):
    return {
        "id": creator_id or str(uuid.uuid4()),
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "style_prompt": "Write like a frustrated German engineer.",
        "topic_affinities": affinities if affinities is not None else ["Germany", "startup", "tech jobs"],
        "score": score,
        "is_active": True,
    }


def _topic(name="Relocating to Switzerland as a German engineer", keywords=None):
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "slug": "relocating-to-switzerland",
        "keywords": keywords if keywords is not None else ["Switzerland", "Germany", "relocation"],
        "weight": 0.8,
    }


def _mock_db(creators, recent_creator_ids=None):
    """Connection whose cursor returns `creators` then recent-post creator ids."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        creators,
        [{"creator_id": cid} for cid in (recent_creator_ids or [])],
    ]
    conn.cursor.return_value = cursor
    return conn


# ── CreatorSelector ────────────────────────────────────────────

class TestCreatorSelector:
    def test_selects_creator_with_matching_affinities(self):
        selector = CreatorSelector()
        match = _creator("felix-bergmann", score=0.5, affinities=["Germany", "Switzerland"])
        no_match = _creator("nora-chen", score=0.5, affinities=["gym", "nutrition"])
        db = _mock_db([match, no_match])

        result = selector.select_for_topic(db, _topic())
        assert result["slug"] == "felix-bergmann"

    def test_recency_penalty_demotes_recent_poster(self):
        selector = CreatorSelector()
        recent = _creator("felix-bergmann", score=0.6, affinities=["Germany", "Switzerland"])
        fresh = _creator("viktor-ostrowski", score=0.6, affinities=["Germany", "Switzerland"])
        db = _mock_db([recent, fresh], recent_creator_ids=[recent["id"]])

        # Randomness is bounded (0.85–1.0) so the 0.5 penalty always dominates
        result = selector.select_for_topic(db, _topic())
        assert result["slug"] == "viktor-ostrowski"

    def test_fallback_to_highest_score_when_no_match(self):
        selector = CreatorSelector()
        # No affinity overlap and tiny RL scores → best score <= 0.1 → fallback
        weak = _creator("nora-chen", score=0.05, affinities=["gym"])
        strong = _creator("dr-layla-nasser", score=0.08, affinities=["banking"])
        db = _mock_db([weak, strong])

        result = selector.select_for_topic(db, _topic(keywords=["unrelated"], name="xyz"))
        assert result["slug"] == "dr-layla-nasser"

    def test_select_tone_returns_valid_tone(self):
        selector = CreatorSelector()
        creator = _creator("viktor-ostrowski")
        for _ in range(50):
            tone = selector.select_tone(creator, _topic())
            assert tone in ALL_TONES

    def test_tone_map_covers_all_seeded_creators(self):
        for slug, tones in _TONE_MAP.items():
            assert tones, f"{slug} has no tones"
            assert all(t in ALL_TONES for t in tones)


# ── PostTextGenerator ──────────────────────────────────────────

class TestPostTextGenerator:
    @pytest.mark.anyio
    async def test_generate_returns_body_and_urls(self):
        body_text = (
            "Switzerland pays double. Germany has Ämter. You do the math.\n"
            "More here: https://example.com/swiss-salaries"
        )
        with patch(
            "private_internet.content.post_generator.converse_text",
            new=AsyncMock(return_value=(body_text, {"inputTokens": 100, "outputTokens": 50})),
        ):
            generator = PostTextGenerator()
            research = [{"title": "Swiss salaries", "summary": "High.", "url": "https://example.com/swiss-salaries"}]
            post = await generator.generate(_topic(), _creator(), "satirical", research)

        assert isinstance(post, GeneratedPost)
        assert "Switzerland" in post.body
        assert post.referenced_urls == ["https://example.com/swiss-salaries"]
        assert post.usage["inputTokens"] == 100

    @pytest.mark.anyio
    async def test_generate_passes_creator_style_and_tone(self):
        mock_converse = AsyncMock(return_value=("post", {}))
        with patch("private_internet.content.post_generator.converse_text", new=mock_converse):
            generator = PostTextGenerator()
            await generator.generate(_topic(), _creator(), "critical", [])

        kwargs = mock_converse.call_args.kwargs
        assert "frustrated German engineer" in kwargs["system_prompt"]
        assert "Tone: critical" in kwargs["system_prompt"]
        assert kwargs["temperature"] == 0.7


# ── PostImageGenerator ─────────────────────────────────────────

class TestPostImageGenerator:
    @pytest.mark.anyio
    async def test_generate_for_post(self):
        fake_png = b"\x89PNG fake image bytes"
        nova_response = {"images": [base64.b64encode(fake_png).decode()]}

        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(nova_response).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch(
            "private_internet.content.image_generator.converse_text",
            new=AsyncMock(return_value=("A dark editorial photo of the Alps.", {})),
        ), patch("private_internet.content.image_generator.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            generator = PostImageGenerator()
            image_bytes, image_prompt = await generator.generate_for_post(
                _topic(), _creator(), "Some post body"
            )

        assert image_bytes == fake_png
        assert "Alps" in image_prompt
        request = json.loads(mock_client.invoke_model.call_args.kwargs["body"])
        assert request["taskType"] == "TEXT_IMAGE"
        assert request["imageGenerationConfig"]["quality"] == "standard"

    @pytest.mark.anyio
    async def test_raises_when_no_images_returned(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"images": [], "error": "blocked"}).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch(
            "private_internet.content.image_generator.converse_text",
            new=AsyncMock(return_value=("prompt", {})),
        ), patch("private_internet.content.image_generator.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_client
            generator = PostImageGenerator()
            with pytest.raises(RuntimeError):
                await generator.generate_for_post(_topic(), _creator(), "body")


# ── AssetStore ─────────────────────────────────────────────────

class TestAssetStore:
    def test_upload_post_image_returns_cdn_url(self, monkeypatch):
        monkeypatch.setenv("S3_CONTENT_BUCKET", "test-bucket")
        monkeypatch.setenv("CLOUDFRONT_BASE_URL", "https://cdn.example.com/")
        with patch("private_internet.content.asset_store.boto3") as mock_boto3:
            mock_s3 = MagicMock()
            mock_boto3.client.return_value = mock_s3
            store = AssetStore()
            url = store.upload_post_image(b"bytes", "post-123")

        assert url == "https://cdn.example.com/content/posts/post-123/image.png"
        put_kwargs = mock_s3.put_object.call_args.kwargs
        assert put_kwargs["Bucket"] == "test-bucket"
        assert put_kwargs["ContentType"] == "image/png"
        assert put_kwargs["CacheControl"] == "max-age=31536000"

    def test_missing_bucket_raises(self, monkeypatch):
        monkeypatch.delenv("S3_CONTENT_BUCKET", raising=False)
        monkeypatch.setenv("CLOUDFRONT_BASE_URL", "https://cdn.example.com")
        with pytest.raises(RuntimeError):
            AssetStore()


# ── generate_posts_batch ───────────────────────────────────────

class TestGeneratePostsBatch:
    @pytest.mark.anyio
    async def test_end_to_end_batch(self):
        topic = _topic()
        creator = _creator()

        conn = MagicMock()
        cursor = MagicMock()
        # 1st fetchall: topics query; 2nd: research query
        cursor.fetchall.side_effect = [[topic], [{"title": "t", "summary": "s", "url": "https://u"}]]
        conn.cursor.return_value = cursor

        mock_selector = MagicMock()
        mock_selector.select_for_topic.return_value = creator
        mock_selector.select_tone.return_value = "satirical"

        mock_text_gen = MagicMock()
        mock_text_gen.generate = AsyncMock(
            return_value=GeneratedPost(body="post body", referenced_urls=[], usage={"inputTokens": 10, "outputTokens": 5})
        )
        mock_image_gen = MagicMock()
        mock_image_gen.generate_for_post = AsyncMock(return_value=(b"img", "prompt"))
        mock_store = MagicMock()
        mock_store.upload_post_image.return_value = "https://cdn/content/posts/x/image.png"

        with patch("private_internet.content.jobs.post_job._connect", return_value=conn), \
             patch("private_internet.content.jobs.post_job.CreatorSelector", return_value=mock_selector), \
             patch("private_internet.content.jobs.post_job.PostTextGenerator", return_value=mock_text_gen), \
             patch("private_internet.content.jobs.post_job.PostImageGenerator", return_value=mock_image_gen), \
             patch("private_internet.content.jobs.post_job.AssetStore", return_value=mock_store):
            result = await generate_posts_batch(count=1, user_id="u1")

        assert result["created"] == 1
        assert result["failed"] == 0
        assert result["input_tokens"] == 10
        conn.commit.assert_called()
        # Verify the post INSERT carried the image URL and tone
        insert_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO content_posts" in c.args[0]]
        assert len(insert_calls) == 1
        params = insert_calls[0].args[1]
        assert params[3] == "post body"
        assert params[4] == "https://cdn/content/posts/x/image.png"
        assert params[6] == "satirical"

    @pytest.mark.anyio
    async def test_image_failure_is_non_fatal(self):
        topic = _topic()
        creator = _creator()

        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.side_effect = [[topic], []]
        conn.cursor.return_value = cursor

        mock_selector = MagicMock()
        mock_selector.select_for_topic.return_value = creator
        mock_selector.select_tone.return_value = "informative"

        mock_text_gen = MagicMock()
        mock_text_gen.generate = AsyncMock(return_value=GeneratedPost(body="body", referenced_urls=[], usage={}))
        mock_image_gen = MagicMock()
        mock_image_gen.generate_for_post = AsyncMock(side_effect=RuntimeError("nova down"))

        with patch("private_internet.content.jobs.post_job._connect", return_value=conn), \
             patch("private_internet.content.jobs.post_job.CreatorSelector", return_value=mock_selector), \
             patch("private_internet.content.jobs.post_job.PostTextGenerator", return_value=mock_text_gen), \
             patch("private_internet.content.jobs.post_job.PostImageGenerator", return_value=mock_image_gen), \
             patch("private_internet.content.jobs.post_job.AssetStore", return_value=MagicMock()):
            result = await generate_posts_batch(count=1, user_id="u1")

        assert result["created"] == 1
        insert_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO content_posts" in c.args[0]]
        params = insert_calls[0].args[1]
        assert params[4] is None  # image_url NULL

    @pytest.mark.anyio
    async def test_no_topics_returns_zero(self):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn.cursor.return_value = cursor

        with patch("private_internet.content.jobs.post_job._connect", return_value=conn), \
             patch("private_internet.content.jobs.post_job.AssetStore", return_value=MagicMock()):
            result = await generate_posts_batch(count=3, user_id="u1")

        assert result == {"created": 0, "failed": 0}
