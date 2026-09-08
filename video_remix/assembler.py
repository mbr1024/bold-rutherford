import os
import subprocess
from typing import List, Optional

from video_remix.agent import GoldenHook, HighlightClip
from video_remix.audio import MediaHelper


class VideoAssembler:
    """Uses FFmpeg to cut and concatenate highlight clips into the final remix video."""

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        self.ffmpeg_path = ffmpeg_path
        self.media_helper = MediaHelper(ffmpeg_path=ffmpeg_path)

    def cut_clip(self, input_video: str, start: float, end: float, output_path: str) -> str:
        """Extract a single clip accurately using FFmpeg."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        duration = end - start
        if duration <= 0:
            raise ValueError(f"Clip duration must be positive, got {duration:.3f}s (start={start:.2f}, end={end:.2f})")

        # Using input seeking with accurate re-encode to avoid keyframe blank/freeze issues
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", f"{start:.3f}",
            "-i", input_video,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            output_path
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg clip cut failed for [{start} -> {end}]: {result.stderr}")

        return output_path

    def assemble(
        self,
        input_video: str,
        clips: List[HighlightClip],
        output_video_path: str,
        temp_dir: str = ".video_remix_work",
        golden_hook: Optional[GoldenHook] = None
    ) -> str:
        """Cut all highlight clips and concatenate them into a seamless remix video."""
        safe_clips = [c for c in clips if c.end > c.start and (c.end - c.start) >= 0.3]
        if not safe_clips:
            raise ValueError("No valid highlight clips provided for assembly.")
        clips = safe_clips

        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)

        clip_files = []

        # 1. Prepend Golden 3-Second Hook if enabled and valid
        if golden_hook and golden_hook.end > golden_hook.start and (golden_hook.end - golden_hook.start) >= 1.0:
            gh_name = f"clip_hook_golden_3s_{golden_hook.start:.1f}s.mp4"
            gh_path = os.path.join(temp_dir, gh_name)
            self.cut_clip(input_video, golden_hook.start, golden_hook.end, gh_path)
            clip_files.append(gh_path)

        # 2. Main sequential clips
        for i, clip in enumerate(clips):
            clip_name = f"clip_{i:03d}_{clip.narrative_role}_{clip.start:.1f}s.mp4"
            clip_path = os.path.join(temp_dir, clip_name)
            self.cut_clip(input_video, clip.start, clip.end, clip_path)
            clip_files.append(clip_path)

        # Write concat list
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for clip_path in clip_files:
                abs_p = os.path.abspath(clip_path).replace("'", "'\\''")
                f.write(f"file '{abs_p}'\n")

        # Concat using FFmpeg concat demuxer
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            output_video_path
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            # Fallback to re-encoding if stream copy fails due to codec differences
            cmd_reencode = [
                self.ffmpeg_path,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-c:a", "aac",
                output_video_path
            ]
            res2 = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res2.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr}\nFallback error: {res2.stderr}")

        return output_video_path
