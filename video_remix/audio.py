import json
import os
import re
import subprocess
from typing import Optional


class MediaHelper:
    """Helper utilities for probing and extracting audio from video files using FFmpeg."""

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def get_duration(self, file_path: str) -> float:
        """Get the duration of a media file in seconds."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Try ffprobe with JSON output first
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            data = json.loads(result.stdout)
            duration_str = data.get("format", {}).get("duration")
            if duration_str:
                return float(duration_str)
        except Exception:
            pass

        # Fallback to parsing ffmpeg stderr output
        try:
            cmd = [self.ffmpeg_path, "-i", file_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            # Match "Duration: 00:01:23.45"
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", result.stderr)
            if match:
                hours, minutes, seconds = match.groups()
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception as e:
            raise RuntimeError(f"Failed to determine media duration for {file_path}: {e}")

        raise RuntimeError(f"Could not parse duration from {file_path}")

    def extract_audio(
        self,
        video_path: str,
        output_audio_path: Optional[str] = None,
        sample_rate: int = 16000,
        channels: int = 1
    ) -> str:
        """Extract a 16kHz mono WAV audio track suitable for ASR models (Whisper)."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if output_audio_path is None:
            base, _ = os.path.splitext(video_path)
            output_audio_path = f"{base}_audio.wav"

        os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)

        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            "-i", video_path,
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            output_audio_path
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")

        return output_audio_path
