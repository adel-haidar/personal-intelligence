import json
import logging
import subprocess

import boto3

from personal_intelligence.config import get_settings

logger = logging.getLogger(__name__)

# Voices that are not available on the neural engine — fall back to standard.
NON_NEURAL_VOICES = {"Maxim", "Tatyana"}


class PollyEngine:
    """Synthesizes narration audio per script section via Amazon Polly."""

    def __init__(self):
        settings = get_settings()
        self.polly = boto3.client("polly", region_name=settings.aws_region)

    def synthesize_section(
        self,
        text: str,
        voice_id: str,
        language_code: str,
        output_path: str,
    ) -> int:
        """
        Synthesize `text` to an mp3 at `output_path`.
        Returns the audio duration in milliseconds.
        """
        engine = "standard" if voice_id in NON_NEURAL_VOICES else "neural"
        response = self.polly.synthesize_speech(
            Engine=engine,
            OutputFormat="mp3",
            VoiceId=voice_id,
            LanguageCode=language_code,
            TextType="text",
            Text=text,
        )
        with open(output_path, "wb") as f:
            f.write(response["AudioStream"].read())
        return self._probe_duration_ms(output_path)

    @staticmethod
    def _probe_duration_ms(audio_path: str) -> int:
        """Read the mp3 duration with ffprobe (ships with ffmpeg)."""
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                audio_path,
            ],
            check=True,
            capture_output=True,
        )
        duration_s = float(json.loads(result.stdout)["format"]["duration"])
        return int(duration_s * 1000)

    def get_total_duration(self, section_durations: list[int]) -> int:
        """Sum of all section durations in ms."""
        return sum(section_durations)
