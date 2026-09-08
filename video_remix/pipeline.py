import os
import time
from dataclasses import dataclass
from typing import Optional

from video_remix.agent import HighlightAgent, RemixPlan
from video_remix.assembler import VideoAssembler
from video_remix.audio import MediaHelper
from video_remix.config import RemixConfig
from video_remix.jianying import JianYingDraftGenerator
from video_remix.multimodal import MultimodalAgent


@dataclass
class PipelineResult:
    source_video: str
    output_video: str
    draft_dir: str
    plan: RemixPlan
    original_duration: float
    remix_duration: float
    time_taken_seconds: float

    @property
    def compression_ratio(self) -> float:
        if self.original_duration <= 0:
            return 0.0
        return (self.remix_duration / self.original_duration) * 100.0


class VideoRemixPipeline:
    """Streamlined end-to-end orchestrator for pure multimodal AI video remixing."""

    def __init__(self, config: Optional[RemixConfig] = None):
        self.config = config or RemixConfig()
        self.media_helper = MediaHelper(
            ffmpeg_path=self.config.ffmpeg_path,
            ffprobe_path=self.config.ffprobe_path
        )
        self.agent = HighlightAgent(config=self.config)
        self.multimodal_agent = MultimodalAgent(config=self.config)
        self.assembler = VideoAssembler(ffmpeg_path=self.config.ffmpeg_path)
        self.draft_generator = JianYingDraftGenerator(media_helper=self.media_helper)

    def run(
        self,
        video_path: str,
        subtitle_file: Optional[str] = None,
        output_video_path: Optional[str] = None,
        output_draft_dir: Optional[str] = None
    ) -> PipelineResult:
        """Execute the streamlined 4-step pure multimodal video remix pipeline."""
        start_time = time.time()

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Source video not found: {video_path}")

        # Setup working directory and default output paths
        os.makedirs(self.config.work_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]

        if output_video_path is None:
            output_video_path = os.path.join("output", f"{base_name}_remix.mp4")

        if output_draft_dir is None:
            output_draft_dir = os.path.join("output", f"{base_name}_jianying_draft")

        # Step 1: Video Probing
        print(f"\n[1/4] 探测源视频信息...")
        original_duration = self.media_helper.get_duration(video_path)
        print(f"  源视频: {video_path} (时长: {original_duration:.2f} 秒)")

        # Step 2: Native Multimodal AI Viewing & Planning
        print(f"\n[2/4] 多模态 AI 原生视频审片 (画面神态 + 视听节奏)...")
        plan = self.multimodal_agent.plan_from_video(
            video_path=video_path,
            total_duration=original_duration,
            style=self.config.style
        )

        plan.save_json(os.path.join(self.config.work_dir, "remix_plan.json"))
        print(f"  标题: {plan.title}")
        print(f"  前置悬念: {plan.hook_summary}")
        if plan.golden_hook and self.config.enable_golden_hook:
            gh = plan.golden_hook
            print(f"  ⚡️ 黄金3秒钩子: {gh.start:.1f}s -> {gh.end:.1f}s [{gh.duration:.1f}s] | {gh.punchline} ({gh.hook_technique})")
        print(f"  入选片段数: {len(plan.clips)} (计划成片时长: {plan.total_selected_duration:.2f} 秒, 过滤冗余: {plan.discarded_total_duration:.1f} 秒)")
        for i, c in enumerate(plan.clips, 1):
            print(f"    - Clip {i} [{c.narrative_role}]: {c.start:.1f}s -> {c.end:.1f}s | {c.title} ({c.reason})")

        # Step 3: FFmpeg Precise Assembly with Breathing Room Padding
        print(f"\n[3/4] FFmpeg 智能分切与无损拼接渲染...")
        active_golden_hook = plan.golden_hook if self.config.enable_golden_hook else None
        self.assembler.assemble(
            input_video=video_path,
            clips=plan.clips,
            output_video_path=output_video_path,
            temp_dir=os.path.join(self.config.work_dir, "clips"),
            golden_hook=active_golden_hook
        )
        remix_duration = self.media_helper.get_duration(output_video_path)
        print(f"  渲染完成: {output_video_path} (实际时长: {remix_duration:.2f} 秒)")

        # Step 4: Export Native JianYing / CapCut Draft Project
        print(f"\n[4/4] 导出剪映 (JianYing / CapCut) 原生工程草稿...")
        self.draft_generator.export_draft(
            source_video_path=video_path,
            clips=plan.clips,
            project_title=plan.title,
            output_dir=output_draft_dir,
            golden_hook=active_golden_hook
        )
        print(f"  草稿已生成: {output_draft_dir}")

        total_time = time.time() - start_time
        print(f"\n✅ 二创全流程执行完毕！耗时: {total_time:.2f} 秒\n")

        return PipelineResult(
            source_video=video_path,
            output_video=output_video_path,
            draft_dir=output_draft_dir,
            plan=plan,
            original_duration=original_duration,
            remix_duration=remix_duration,
            time_taken_seconds=total_time
        )
