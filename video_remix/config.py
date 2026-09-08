import os
import shutil
from dataclasses import dataclass, field
from typing import Optional


def load_dotenv_if_exists():
    """Automatically load environment variables from .env or user config without external dependencies."""
    search_paths = [
        os.path.abspath(".env"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")),
        os.path.expanduser("~/.config/video_remix/config.env"),
        os.path.expanduser("~/.video_remix.env")
    ]
    for p in search_paths:
        if os.path.exists(p) and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key and key not in os.environ:
                            os.environ[key] = val
                break
            except Exception:
                pass


# Auto-load on module import
load_dotenv_if_exists()


def _resolve_llm_api_key() -> Optional[str]:
    provider = os.environ.get("ACTIVE_PROVIDER", "").lower()
    if provider in ("gemini_relay", "openlux", "gemini"):
        return os.environ.get("GEMINI_RELAY_API_KEY") or os.environ.get("OPENAI_API_KEY")
    elif provider in ("dashscope", "qwen", "bailian"):
        return os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    return (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GEMINI_RELAY_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )


def _resolve_llm_base_url() -> Optional[str]:
    provider = os.environ.get("ACTIVE_PROVIDER", "").lower()
    if provider in ("gemini_relay", "openlux", "gemini"):
        return os.environ.get("GEMINI_RELAY_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openlux.ai/v1"
    elif provider in ("dashscope", "qwen", "bailian"):
        return os.environ.get("DASHSCOPE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_BASE_URL")


def _resolve_llm_model() -> str:
    provider = os.environ.get("ACTIVE_PROVIDER", "").lower()
    if provider in ("gemini_relay", "openlux", "gemini"):
        return os.environ.get("GEMINI_RELAY_MODEL") or os.environ.get("LLM_MODEL") or "gemini-3.7-flash"
    elif provider in ("dashscope", "qwen", "bailian"):
        return os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-vl-plus"
    return os.environ.get("LLM_MODEL", "gemini-3.7-flash")


@dataclass
class RemixConfig:
    """Global configuration for the Video Remix Pipeline."""

    # Path to ffmpeg binary
    ffmpeg_path: str = field(
        default_factory=lambda: os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
    )
    ffprobe_path: str = field(
        default_factory=lambda: os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"
    )

    # Active provider selection ('gemini_relay', 'dashscope', etc.)
    active_provider: str = field(
        default_factory=lambda: os.environ.get("ACTIVE_PROVIDER", "gemini_relay")
    )

    # LLM API configuration (OpenAI-compatible: supports OpenAI, DeepSeek, Qwen, Moonshot, OpenLux Gemini, etc.)
    llm_api_key: Optional[str] = field(default_factory=_resolve_llm_api_key)
    llm_base_url: Optional[str] = field(default_factory=_resolve_llm_base_url)
    llm_model: str = field(default_factory=_resolve_llm_model)

    # Narrative & Remix Style ('general' or 'funny')
    style: str = field(
        default_factory=lambda: os.environ.get("REMIX_STYLE", "general")
    )
    min_clip_duration: float = 3.0
    max_clip_duration: float = 60.0
    target_total_duration: float = 180.0  # Target duration (s)

    # Golden 3-Second Hook (2.5s-4.0s teaser placed at video start)
    enable_golden_hook: bool = field(
        default_factory=lambda: os.environ.get("ENABLE_GOLDEN_HOOK", "true").lower() in ("true", "1", "yes")
    )

    # Natural Breathing Room Padding (seconds) to prevent clipped speech
    pre_roll: float = 0.2
    post_roll: float = 0.3

    # Multimodal Video API Settings (Gemini Native)
    gemini_api_key: Optional[str] = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_RELAY_API_KEY")
    )
    gemini_model: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL") or os.environ.get("GEMINI_RELAY_MODEL") or "gemini-3.7-flash"
    )
    frame_sample_interval: float = 2.0  # Sample 1 frame every 2s for visual understanding

    # Scratch / Temp working directory
    work_dir: str = ".video_remix_work"
