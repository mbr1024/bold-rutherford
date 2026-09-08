import json
import os
import time
import uuid
from typing import List, Optional

from video_remix.agent import GoldenHook, HighlightClip
from video_remix.audio import MediaHelper


class JianYingDraftGenerator:
    """Generates JianYing Pro (剪映) / CapCut compatible project drafts."""

    def __init__(self, media_helper: Optional[MediaHelper] = None):
        self.media_helper = media_helper or MediaHelper()

    def export_draft(
        self,
        source_video_path: str,
        clips: List[HighlightClip],
        project_title: str,
        output_dir: str,
        golden_hook: Optional[GoldenHook] = None
    ) -> str:
        """Export a ready-to-open JianYing draft directory containing draft_content.json and draft_meta_info.json.

        Time units in JianYing protocol are in microseconds (1 second = 1,000,000 us).
        """
        os.makedirs(output_dir, exist_ok=True)
        abs_source_path = os.path.abspath(source_video_path)
        source_duration_sec = self.media_helper.get_duration(source_video_path)
        source_duration_us = int(source_duration_sec * 1_000_000)

        material_video_id = str(uuid.uuid4()).upper()
        track_id = str(uuid.uuid4()).upper()
        draft_id = str(uuid.uuid4()).upper()

        current_timeline_us = 0
        segments = []

        # 1. Prepend Golden 3-Second Hook if provided
        if golden_hook and golden_hook.end > golden_hook.start and (golden_hook.end - golden_hook.start) >= 1.0:
            gh_dur_us = int((golden_hook.end - golden_hook.start) * 1_000_000)
            gh_start_us = int(golden_hook.start * 1_000_000)
            seg_id = str(uuid.uuid4()).upper()
            segments.append({
                "id": seg_id,
                "material_id": material_video_id,
                "source_timerange": {
                    "start": gh_start_us,
                    "duration": gh_dur_us
                },
                "target_timerange": {
                    "start": current_timeline_us,
                    "duration": gh_dur_us
                },
                "speed": 1.0,
                "volume": 1.0,
                "extra_info": {
                    "narrative_role": "golden_hook",
                    "title": f"⚡️ 黄金3秒爆点钩子: {golden_hook.punchline}",
                    "reason": golden_hook.hook_technique,
                    "voiceover": golden_hook.voiceover_caption
                }
            })
            current_timeline_us += gh_dur_us

        # 2. Main story clips
        for clip in clips:
            clip_dur_us = int((clip.end - clip.start) * 1_000_000)
            clip_source_start_us = int(clip.start * 1_000_000)

            seg_id = str(uuid.uuid4()).upper()
            segment_obj = {
                "id": seg_id,
                "material_id": material_video_id,
                "source_timerange": {
                    "start": clip_source_start_us,
                    "duration": clip_dur_us
                },
                "target_timerange": {
                    "start": current_timeline_us,
                    "duration": clip_dur_us
                },
                "speed": 1.0,
                "volume": 1.0,
                "extra_info": {
                    "narrative_role": clip.narrative_role,
                    "title": clip.title,
                    "reason": clip.reason,
                    "voiceover": clip.voiceover_commentary or ""
                }
            }
            segments.append(segment_obj)
            current_timeline_us += clip_dur_us

        total_draft_duration_us = current_timeline_us

        # Build draft_content.json
        draft_content = {
            "id": draft_id,
            "fps": 30.0,
            "duration": total_draft_duration_us,
            "materials": {
                "videos": [
                    {
                        "id": material_video_id,
                        "path": abs_source_path,
                        "duration": source_duration_us,
                        "type": "video"
                    }
                ],
                "audios": [],
                "texts": [],
                "transitions": [],
                "speeds": []
            },
            "tracks": [
                {
                    "id": track_id,
                    "type": "video",
                    "attribute": 0,
                    "flag": 0,
                    "segments": segments
                }
            ],
            "version": 300000
        }

        # Build draft_meta_info.json
        now_ts = int(time.time() * 1_000_000)
        draft_meta_info = {
            "draft_id": draft_id,
            "draft_name": project_title,
            "draft_root_path": os.path.abspath(output_dir),
            "tm_draft_create": now_ts,
            "tm_draft_modified": now_ts,
            "draft_remix_metadata": {
                "generated_by": "VideoRemix-AI",
                "clips_count": len(clips),
                "total_duration_seconds": total_draft_duration_us / 1_000_000
            }
        }

        content_file = os.path.join(output_dir, "draft_content.json")
        meta_file = os.path.join(output_dir, "draft_meta_info.json")

        with open(content_file, "w", encoding="utf-8") as f:
            json.dump(draft_content, f, ensure_ascii=False, indent=2)

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(draft_meta_info, f, ensure_ascii=False, indent=2)

        return output_dir
