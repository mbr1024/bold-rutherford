import base64
import json
import os
import re
import subprocess
import time
import urllib.request
from typing import List, Optional

from video_remix.agent import GoldenHook, HighlightClip, RemixPlan, call_chat_completions
from video_remix.config import RemixConfig
from video_remix.prompts import (
    FUNNY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)


def apply_breathing_padding(
    clips: List[HighlightClip],
    total_duration: float,
    pre_roll: float = 0.2,
    post_roll: float = 0.3
) -> List[HighlightClip]:
    """Adds natural breathing room padding and enforces strict boundaries [0, total_duration]."""
    valid_clips = []
    for clip in clips:
        # If start is at or beyond total_duration, drop it
        if total_duration > 0 and clip.start >= total_duration:
            print(f"  [Warning] 剔除超出视频范围的片段: start={clip.start:.1f}s, total_duration={total_duration:.1f}s")
            continue
        s = max(0.0, round(clip.start - pre_roll, 2))
        e = round(clip.end + post_roll, 2)
        if total_duration > 0:
            e = min(total_duration, e)
        # Ensure start is strictly before end with minimal duration
        if e <= s or (e - s) < 0.5:
            print(f"  [Warning] 剔除倒错或过短片段: [{clip.start:.1f}s -> {clip.end:.1f}s] (padded: [{s}s -> {e}s])")
            continue
        clip.start = s
        clip.end = e
        valid_clips.append(clip)
    return valid_clips


class TimestampSnapper:
    """Lightweight compatibility wrapper applying natural breathing room padding."""

    def __init__(self, pre_roll: float = 0.2, post_roll: float = 0.3, tolerance: float = 2.0):
        self.pre_roll = pre_roll
        self.post_roll = post_roll

    def snap(self, clips: List[HighlightClip], transcript=None, total_duration: float = 0.0) -> List[HighlightClip]:
        return apply_breathing_padding(clips, total_duration, self.pre_roll, self.post_roll)


