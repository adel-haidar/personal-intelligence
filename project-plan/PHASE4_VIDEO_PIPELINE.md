# PHASE 4 — Video Generation Pipeline (SIGNAL)
## Agent: Claude Code
## Depends on: Phase 1 (models), Phase 2 (topics), Phase 3 (AssetStore reuse)

---

## Goal
Build a narrated-slideshow video pipeline:
**Script → 4 Images (Nova Canvas) → Narration (Amazon Polly) → Assembly (FFmpeg) → S3**

This keeps video generation cost at ~€0.15–0.25/video with zero external video AI services.

---

## Video Format Spec

| Property | Value |
|----------|-------|
| Resolution | 1280×720 (HD) |
| Frame rate | 24fps |
| Duration | 90–150 seconds |
| Structure | 4 image slides, ~25–35s each, Ken Burns pan/zoom |
| Audio | Polly Neural TTS narration + subtle ambient tone (silence is also fine) |
| Codec | H.264 / AAC |
| Output | MP4 |

---

## Task 1 — Script Generator

Create: `backend/app/content/video_generator.py`

### Class: `VideoScriptGenerator`

Uses **Bedrock Claude Haiku**, `temperature=0`.

```python
class VideoScriptGenerator:
    async def generate(
        self,
        topic: ContentTopic,
        creator: ContentCreator,
        research: list[ContentResearch]
    ) -> VideoScript:
        """
        System: "{creator.style_prompt}
        
        You are writing a narration script for a short video (90–120 seconds spoken at normal pace ≈ 150 words/minute, so target 225–300 words total).
        
        Structure EXACTLY:
        - INTRO (1 sentence hook, 15–20 words)
        - SECTION_1: first key point (60–80 words)
        - SECTION_2: second key point (60–80 words)
        - SECTION_3: third key point or counterpoint (60–80 words)  
        - OUTRO (closing thought + 1 relevant URL if available, 20–30 words)
        
        Use research facts where relevant. Cite URLs naturally ('according to Reuters...' style).
        Output ONLY valid JSON:
        {
          'title': str,
          'sections': [
            {'id': 'INTRO', 'text': str, 'image_prompt': str},
            {'id': 'SECTION_1', 'text': str, 'image_prompt': str},
            {'id': 'SECTION_2', 'text': str, 'image_prompt': str},
            {'id': 'SECTION_3', 'text': str, 'image_prompt': str},
            {'id': 'OUTRO', 'text': str, 'image_prompt': str}
          ],
          'description': str  (2-sentence video description)
        }"
        
        User: "Topic: {topic.name}
        Research: {research_text}"
        """
```

### Dataclass: `VideoScript`
```python
@dataclass
class ScriptSection:
    id: str
    text: str
    image_prompt: str

@dataclass
class VideoScript:
    title: str
    description: str
    sections: list[ScriptSection]   # always 5 sections in order above
```

---

## Task 2 — Video Image Generator

In `video_generator.py`:

### Class: `VideoImageGenerator`

Reuses `PostImageGenerator` logic but with video-specific sizing:

```python
class VideoImageGenerator:
    async def generate_for_section(
        self,
        section: ScriptSection,
        creator: ContentCreator
    ) -> bytes:
        """
        Nova Canvas request:
        - width: 1280, height: 720   (16:9 for video)
        - quality: "standard"
        - prompt: section.image_prompt + " cinematic, 16:9, dark editorial style, no text"
        - negativeText: "text, watermark, logo, people's faces, blurry"
        """

    async def generate_thumbnail(self, script: VideoScript, creator: ContentCreator) -> bytes:
        """
        Generate a 1280x720 thumbnail using the INTRO section image_prompt
        + "bold title overlay style, high contrast" appended.
        This is the image shown in the video card before playback.
        """
```

---

## Task 3 — Polly TTS Engine

Create: `backend/app/content/polly_engine.py`

```python
import boto3

class PollyEngine:
    def __init__(self):
        self.polly = boto3.client("polly", region_name="eu-central-1")

    def synthesize_section(
        self,
        text: str,
        voice_id: str,
        language_code: str,
        output_path: str
    ) -> int:
        """
        Call Polly SynthesizeSpeech:
        - Engine: "neural"
        - OutputFormat: "mp3"
        - VoiceId: voice_id
        - LanguageCode: language_code
        - TextType: "text"
        
        Save mp3 to output_path.
        Return duration in milliseconds (parse from response AudioStream).
        Note: Polly Neural supports most voices. If voice_id is "Maxim" (Russian),
        use Engine="standard" as Maxim is not neural. Add a helper dict:
        NON_NEURAL_VOICES = {"Maxim", "Tatyana"}
        """

    def get_total_duration(self, section_durations: list[int]) -> int:
        """Sum of all section durations in ms."""
```

