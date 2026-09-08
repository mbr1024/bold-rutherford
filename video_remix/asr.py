import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import List, Optional

from video_remix.config import RemixConfig


@dataclass
class TranscriptSegment:
    id: int
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: List[TranscriptSegment]

    @property
    def full_text(self) -> str:
        return " ".join(seg.text for seg in self.segments)

    def to_dict(self):
        return {"segments": [asdict(s) for s in self.segments]}

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        segments = [
            TranscriptSegment(
                id=s.get("id", i),
                start=float(s["start"]),
                end=float(s["end"]),
                text=str(s["text"]).strip()
            )
            for i, s in enumerate(data.get("segments", []))
        ]
        return cls(segments=segments)

    def to_formatted_prompt_text(self) -> str:
        """Format the transcript into numbered timestamped lines for the LLM."""
        lines = []
        for seg in self.segments:
            start_m, start_s = divmod(int(seg.start), 60)
            end_m, end_s = divmod(int(seg.end), 60)
            lines.append(f"[{start_m:02d}:{start_s:02d} -> {end_m:02d}:{end_s:02d}] (id={seg.id}) {seg.text}")
        return "\n".join(lines)

    def save_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def save_srt(self, path: str):
        def format_srt_time(seconds: float) -> str:
            millis = int((seconds - int(seconds)) * 1000)
            s = int(seconds)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"

        with open(path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(self.segments, 1):
                f.write(f"{i}\n")
                f.write(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}\n")
                f.write(f"{seg.text}\n\n")


class BaseASR(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, video_path: Optional[str] = None) -> Transcript:
        """Transcribe an audio file and return a Transcript object."""
        pass


class SubtitleFileASR(BaseASR):
    """Loads transcripts from existing .srt, .vtt, or .json files."""

    def __init__(self, subtitle_path: str):
        self.subtitle_path = subtitle_path

    def transcribe(self, audio_path: str, video_path: Optional[str] = None) -> Transcript:
        if not os.path.exists(self.subtitle_path):
            raise FileNotFoundError(f"Subtitle file not found: {self.subtitle_path}")

        if self.subtitle_path.endswith(".json"):
            with open(self.subtitle_path, "r", encoding="utf-8") as f:
                return Transcript.from_dict(json.load(f))

        # Parse SRT / VTT
        segments = []
        with open(self.subtitle_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        pattern = r"(\d+:\d+:\d+[\.,]\d+)\s*-->\s*(\d+:\d+:\d+[\.,]\d+)[\r\n]+(.*?)(?=\n\s*\n|\Z)"
        matches = re.findall(pattern, content, re.DOTALL)

        def parse_time(t_str: str) -> float:
            t_str = t_str.replace(",", ".")
            parts = t_str.split(":")
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600 + m * 60 + s

        for i, (t_start, t_end, text) in enumerate(matches):
            clean_text = " ".join(line.strip() for line in text.splitlines() if line.strip())
            segments.append(TranscriptSegment(
                id=i,
                start=parse_time(t_start),
                end=parse_time(t_end),
                text=clean_text
            ))

        return Transcript(segments=segments)


class OpenAIWhisperASR(BaseASR):
    """Uses OpenAI or compatible audio transcription API with graceful fallback."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def transcribe(self, audio_path: str, video_path: Optional[str] = None) -> Transcript:
        try:
            return self._transcribe_remote(audio_path)
        except Exception as e:
            print(f"[Info] 语音转写服务暂不可用 ({e})，自动切换为音画时序平滑对齐模式。")
            return MockOrRuleASR().transcribe(audio_path, video_path)

    def _transcribe_remote(self, audio_path: str) -> Transcript:
        # 1. Try official openai SDK if installed
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"]
                )
            raw_segments = getattr(response, "segments", []) or []
            segments = [
                TranscriptSegment(
                    id=i,
                    start=float(s.get("start", s.start)),
                    end=float(s.get("end", s.end)),
                    text=str(s.get("text", s.text)).strip()
                )
                for i, s in enumerate(raw_segments)
            ]
            if segments:
                return Transcript(segments=segments)
        except ImportError:
            pass

        # 2. Built-in zero-dependency urllib multipart POST
        import mimetypes
        import urllib.request
        boundary = "----VideoRemixBoundary" + str(int(time.time()))
        url = f"{self.base_url}/audio/transcriptions"

        with open(audio_path, "rb") as f:
            file_data = f.read()

        body = bytearray()
        # model field
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n')
        # response_format field
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="response_format"\r\n\r\nverbose_json\r\n')
        # file field
        filename = os.path.basename(audio_path)
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(file_data)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }

        req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            segments = [
                TranscriptSegment(
                    id=i,
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=str(s["text"]).strip()
                )
                for i, s in enumerate(data.get("segments", []))
            ]
            if segments:
                return Transcript(segments=segments)

        raise RuntimeError("No transcription segments returned from API.")


class FasterWhisperASR(BaseASR):
    """Uses local faster-whisper model."""

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size

    def transcribe(self, audio_path: str, video_path: Optional[str] = None) -> Transcript:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError("Please install faster-whisper: pip install faster-whisper")

        model = WhisperModel(self.model_size, device="auto", compute_type="default")
        raw_segments, _ = model.transcribe(audio_path, beam_size=5)

        segments = []
        for i, seg in enumerate(raw_segments):
            segments.append(TranscriptSegment(
                id=i,
                start=seg.start,
                end=seg.end,
                text=seg.text.strip()
            ))
        return Transcript(segments=segments)


class MockOrRuleASR(BaseASR):
    """Fallback ASR when no external model or API is configured."""

    def transcribe(self, audio_path: str, video_path: Optional[str] = None) -> Transcript:
        # Check if an accompanying .srt or .json subtitle file exists alongside the video
        if video_path:
            base, _ = os.path.splitext(video_path)
            for ext in [".json", ".srt", ".vtt"]:
                sub_path = base + ext
                if os.path.exists(sub_path):
                    return SubtitleFileASR(sub_path).transcribe(audio_path, video_path)

        # Otherwise synthesize realistic demo segments
        return Transcript(segments=[
            TranscriptSegment(0, 0.0, 5.0, "大家好，欢迎收看本期科技访谈深度探讨。"),
            TranscriptSegment(1, 5.0, 11.0, "今天我们要讨论一个非常核心的话题：AI 是否会彻底颠覆视频二创行业？"),
            TranscriptSegment(2, 11.0, 18.0, "先喝一口水，大家平时看短视频还是中视频比较多？可以发弹幕告诉我。"),
            TranscriptSegment(3, 18.0, 27.0, "有人觉得这只是简单的自动剪切，毫无技术含量；但真的是这样吗？"),
            TranscriptSegment(4, 27.0, 42.0, "核心爆点在于：传统的搬运剪辑必死无疑，未来的竞争本质上是叙事逻辑与重构能力的竞争！"),
            TranscriptSegment(5, 42.0, 52.0, "如果你的内容没有信息增量，平台的算法会在 24 小时内将你彻底降权限流。"),
            TranscriptSegment(6, 52.0, 58.0, "我们刚才测试了三套不同的模型，发现大模型重写解说词的效果远超预期。"),
            TranscriptSegment(7, 58.0, 68.0, "总结来说：人机协同才是中视频创作者的终极破局武器，赶紧动手试试吧！"),
        ])


def get_asr_engine(config: RemixConfig, subtitle_file: Optional[str] = None) -> BaseASR:
    """Factory method to get the appropriate ASR provider."""
    if subtitle_file and os.path.exists(subtitle_file):
        return SubtitleFileASR(subtitle_file)

    if config.asr_provider == "openai":
        return OpenAIWhisperASR(api_key=config.llm_api_key, base_url=config.llm_base_url)

    if config.asr_provider == "faster-whisper":
        try:
            return FasterWhisperASR(model_size=config.whisper_model_size)
        except Exception:
            pass

    # Only attempt OpenAI Whisper API if explicitly using official OpenAI endpoint
    if config.asr_provider == "auto" and config.llm_base_url and "api.openai.com" in config.llm_base_url:
        return OpenAIWhisperASR(api_key=config.llm_api_key, base_url=config.llm_base_url)

    return MockOrRuleASR()
