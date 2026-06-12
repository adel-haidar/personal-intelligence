# PHASE 3 — Post Generation Pipeline (PULSE)
## Agent: Claude Code
## Depends on: Phase 1 (models), Phase 2 (topics must exist in DB)

---

## Goal
Build the pipeline that takes a topic from the DB, selects an appropriate creator persona, generates a text post + image via AWS Bedrock, stores assets in S3, and writes the final post record to `content_posts`.

---

## Task 1 — Creator Selector

Create: `backend/app/content/creator_selector.py`

### Class: `CreatorSelector`

```python
class CreatorSelector:
    def select_for_topic(self, db: Session, topic: ContentTopic) -> ContentCreator:
        """
        Logic:
        1. Filter active creators (is_active=True, score >= 0.3)
        2. Score each creator by:
           - topic_affinity_match: count of topic keywords in creator.topic_affinities
           - creator.score (RL weight)
           - recency penalty: if creator posted about same topic in last 7 days → -0.5
        3. Add slight randomness: multiply each score by random.uniform(0.85, 1.0)
           (prevents the same creator dominating, simulates editorial variety)
        4. Return top scorer
        5. Fallback: if no creator scores > 0.1, return highest overall score creator
        """

    def select_tone(self, creator: ContentCreator, topic: ContentTopic) -> str:
        """
        Assign tone based on creator personality:
        - Maksim Volkov → 'satirical' or 'critical'
        - Dr. Layla Nasser → 'informative' or 'critical'
        - Felix Bergmann → 'satirical' or 'supportive'
        - Nora Chen → 'supportive' or 'informative'
        - Viktor Ostrowski → 'satirical'
        Add randomness: 20% chance of flipping to a different valid tone.
        """
```

---

## Task 2 — Text Post Generator

Create: `backend/app/content/post_generator.py`

### Class: `PostTextGenerator`

Uses **AWS Bedrock Claude Haiku** (`anthropic.claude-haiku-4-5` or latest Haiku on Bedrock).
`temperature=0.7` (slight creativity is fine for posts — not financial data).

```python
class PostTextGenerator:
    def __init__(self):
        self.bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

    async def generate(
        self,
        topic: ContentTopic,
        creator: ContentCreator,
        tone: str,
        research: list[ContentResearch]
    ) -> GeneratedPost:
        """
        Prompt structure:
        
        System: "{creator.style_prompt}
        
        You are writing a single social media post. 
        Tone: {tone}.
        Keep it under 300 words.
        You may include 1–2 relevant links from the research provided.
        Do NOT add hashtags unless they feel natural for this creator's voice.
        Output ONLY the post text, no labels or preamble."
        
        User: "Write a post about: {topic.name}
        
        Background research:
        {chr(10).join([f'- {r.title}: {r.summary} ({r.url})' for r in research[:3]])}
        
        Write the post now."
        
        Parse response → return GeneratedPost(body=str, referenced_urls=list[str])
        """
```

### Dataclass: `GeneratedPost`
```python
@dataclass
class GeneratedPost:
    body: str
    referenced_urls: list[str]   # URLs mentioned inline in the body
```

---

## Task 3 — Image Generator

Create: `backend/app/content/image_generator.py`

Uses **AWS Bedrock Nova Canvas** (`amazon.nova-canvas-v1:0`).

```python
class PostImageGenerator:
    async def generate_for_post(
        self,
        topic: ContentTopic,
        creator: ContentCreator,
        post_body: str
    ) -> tuple[bytes, str]:
        """
        First: generate an image prompt using Haiku:
        
        System: "Generate a single image prompt for a social media post image.
        Style: dark, editorial, high-contrast. No text in image.
        Creator aesthetic: {creator.style_prompt[:100]}
        Output ONLY the image prompt, 1–2 sentences."
        
        User: "Topic: {topic.name}. Post excerpt: {post_body[:150]}"
        
        Then: call Nova Canvas with the generated prompt.
        
        Nova Canvas request body:
        {
          "taskType": "TEXT_IMAGE",
          "textToImageParams": {
            "text": <generated_prompt>,
            "negativeText": "text, watermark, logo, blurry, low quality"
          },
          "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 1024,
            "width": 1024,
            "quality": "standard"   ← use standard, not premium, to save cost
          }
        }
        
        Return (image_bytes: bytes, image_prompt: str)
        """
```

---

## Task 4 — S3 Upload Service

Create: `backend/app/content/asset_store.py`

```python
class AssetStore:
    BUCKET = os.getenv("S3_CONTENT_BUCKET")  # new env var, same bucket or new prefix
    CDN_BASE = os.getenv("CLOUDFRONT_BASE_URL")

    def upload_post_image(self, image_bytes: bytes, post_id: str) -> str:
        """
        Key: content/posts/{post_id}/image.jpg
        ContentType: image/jpeg
        CacheControl: max-age=31536000
        Returns full CloudFront URL.
        """

    def upload_video(self, video_path: str, video_id: str) -> str:
        """
        Key: content/videos/{video_id}/video.mp4
        ContentType: video/mp4
        Returns full CloudFront URL.
        (Used in Phase 4)
        """

    def upload_thumbnail(self, image_bytes: bytes, video_id: str) -> str:
        """
        Key: content/videos/{video_id}/thumbnail.jpg
        Returns full CloudFront URL.
        """
```

---

## Task 5 — Post Pipeline Orchestrator

Create: `backend/app/content/jobs/post_job.py`

```python
async def generate_posts_batch(db: Session, count: int = 3):
    """
    1. Query content_topics ordered by weight DESC, last_used_at ASC (prefer untouched high-weight topics)
    2. Take top `count` topics
    3. For each topic:
       a. CreatorSelector.select_for_topic()
       b. CreatorSelector.select_tone()
       c. PostTextGenerator.generate()
       d. PostImageGenerator.generate_for_post()
       e. AssetStore.upload_post_image()
       f. Insert into content_posts
       g. Update topic.used_count += 1, topic.last_used_at = now()
    4. Log: N posts created, total Bedrock tokens used (from response metadata)
    """
```

---

## Task 6 — Admin Endpoint

Add to router:

```python
POST /api/content/jobs/posts/run
Body: { "count": int }   # default 3
```

Same internal auth as Phase 2 (`X-Internal-Secret`).

---

## Environment Variables Required

```
S3_CONTENT_BUCKET=personal-intelligence-content
CLOUDFRONT_BASE_URL=https://d<id>.cloudfront.net
```

(CloudFront distribution should serve the new bucket prefix. If using existing distribution, add a new origin path `/content/*`.)

---

## Completion Criteria
- [ ] `generate_posts_batch(db, count=3)` runs end-to-end
- [ ] 3 posts in `content_posts` with real body text
- [ ] Each post has a valid CloudFront `image_url`
- [ ] Images are visually coherent (dark, editorial style)
- [ ] `GET /api/content/posts` returns posts with creator + topic data (use joins)
- [ ] Post bodies are distinctly different in voice (creator style_prompt is working)
- [ ] No hardcoded AWS credentials — uses IAM role on EC2