---

## Task 4 — FFmpeg Video Assembler

Create: `backend/app/content/ffmpeg_assembler.py`

FFmpeg must be installed on EC2: `sudo apt install ffmpeg -y`

### Class: `VideoAssembler`

```python
import subprocess
import tempfile

class VideoAssembler:
    def assemble(
        self,
        sections: list[ScriptSection],
        image_paths: list[str],          # one per section
        audio_paths: list[str],          # one mp3 per section
        output_path: str
    ) -> int:
        """
        For each section: create a video clip with Ken Burns effect.
        Then concatenate all clips into final MP4.
        
        Ken Burns FFmpeg filter per image:
        -vf "scale=1280:720,zoompan=z='if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))':d={duration_frames}:s=1280x720"
        
        Duration per section = audio_duration_ms / 1000 * 24 frames
        
        Steps:
        1. For each section i:
           ffmpeg -loop 1 -i {image_paths[i]} -i {audio_paths[i]}
                  -vf "zoompan=..." -c:v libx264 -c:a aac
                  -shortest {temp_dir}/section_{i}.mp4
        
        2. Write concat file:
           file 'section_0.mp4'
           file 'section_1.mp4'
           ...
        
        3. ffmpeg -f concat -safe 0 -i concat.txt -c copy {output_path}
        
        Return total duration in seconds.
        
        Use subprocess.run(..., check=True, capture_output=True).
        On failure: log stderr and raise VideoAssemblyError.
        """
```

---

## Task 5 — Video Pipeline Orchestrator

Create: `backend/app/content/jobs/video_job.py`

```python
async def generate_video(db: Session, topic_id: str = None) -> str:
    """
    Full pipeline. Returns video_id on success.
    
    1. Select topic (by topic_id or highest weight unused in last 7 days for video)
    2. Select creator via CreatorSelector
    3. Create content_videos record with status='processing'
    4. VideoScriptGenerator.generate()  ← script + image prompts
    5. VideoImageGenerator.generate_for_section() for each of 5 sections (parallel)
    6. VideoImageGenerator.generate_thumbnail()
    7. Save all images to /tmp/{video_id}/img_{i}.jpg
    8. PollyEngine.synthesize_section() for each section (sequential, Polly rate limits)
    9. Save all audio to /tmp/{video_id}/audio_{i}.mp3
    10. VideoAssembler.assemble() → /tmp/{video_id}/video.mp4
    11. AssetStore.upload_video() → CF URL
    12. AssetStore.upload_thumbnail() → CF URL
    13. Update content_videos: status='ready', video_url, thumbnail_url, duration_seconds, script
    14. Update topic: used_count, last_used_at
    15. Cleanup /tmp/{video_id}/
    16. Return video_id
    
    On any exception: set status='failed', log error, re-raise
    """

async def generate_videos_batch(db: Session, count: int = 2):
    """Run generate_video() `count` times sequentially (not parallel — FFmpeg is CPU-bound)."""
```

---

## Task 6 — Admin Endpoint

Add to router:

```python
POST /api/content/jobs/videos/run
Body: { "count": int, "topic_id": str | null }
```

---

## System Dependencies on EC2

Add to deployment notes / `CLAUDE.md`:
```bash
# Required system packages
sudo apt install ffmpeg -y

# Verify
ffmpeg -version
```

---

## Environment Variables Required

No new ones — reuses S3_CONTENT_BUCKET, CLOUDFRONT_BASE_URL from Phase 3.

---

## Cost per Video (30-second test video estimate)

| Step | API | Approx cost |
|------|-----|------------|
| Script (Haiku, ~400 tokens in+out) | Bedrock | $0.002 |
| 5 images 1280×720 (Nova Canvas standard) | Bedrock | $0.20 |
| TTS ~280 words (~1800 chars) × 5 sections | Polly Neural | $0.014 |
| FFmpeg assembly | EC2 CPU | $0.000 |
| S3 upload + CF | AWS | ~$0.001 |
| **Total** | | **~€0.22** |

10 videos/month ≈ **€2.20** — well within budget.

---

## Completion Criteria
- [ ] `generate_video()` produces a valid MP4 in S3
- [ ] Video plays in browser from CloudFront URL
- [ ] Audio narration matches slide content
- [ ] Ken Burns zoom effect is visible
- [ ] Video duration is 90–150 seconds
- [ ] `content_videos.status` transitions correctly: pending → processing → ready
- [ ] `/tmp` cleanup happens even on failure
- [ ] Two different creators produce noticeably different narration voices