class MultimodalAgent:
    """Multimodal AI Director that watches video natively to make remix decisions."""

    def __init__(self, config: RemixConfig):
        self.config = config

    def _is_gemini_backend(self) -> bool:
        """Detect whether the current configured model/endpoint is a Gemini backend (OpenLux, Google, etc.)."""
        model = (self.config.llm_model or "").lower()
        url = (self.config.llm_base_url or "").lower()
        provider = (self.config.active_provider or "").lower()
        return "gemini" in model or "gemini" in provider or "openlux" in url or bool(self.config.gemini_api_key)

    def plan_from_video(
        self,
        video_path: str,
        total_duration: float,
        style: str = "general",
        transcript=None
    ) -> RemixPlan:
        """Analyze raw video natively using multimodal AI and output a structured remix plan."""
        # 1. Primary: Gemini Native REST API (Direct MP4 video streaming via inline_data)
        api_key = self.config.llm_api_key or self.config.gemini_api_key
        if self._is_gemini_backend() and api_key:
            try:
                plan = self._plan_with_gemini_rest_video(video_path, total_duration, style)
                plan.clips = apply_breathing_padding(plan.clips, total_duration, self.config.pre_roll, self.config.post_roll)
                return plan
            except Exception as e:
                print(f"[Warning] Gemini full-stream video analysis failed ({e}). Falling back to frame sampling.")

        # 2. Secondary: Official google-generativeai SDK if configured
        if self.config.gemini_api_key:
            try:
                plan = self._plan_with_gemini_native(video_path, total_duration, style)
                plan.clips = apply_breathing_padding(plan.clips, total_duration, self.config.pre_roll, self.config.post_roll)
                return plan
            except Exception as e:
                print(f"[Warning] Gemini SDK video analysis failed ({e}). Trying frame sampling.")

        # 3. Tertiary: Frame sampling with multimodal chat completions (Qwen-VL / OpenAI vision)
        if self.config.llm_api_key:
            try:
                plan = self._plan_with_frame_sampling(video_path, total_duration, style)
                plan.clips = apply_breathing_padding(plan.clips, total_duration, self.config.pre_roll, self.config.post_roll)
                return plan
            except Exception as e:
                print(f"[Warning] Multimodal frame sampling failed ({e}). Falling back to simulation.")

        # 4. Quaternary: High-fidelity offline simulation
        plan = self._simulate_multimodal_plan(video_path, total_duration, style)
        plan.clips = apply_breathing_padding(plan.clips, total_duration, self.config.pre_roll, self.config.post_roll)
        return plan

    def _create_analysis_proxy_video(self, video_path: str, total_duration: float) -> str:
        """Quickly compress video to a lightweight proxy MP4 (480p/10fps, mono 32k audio) for Gemini direct feeding."""
        proxy_dir = os.path.join(self.config.work_dir, "proxy_videos")
        os.makedirs(proxy_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        proxy_path = os.path.join(proxy_dir, f"{base_name}_analysis_proxy.mp4")

        # Reuse existing proxy video if newer than source
        if os.path.exists(proxy_path) and os.path.getmtime(proxy_path) >= os.path.getmtime(video_path):
            proxy_size_mb = os.path.getsize(proxy_path) / (1024 * 1024)
            print(f"  [多模态] 复用已生成的分析代理视频: {proxy_path} ({proxy_size_mb:.2f} MB)", flush=True)
            return proxy_path

        print(f"  [多模态] 本地极速转码 AI 原生审片代理视频 (480p/10fps/极轻量音画流)...", flush=True)
        cmd = [
            self.config.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vf", "scale='min(480,iw)':-2:force_original_aspect_ratio=decrease,fps=10",
            "-c:v", "libx264",
            "-crf", "32",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "32k",
            "-ac", "1",
            "-pix_fmt", "yuv420p",
            proxy_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            print(f"  [Warning] 代理视频压缩失败: {res.stderr[:200]}，回退使用原视频。")
            return video_path

        proxy_size_mb = os.path.getsize(proxy_path) / (1024 * 1024)
        print(f"  [多模态] 代理视频生成完毕 (体积: {proxy_size_mb:.2f} MB)，准备直传 Gemini 原生引擎...", flush=True)
        return proxy_path

    def _plan_with_gemini_rest_video(self, video_path: str, total_duration: float, style: str) -> RemixPlan:
        """Streams full proxy video natively to Gemini generateContent endpoint via inline_data (video/mp4)."""
        proxy_path = self._create_analysis_proxy_video(video_path, total_duration)

        proxy_size_mb = os.path.getsize(proxy_path) / (1024 * 1024)
        if proxy_size_mb > 25.0:
            raise ValueError(f"Proxy video size ({proxy_size_mb:.1f} MB) exceeds inline_data limit (>25MB).")

        with open(proxy_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")

        base_url = self.config.llm_base_url or "https://api.openlux.ai"
        host = re.sub(r"/v1(?:beta)?/?$", "", base_url).rstrip("/")
        if not host:
            host = "https://api.openlux.ai"

        model = self.config.llm_model or self.config.gemini_model or "gemini-2.5-flash"
        endpoint = f"{host}/v1beta/models/{model}:generateContent"

        api_key = self.config.llm_api_key or self.config.gemini_api_key

        target_duration = min(self.config.target_total_duration, total_duration * 0.4)
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"你正在直接审看该视频的整段音视频原画流（包含完整音轨、说话语音、关键人物动作与画面变化）。\n"
            f"原视频总时长约 {total_duration:.1f} 秒，目标精剪时长约为 {target_duration:.1f} 秒。\n\n"
            f"【剪辑与时序硬性要求】：\n"
            f"1. 【黄金3秒】：必须从高潮或最大视觉/情绪爆发点提取一个 2.5s ~ 3.5s 的前置钩子 golden_hook。\n"
            f"2. 【主线正序】：clips 中的主线片段必须严格按照视频发生的时间先后正序排列（clips 中的 start 必须从小到大严格递增），绝不允许时序混乱！\n"
            f"3. 【时间精确】：start 和 end 必须为原片绝对时间秒数（Seconds，浮点数）。原片总长约 {total_duration:.1f} 秒，片段必须在 0.0 到 {total_duration:.1f} 之间取值！\n"
            f"4. 【专业拉片】：对每个入选主线分镜，详细拆解 visual_action（景别与画面动作）、audio_dialogue（台词声音细节）与 discarded_context（前后剔除的冗余内容说明）。\n\n"
            f"严格输出以下 JSON Schema 格式：\n"
            f'{{\n'
            f'  "title": "精炼有吸引力的视频标题",\n'
            f'  "hook_summary": "开篇核心看点说明",\n'
            f'  "narrative_arc": "整体镜头推进逻辑与内容主线",\n'
            f'  "golden_hook": {{\n'
            f'    "start": 18.5,\n'
            f'    "end": 21.5,\n'
            f'    "hook_technique": "高潮爆点前置 / 认知反差 / 感官冲击 / 核心悬念",\n'
            f'    "punchline": "爆点瞬间动作与视觉核心描述",\n'
            f'    "voiceover_caption": "推荐吸睛大字花字或口播台词（15字以内）"\n'
            f'  }},\n'
            f'  "clips": [\n'
            f'    {{\n'
            f'      "start": 12.5,\n'
            f'      "end": 28.0,\n'
            f'      "narrative_role": "hook",\n'
            f'      "title": "镜头概括",\n'
            f'      "visual_action": "【景别】画面动作与视觉焦点",\n'
            f'      "audio_dialogue": "台词语音与声音细节",\n'
            f'      "reason": "入选该镜头的价值理由",\n'
            f'      "discarded_context": "前后剔除的冗余时长说明",\n'
            f'      "voiceover_commentary": "镜头说明"\n'
            f'    }}\n'
            f'  ]\n'
            f'}}'
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "video/mp4",
                                "data": video_b64
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.8 if style == "funny" else 0.7
            }
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "x-goog-api-key": api_key,
                "User-Agent": "VideoRemix/2.0"
            }
        )

        import ssl
        print(f"  [多模态] 正在向 Gemini 原生端点传输整段视频流进行全音画深度审片...", flush=True)
        try:
            ctx = ssl.create_default_context()
            resp_handle = urllib.request.urlopen(req, timeout=120, context=ctx)
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                ctx_unverified = ssl._create_unverified_context()
                resp_handle = urllib.request.urlopen(req, timeout=120, context=ctx_unverified)
            else:
                raise

        with resp_handle as resp:
            body = json.loads(resp.read().decode("utf-8"))

        usage = body.get("usageMetadata", {})
        if usage:
            p_tok = usage.get("promptTokenCount", 0)
            c_tok = usage.get("candidatesTokenCount", 0)
            t_tok = usage.get("totalTokenCount", p_tok + c_tok)
            details = usage.get("promptTokensDetails") or []
            detail_str = ""
            if details:
                mod_parts = [f"{d.get('modality')}: {d.get('tokenCount')}" for d in details if d.get("tokenCount")]
                if mod_parts:
                    detail_str = f" ({', '.join(mod_parts)})"
            print(f"  [Token消耗] 输入: {p_tok}{detail_str} | 输出: {c_tok} | 总计: {t_tok}", flush=True)

        candidates = body.get("candidates") or []
        if not candidates:
            raise ValueError(f"Gemini returned empty candidates: {body}")

        raw_text = candidates[0]["content"]["parts"][0]["text"]
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
        return RemixPlan.from_dict(data, total_duration=total_duration)

    def _plan_with_gemini_native(self, video_path: str, total_duration: float, style: str) -> RemixPlan:
        """Uploads video directly to Gemini Files API and gets native video understanding."""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("Please install google-generativeai: pip install google-generativeai")

        genai.configure(api_key=self.config.gemini_api_key)

        print(f"  [多模态] 正在向 Gemini 传输视频进行原生视听审片...")
        video_file = genai.upload_file(path=video_path)

        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise RuntimeError("Gemini video processing failed on cloud.")

        sys_prompt = FUNNY_SYSTEM_PROMPT if style == "funny" else SYSTEM_PROMPT
        prompt = (
            f"{sys_prompt}\n\n"
            f"请仔细审看视频的视觉表情、肢体动作与声音语气变化。\n"
            f"视频总时长约 {total_duration:.1f} 秒，目标二创时长约为 {total_duration * 0.4:.1f} 秒。\n"
            f"请找出最搞笑、打脸或最具冲击力的 3-5 个片段，并严格输出 JSON:\n"
            f'{{"title": "...", "hook_summary": "...", "narrative_arc": "...", '
            f'"clips": [{{"start": 10.0, "end": 20.0, "narrative_role": "hook", "title": "...", "reason": "...", "voiceover_commentary": "..."}}]}}'
        )

        model = genai.GenerativeModel(
            model_name=self.config.gemini_model,
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content([video_file, prompt])
        data = json.loads(response.text)
        return RemixPlan.from_dict(data, total_duration=total_duration)

    def _extract_sampled_frames(self, video_path: str, sample_interval: float = 2.0) -> List[str]:
        """Extract keyframes at regular intervals using FFmpeg."""
        frames_dir = os.path.join(self.config.work_dir, "sampled_frames")
        os.makedirs(frames_dir, exist_ok=True)

        output_pattern = os.path.join(frames_dir, "frame_%04d.jpg")
        cmd = [
            self.config.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-vf", f"fps=1/{sample_interval},scale=640:-1",
            "-q:v", "3",
            output_pattern
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Frame extraction failed: {res.stderr}")

        frame_files = sorted([
            os.path.join(frames_dir, f)
            for f in os.listdir(frames_dir)
            if f.startswith("frame_") and f.endswith(".jpg")
        ])
        return frame_files

    def _plan_with_frame_sampling(
        self,
        video_path: str,
        total_duration: float,
        style: str
    ) -> RemixPlan:
        """Samples frames and feeds them to Gemini / Qwen-VL with multimodal message format."""
        frames = self._extract_sampled_frames(video_path, self.config.frame_sample_interval)

        max_frames = 24 if len(frames) >= 24 else 16
        step = max(1, len(frames) // max_frames)
        selected_frame_indices = list(range(0, len(frames), step))[:max_frames]

        content_parts = []
        frame_time_notes = []
        for rank, idx in enumerate(selected_frame_indices, 1):
            frame_sec = round(idx * self.config.frame_sample_interval, 1)
            frame_time_notes.append(f"帧{rank}: 约{frame_sec}秒")

        time_index_summary = "，".join(frame_time_notes)

        content_parts.append({
            "type": "text",
            "text": (
                f"你是一位顶级中视频二创剪辑总编导。原视频总时长约 {total_duration:.1f} 秒。\n"
                f"以下是按时间提取的 {len(selected_frame_indices)} 个关键帧画面序列（对应时间点：{time_index_summary}）。\n\n"
                f"【剪辑与时序硬性要求】：\n"
                f"1. 必须严格按照故事推进的时间先后正序排列（start 必须从小到大严格递增），绝不允许时序混乱或前言不搭后语（切勿将开场铺垫排在高潮之后）！\n"
                f"2. start 和 end 必须是数字浮点秒数（例如 15.2，严禁带分秒冒号格式）。\n"
                f"3. 挑选 3-5 个最炸裂/最精彩的核心片段，规划成 1-3 分钟的中视频二创剧本。\n\n"
                f"严格输出以下 JSON Schema 格式：\n"
                f'{{\n'
                f'  "title": "爆款二创标题",\n'
                f'  "hook_summary": "开篇核心吸睛点说明",\n'
                f'  "narrative_arc": "整体叙事推进设计",\n'
                f'  "clips": [\n'
                f'    {{\n'
                f'      "start": 12.5,\n'
                f'      "end": 28.0,\n'
                f'      "narrative_role": "hook",\n'
                f'      "title": "片段概括",\n'
                f'      "reason": "入选理由",\n'
                f'      "voiceover_commentary": "建议解说词"\n'
                f'    }}\n'
                f'  ]\n'
                f'}}'
            )
        })

        for idx in selected_frame_indices:
            frame_path = frames[idx]
            with open(frame_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content_parts}
        ]

        data = call_chat_completions(
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
            messages=messages,
            temperature=0.7,
            json_mode=True
        )

        return RemixPlan.from_dict(data, total_duration=total_duration)

    def _simulate_multimodal_plan(
        self,
        video_path: str,
        total_duration: float,
        style: str = "general"
    ) -> RemixPlan:
        """High-fidelity local simulation for test and offline environments with strict chronological order."""
        if total_duration > 60.0:
            c1_start = round(total_duration * 0.02, 1)
            c1_end = round(min(c1_start + 12.0, total_duration * 0.15), 1)
            c2_start = round(total_duration * 0.25, 1)
            c2_end = round(min(c2_start + 18.0, total_duration * 0.40), 1)
            c3_start = round(total_duration * 0.65, 1)
            c3_end = round(min(c3_start + 22.0, total_duration * 0.85), 1)
        else:
            c1_start = 0.0
            c1_end = min(8.0, total_duration * 0.2)
            c2_start = min(18.0, total_duration * 0.4)
            c2_end = min(32.0, total_duration * 0.7)
            c3_start = min(38.0, total_duration * 0.8)
            c3_end = min(45.0, total_duration)

        title = "【AI多模态智能精剪】核心镜头与高能片段精选"
        hook_summary = "智能视觉捕捉：关键动作与核心信息开篇，迅速抓住眼球。"
        narrative_arc = "开篇关键引入 -> 核心高潮展开 -> 结论与收束（严格时间正序）"

        clip1 = HighlightClip(
            start=c1_start,
            end=c1_end,
            narrative_role="hook",
            title="【起因交代】关键起因与背景展开",
            reason="交代起因与核心场景",
            voiceover_commentary="全片关键起因与核心人物动作展开。",
            visual_action="【中景】展示核心人物与初始场景环境全貌",
            audio_dialogue="交代核心事件起因，语气好奇吸睛",
            discarded_context="过滤了开场前的空白调试与闲聊"
        )
        clip2 = HighlightClip(
            start=c2_start,
            end=c2_end,
            narrative_role="climax",
            title="【核心高潮】视觉与内容关键突破",
            reason="AI检测到画面中最强烈的动作与信息密度",
            voiceover_commentary="内容与情绪达到顶点，最具信息增量。",
            visual_action="【特写】关键动作连续突破，视觉冲击力最强瞬间",
            audio_dialogue="情绪高潮爆发，核心金句或关键音效出现",
            discarded_context="过滤了高潮前的长时间铺垫与重复动作"
        )
        clip3 = HighlightClip(
            start=c3_start,
            end=c3_end,
            narrative_role="conclusion",
            title="【总结收束】精彩结尾与关键结论",
            reason="总结收尾，节奏闭环",
            voiceover_commentary="完美收尾，形成完整的信息闭环。",
            visual_action="【全景】结局展示与收束动作",
            audio_dialogue="给出明确总结结论与后续展望",
            discarded_context="过滤了结尾冗长的寒暄与片尾黑屏"
        )
        clips = [clip1, clip2, clip3]

        # Ensure strictly ascending chronological order
        clips.sort(key=lambda x: x.start)

        golden_hook = GoldenHook(
            start=c2_start,
            end=min(c2_end, c2_start + 3.0),
            hook_technique="高潮爆点前置",
            punchline="【高潮瞬间】动作最密集、情绪最高昂的核心高光",
            voiceover_caption="最炸裂瞬间前置预警"
        )

        selected_dur = sum(c.end - c.start for c in clips)
        discarded = max(0.0, round(total_duration - selected_dur, 1))

        return RemixPlan(
            title=title,
            hook_summary=hook_summary,
            narrative_arc=narrative_arc,
            clips=clips,
            golden_hook=golden_hook,
            discarded_total_duration=discarded
        )
