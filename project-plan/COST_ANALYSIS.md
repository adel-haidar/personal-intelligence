# Cost Analysis — AI Content Platform
## personal-intelligence / PULSE + SIGNAL

---

## Monthly Volume Assumptions

| Content Type | Volume | Frequency |
|-------------|--------|-----------|
| Posts (PULSE) | ~60/month | 3× per day |
| Videos (SIGNAL) | ~30/month | 1× per day |
| Topic extractions | ~30/month | 1× per day |

---

## Per-Unit Cost Breakdown

### Post Generation (1 post)

| Step | Service | Input | Cost |
|------|---------|-------|------|
| Text generation | Bedrock Claude Haiku | ~600 tokens | $0.00045 |
| Image prompt generation | Bedrock Claude Haiku | ~200 tokens | $0.00015 |
| Image generation | Bedrock Nova Canvas (standard, 1024×1024) | 1 image | $0.040 |
| S3 upload | S3 | ~200KB | $0.000005 |
| **Total per post** | | | **~$0.041** |

### Video Generation (1 video, ~120s)

| Step | Service | Input | Cost |
|------|---------|-------|------|
| Script generation | Bedrock Claude Haiku | ~800 tokens | $0.0006 |
| Image prompt gen | Bedrock Claude Haiku | ~300 tokens | $0.0002 |
| 5 images (1280×720) | Bedrock Nova Canvas (standard) | 5 images | $0.200 |
| TTS narration | Amazon Polly Neural | ~1800 chars × 5 | $0.014 |
| FFmpeg assembly | EC2 (existing) | CPU time | $0.000 |
| S3 upload | S3 | ~30MB MP4 | $0.0007 |
| **Total per video** | | | **~$0.215** |

### Topic Intelligence (1 run)

| Step | Service | Input | Cost |
|------|---------|-------|------|
| MCP memory read | self-hosted | HTTP call | $0.000 |
| Topic extraction | Bedrock Claude Haiku | ~1200 tokens | $0.0009 |
| Web research | Gemini 2.0 Flash (5 topics × 1 call) | ~5000 tokens | $0.0004 |
| **Total per run** | | | **~$0.001** |

---

## Monthly Cost Summary

| Item | Volume | Unit cost | Monthly cost |
|------|--------|-----------|-------------|
| Posts — Haiku text | 60 | $0.00060 | $0.036 |
| Posts — Nova Canvas image | 60 | $0.040 | $2.40 |
| Videos — Haiku script | 30 | $0.0008 | $0.024 |
| Videos — Nova Canvas images (5×) | 150 | $0.040 | $6.00 |
| Videos — Polly TTS | 30 | $0.014 | $0.42 |
| Videos — S3 storage (30 × 30MB) | 900MB | $0.023/GB | $0.021 |
| Topic intelligence | 30 runs | $0.001 | $0.030 |
| S3 images storage (~60 × 200KB) | 12MB | $0.023/GB | $0.0003 |
| CloudFront data transfer (est. 5GB) | 5GB | $0.010/GB | $0.050 |
| SQS messages | ~300 | free tier | $0.000 |
| EventBridge rules | 3 rules | free | $0.000 |
| **TOTAL** | | | **~$9.00/month** |

**Converted: ~€8.30/month** at current rates.

---

## Cost Control Rules

1. **Nova Canvas standard quality only** — never use `premium`. Difference is barely noticeable for editorial style.
2. **1 video/day max by default** — can increase via manual trigger only.
3. **Haiku for all generation** — never use Claude Sonnet/Opus for automated content.
4. **5-section videos only** — no padding to make videos longer.
5. **Skip image if topic has been used in last 24h** — reuse existing research.
6. **Polly `standard` engine for non-neural voices** (Maxim, Tatyana) — free tier covers 5M chars/month for standard.

---

## Cost at Scale

| Scenario | Monthly cost |
|----------|-------------|
| Current plan (60 posts, 30 videos) | ~€8 |
| 2× videos (60 videos/month) | ~€14 |
| 5× videos (150 videos/month) | ~€36 |
| Break-even vs. Runway AI (1 video) | N/A — Runway is $50+/month for 5 videos |

---

## What Was Rejected and Why

| Option | Why rejected |
|--------|-------------|
| Runway ML / Sora | $50–200/month, no AWS integration |
| Stable Diffusion on EC2 GPU | g4dn.xlarge = ~$100/month, not worth it |
| OpenAI DALL-E 3 | ~$0.08/image vs $0.04 Nova Canvas |
| AWS MediaConvert | Overkill — FFmpeg on existing EC2 is free |
| Separate Elasticsearch | PostgreSQL + pgvector already handles similarity |
| HeyGen / Synthesia | $30+/month, faces/avatars = uncanny valley |

---

## Future Cost Optimizations (not needed now)

- **S3 Lifecycle rules**: Move videos older than 90 days to S3 Glacier Instant (~$0.004/GB vs $0.023/GB)
- **Bedrock Batch Inference**: 50% discount for non-realtime requests
- **Polly SSML caching**: If same script section generated again, serve cached MP3
