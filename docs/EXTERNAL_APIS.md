# External API Dependencies

A complete list of the third-party APIs this project depends on, grouped by area,
with the reason each one is needed. Keep this aligned with the code — when an
integration is added or retired, update this file.

## AWS (via `boto3`)

| API | Why we need it |
|-----|----------------|
| AWS Bedrock (`bedrock-runtime`) | Core LLM + embeddings — Titan Embed v2 for memory (pgvector embeddings) and Claude for reasoning (email/bank/health analysis, content text generation) |
| AWS Polly | Text-to-speech narration for SIGNAL videos |
| AWS S3 | Object storage for generated images, audio, and video |
| AWS SES (`sesv2`) | Transactional email (password reset, email verification) |

## Content & Media Generation

| API | Why we need it |
|-----|----------------|
| ElevenLabs API | Voice/TTS narration + music generation (ARIA podcasts & music, video voiceover) |
| fal.ai | Image generation (FLUX — PULSE post images & SIGNAL slides) and Kling video model (STORIES cinematic long-form clips) |
| Replicate API | Wan2.1 video clip generation (SIGNAL + PULSE — high-volume, cost-efficient) |
| Suno API (`sunoapi.org`) | AI music generation (ARIA) |
| Google Gemini (`google-generativeai`) | Topic extraction from memory, research, and video-job content |

## Agents (Service B — `personal-intelligence-agents`)

| API | Why we need it |
|-----|----------------|
| Microsoft Graph API (`graph.microsoft.com`, `login.microsoftonline.com`) | Outlook email delta-sync & draft creation (email agent) + OneDrive file access |
| RapidAPI / JSearch | Job listings for the job-hunter agent |
| Yahoo Finance (`query1.finance.yahoo.com`) | Market data quotes for the trading agent |
| News feeds (Google News, Bloomberg, The Economist) | Financial/market news fetching (trading market_data + research) |
| LinkedIn | Job posting scraping (job-hunter agent) |

## Auth & Payments

| API | Why we need it |
|-----|----------------|
| Google OAuth (`accounts.google.com`, `oauth2.googleapis.com`) | Google sign-in for user authentication |
| Stripe API | Payments / subscription billing |

## Retired integrations

Referenced in code history but no longer active:

- **AWS Nova Canvas / Titan G2** image models — EOL'd / legacy-revoked in this
  account; replaced by fal.ai FLUX (see `src/private_internet/content/fal_image.py`).
