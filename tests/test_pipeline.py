import json
import os
import shutil
import tempfile
import unittest

from video_remix.agent import HighlightAgent, HighlightClip, RemixPlan
from video_remix.asr import MockOrRuleASR, SubtitleFileASR, Transcript, TranscriptSegment
from video_remix.assembler import VideoAssembler
from video_remix.audio import MediaHelper
from video_remix.config import RemixConfig
from video_remix.demo_generator import generate_sample_video_and_subtitles
from video_remix.jianying import JianYingDraftGenerator
from video_remix.pipeline import VideoRemixPipeline


class TestVideoRemix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="video_remix_test_")
        cls.demo_video = os.path.join(cls.test_dir, "sample.mp4")
        cls.demo_srt = os.path.join(cls.test_dir, "sample.srt")
        generate_sample_video_and_subtitles(
            output_video_path=cls.demo_video,
            output_srt_path=cls.demo_srt
        )

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)

    def test_media_helper(self):
        helper = MediaHelper()
        duration = helper.get_duration(self.demo_video)
        self.assertGreater(duration, 40.0)
        self.assertLess(duration, 50.0)

        audio_out = os.path.join(self.test_dir, "audio.wav")
        helper.extract_audio(self.demo_video, audio_out)
        self.assertTrue(os.path.exists(audio_out))
        self.assertGreater(os.path.getsize(audio_out), 1000)

    def test_asr_and_srt_parsing(self):
        asr = SubtitleFileASR(self.demo_srt)
        transcript = asr.transcribe("dummy_audio.wav")
        self.assertEqual(len(transcript.segments), 5)
        self.assertIn("AI二创", transcript.segments[0].text)
        self.assertAlmostEqual(transcript.segments[0].start, 0.0, places=1)
        self.assertAlmostEqual(transcript.segments[0].end, 8.0, places=1)

    def test_highlight_agent_heuristic(self):
        config = RemixConfig()
        agent = HighlightAgent(config=config)
        asr = SubtitleFileASR(self.demo_srt)
        transcript = asr.transcribe("dummy_audio.wav")

        plan = agent.plan(transcript, total_duration=45.0)
        self.assertIsInstance(plan, RemixPlan)
        self.assertTrue(len(plan.clips) > 0)
        self.assertEqual(plan.clips[0].narrative_role, "hook")

        for clip in plan.clips:
            self.assertGreater(clip.end, clip.start)
            self.assertLessEqual(clip.end, 45.0)

    def test_jianying_draft_generator(self):
        helper = MediaHelper()
        generator = JianYingDraftGenerator(media_helper=helper)
        clips = [
            HighlightClip(start=0.0, end=5.0, narrative_role="hook", title="开篇", reason="测试"),
            HighlightClip(start=18.0, end=30.0, narrative_role="climax", title="核心", reason="测试")
        ]
        draft_dir = os.path.join(self.test_dir, "test_draft")
        generator.export_draft(
            source_video_path=self.demo_video,
            clips=clips,
            project_title="测试工程",
            output_dir=draft_dir
        )

        content_path = os.path.join(draft_dir, "draft_content.json")
        meta_path = os.path.join(draft_dir, "draft_meta_info.json")
        self.assertTrue(os.path.exists(content_path))
        self.assertTrue(os.path.exists(meta_path))

        with open(content_path, "r", encoding="utf-8") as f:
            content = json.load(f)
            self.assertIn("materials", content)
            self.assertIn("tracks", content)
            self.assertEqual(len(content["tracks"][0]["segments"]), 2)

    def test_timestamp_snapper(self):
        from video_remix.multimodal import TimestampSnapper, apply_breathing_padding

        snapper = TimestampSnapper(pre_roll=0.2, post_roll=0.3)
        rough_clips = [
            HighlightClip(start=18.5, end=31.5, narrative_role="hook", title="粗剪", reason="测试")
        ]
        snapped = snapper.snap(rough_clips, total_duration=45.0)

        # Expected breathing padding: 18.5 - 0.2 = 18.3, 31.5 + 0.3 = 31.8
        self.assertEqual(len(snapped), 1)
        self.assertAlmostEqual(snapped[0].start, 18.3, places=1)
        self.assertAlmostEqual(snapped[0].end, 31.8, places=1)

    def test_multimodal_agent_planning(self):
        from video_remix.multimodal import MultimodalAgent

        config = RemixConfig(style="funny")
        agent = MultimodalAgent(config=config)

        plan = agent.plan_from_video(
            video_path=self.demo_video,
            total_duration=45.0,
            style="funny"
        )
        self.assertIsInstance(plan, RemixPlan)
        self.assertTrue(len(plan.clips) > 0)
        self.assertIn("多模态", plan.title)

    def test_end_to_end_pipeline(self):
        work_dir = os.path.join(self.test_dir, "work")
        out_video = os.path.join(self.test_dir, "remix_output.mp4")
        out_draft = os.path.join(self.test_dir, "jianying_output")

        config = RemixConfig(work_dir=work_dir, style="funny")
        pipeline = VideoRemixPipeline(config=config)

        result = pipeline.run(
            video_path=self.demo_video,
            subtitle_file=self.demo_srt,
            output_video_path=out_video,
            output_draft_dir=out_draft
        )

        self.assertTrue(os.path.exists(out_video))
        self.assertTrue(os.path.exists(out_draft))
        self.assertGreater(result.remix_duration, 0)
        self.assertLess(result.remix_duration, result.original_duration)


if __name__ == "__main__":
    unittest.main()
