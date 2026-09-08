import json
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from video_remix.asr import Transcript
from video_remix.config import RemixConfig
from video_remix.prompts import (
    FUNNY_SYSTEM_PROMPT,
    FUNNY_USER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)


@dataclass
class GoldenHook:
    """Golden 3-Second Hook (2.5s - 4.0s) teaser placed at video start for maximum retention."""
    start: float
    end: float
    hook_technique: str = "高潮爆点前置"
    punchline: str = ""
    voiceover_caption: str = ""
    duration: float = field(init=False)

    def __post_init__(self):
        self.duration = round(max(0.0, self.end - self.start), 2)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "hook_technique": self.hook_technique,
            "punchline": self.punchline,
            "voiceover_caption": self.voiceover_caption
        }

    @classmethod
    def from_dict(cls, data: dict, total_duration: float = 0.0) -> Optional["GoldenHook"]:
        if not data or not isinstance(data, dict):
            return None
        s_val = data.get("start") if "start" in data else (data.get("start_time") or data.get("from"))
        e_val = data.get("end") if "end" in data else (data.get("end_time") or data.get("to"))
        if s_val is None and e_val is None:
            return None
        s = parse_time_value(s_val)
        e = parse_time_value(e_val)
        if total_duration > 0:
            s = min(s, total_duration)
            e = min(e, total_duration)
        if e <= s:
            e = min(total_duration, s + 3.0) if total_duration > 0 else s + 3.0
        dur = e - s
        if dur < 1.0:
            e = min(total_duration, s + 3.0) if total_duration > 0 else s + 3.0
        elif dur > 5.0:
            e = s + 3.5
        return cls(
            start=round(s, 2),
            end=round(e, 2),
            hook_technique=data.get("hook_technique") or data.get("technique") or "高潮爆点前置",
            punchline=data.get("punchline") or data.get("reason") or "最具视觉冲击力的高能瞬间",
            voiceover_caption=data.get("voiceover_caption") or data.get("caption") or ""
        )


@dataclass
class HighlightClip:
    start: float
    end: float
    narrative_role: str  # 'hook', 'context', 'body', 'climax', 'twist', 'conclusion'
    title: str
    reason: str
    voiceover_commentary: Optional[str] = None
    visual_action: str = ""      # 画面动作与景别
    audio_dialogue: str = ""     # 台词与声音细节
    discarded_context: str = ""  # 本镜头前后过滤掉的无效冗余说明


def parse_time_value(val) -> float:
    """Robustly parse timestamps in float, integer, '01:23', '00:01:23', or '15s' format."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    val = str(val).strip().strip("'\"")
    if not val:
        return 0.0
    if ":" in val:
        parts = val.split(":")
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
        except ValueError:
            pass
    cleaned = re.sub(r"[^\d.]", "", val)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


@dataclass
class RemixPlan:
    title: str
    hook_summary: str
    narrative_arc: str
    clips: List[HighlightClip] = field(default_factory=list)
    golden_hook: Optional[GoldenHook] = None
    discarded_total_duration: float = 0.0

    @property
    def total_selected_duration(self) -> float:
        base_dur = sum(c.end - c.start for c in self.clips)
        if self.golden_hook:
            base_dur += self.golden_hook.duration
        return base_dur

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.golden_hook:
            d["golden_hook"] = self.golden_hook.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict, total_duration: float = 0.0) -> "RemixPlan":
        raw_clips = data.get("clips") or []
        if isinstance(raw_clips, dict):
            raw_clips = list(raw_clips.values())

        clips = []
        for i, c in enumerate(raw_clips):
            if not isinstance(c, dict):
                continue
            s_val = c.get("start") if "start" in c else (c.get("start_time") or c.get("startTime") or c.get("start_seconds") or c.get("from"))
            e_val = c.get("end") if "end" in c else (c.get("end_time") or c.get("endTime") or c.get("end_seconds") or c.get("to"))
            start_sec = parse_time_value(s_val)
            end_sec = parse_time_value(e_val)
            if end_sec <= start_sec:
                continue
            clips.append(HighlightClip(
                start=start_sec,
                end=end_sec,
                narrative_role=c.get("narrative_role") or c.get("role") or "body",
                title=c.get("title") or f"Clip {i+1}",
                reason=c.get("reason") or "",
                voiceover_commentary=c.get("voiceover_commentary") or c.get("voiceover"),
                visual_action=c.get("visual_action") or c.get("action") or "",
                audio_dialogue=c.get("audio_dialogue") or c.get("dialogue") or "",
                discarded_context=c.get("discarded_context") or c.get("cut_reason") or ""
            ))

        # If model mistakenly output percentage/ratio (e.g. 0.1 to 0.7) for long video
        if total_duration > 10.0 and clips and all(c.end <= 1.0 for c in clips):
            for c in clips:
                c.start = round(c.start * total_duration, 2)
                c.end = min(total_duration, round(c.end * total_duration, 2))

        # Enforce chronological ordering so story timeline flows forward naturally
        clips.sort(key=lambda x: x.start)

        # Parse golden_hook
        gh_data = data.get("golden_hook")
        golden_hook = GoldenHook.from_dict(gh_data, total_duration=total_duration) if gh_data else None

        # Fallback: if no golden hook generated, synthesize one from the climax clip
        if not golden_hook and clips:
            climax_clips = [c for c in clips if c.narrative_role in ("climax", "twist")]
            target_clip = climax_clips[0] if climax_clips else clips[-1]
            gh_start = target_clip.start
            gh_end = min(target_clip.end, target_clip.start + 3.0)
            if gh_end > gh_start:
                golden_hook = GoldenHook(
                    start=round(gh_start, 2),
                    end=round(gh_end, 2),
                    hook_technique="高潮爆点前置 (AI精炼提取)",
                    punchline=f"【前置高光】{target_clip.title}",
                    voiceover_caption=f"先睹为快：{target_clip.title}"
                )

        selected_dur = sum(c.end - c.start for c in clips)
        discarded = max(0.0, round(total_duration - selected_dur, 1)) if total_duration > 0 else 0.0

        return cls(
            title=data.get("title", "未命名二创视频"),
            hook_summary=data.get("hook_summary", ""),
            narrative_arc=data.get("narrative_arc", ""),
            clips=clips,
            golden_hook=golden_hook,
            discarded_total_duration=discarded
        )

    def save_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


def call_chat_completions(
    api_key: str,
    base_url: Optional[str],
    model: str,
    messages: list,
    temperature: float = 0.7,
    json_mode: bool = True
) -> dict:
    """Invokes OpenAI-compatible chat completions API with zero-dependency urllib fallback."""
    base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        kwargs = {"model": model, "messages": messages, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        return json.loads(resp.choices[0].message.content)
    except ImportError:
        pass

    # Built-in zero-dependency urllib fallback
    import urllib.request
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "VideoRemix-AI/0.1.0"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    import ssl
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
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
        usage = body.get("usage")
        if usage:
            p_tok = usage.get("prompt_tokens", 0)
            c_tok = usage.get("completion_tokens", 0)
            t_tok = usage.get("total_tokens", p_tok + c_tok)
            print(f"  [Token消耗] 输入: {p_tok} | 输出: {c_tok} | 总计: {t_tok}", flush=True)

        raw_text = body["choices"][0]["message"]["content"]
        # Strip markdown ```json codeblocks if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)


class HighlightAgent:
    """AI Director / Chief Editor responsible for analyzing transcripts and crafting the remix plan."""

    def __init__(self, config: RemixConfig):
        self.config = config

    def plan(self, transcript: Transcript, total_duration: float) -> RemixPlan:
        """Generate a complete remix plan from the given transcript."""
        if not transcript.segments:
            raise ValueError("Transcript has no segments to analyze.")

        # If LLM API Key is configured, use the LLM backend
        if self.config.llm_api_key:
            try:
                return self._plan_with_llm(transcript, total_duration)
            except Exception as e:
                print(f"[Warning] LLM planning failed ({e}). Falling back to heuristic rule engine.")

        # Otherwise, run the heuristic rule engine
        return self._plan_with_heuristic(transcript, total_duration)

    def _plan_with_llm(self, transcript: Transcript, total_duration: float) -> RemixPlan:
        min_target = min(self.config.min_clip_duration * 3, total_duration * 0.2)
        max_target = min(self.config.target_total_duration, total_duration * 0.8)

        if self.config.style == "funny":
            sys_prompt = FUNNY_SYSTEM_PROMPT
            user_template = FUNNY_USER_PROMPT_TEMPLATE
        else:
            sys_prompt = SYSTEM_PROMPT
            user_template = USER_PROMPT_TEMPLATE

        user_content = user_template.format(
            transcript_text=transcript.to_formatted_prompt_text(),
            total_duration=total_duration,
            min_target_duration=min_target,
            max_target_duration=max_target
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content}
        ]

        data = call_chat_completions(
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
            messages=messages,
            temperature=0.8 if self.config.style == "funny" else 0.7,
            json_mode=True
        )

        plan = RemixPlan.from_dict(data)
        self._validate_and_sanitize(plan, total_duration)
        return plan

    def _plan_with_heuristic(self, transcript: Transcript, total_duration: float) -> RemixPlan:
        """Heuristic highlight extractor that scores segments by keywords, density, and structure."""
        if self.config.style == "funny":
            high_energy_keywords = [
                "哈哈哈", "笑死", "卧槽", "蚌埠住", "离谱", "打脸", "翻车", "破防", "丢人",
                "救命", "神操作", "大哥", "退钱", "绝了", "扣地缝", "大冤种", "倒反天罡",
                "服了", "疯了", "谁懂啊", "无语", "下头", "名场面", "尴尬", "别搞"
            ]
        else:
            high_energy_keywords = [
                "核心", "关键", "爆点", "颠覆", "必死", "其实", "反思", "真相", "重要",
                "秘密", "突破", "巨大", "千万", "严重", "精彩", "必须", "但是", "为什么", "注意"
            ]

        scored_segments = []
        for seg in transcript.segments:
            score = 1.0
            # Keyword score
            for kw in high_energy_keywords:
                if kw in seg.text:
                    score += 4.0 if self.config.style == "funny" else 3.0
            # Length penalty for too short or too long
            dur = seg.end - seg.start
            if dur < 2.0 or dur > 50.0:
                score *= 0.5
            # Exclamation or question mark bonus
            if any(char in seg.text for char in ["！", "!", "？", "?"]):
                score += 2.0
            scored_segments.append((score, seg))

        # Sort by score descending
        scored_segments.sort(key=lambda x: x[0], reverse=True)

        clips: List[HighlightClip] = []

        # Find Hook (from top candidates with high punchiness)
        if scored_segments:
            best_score, best_seg = scored_segments[0]
            clips.append(HighlightClip(
                start=best_seg.start,
                end=best_seg.end,
                narrative_role="hook",
                title="悬念前置引子",
                reason=f"命中高热度关键词及情绪表达 (评分 {best_score:.1f})"
            ))

        # Find Context & Climax
        used_ids = {clips[0].start} if clips else set()
        for score, seg in scored_segments[1:]:
            if len(clips) >= 4:
                break
            if seg.start in used_ids:
                continue
            role = "climax" if len(clips) == 1 else "twist"
            clips.append(HighlightClip(
                start=seg.start,
                end=seg.end,
                narrative_role=role,
                title=f"核心看点片段 #{len(clips)}",
                reason=f"高密度信息支撑 (评分 {score:.1f})"
            ))
            used_ids.add(seg.start)

        # Find Conclusion (prefer segment near the end of the video)
        tail_segments = [s for s in transcript.segments if s.end >= total_duration * 0.7]
        if tail_segments:
            last_seg = tail_segments[-1]
            if last_seg.start not in used_ids:
                clips.append(HighlightClip(
                    start=last_seg.start,
                    end=last_seg.end,
                    narrative_role="conclusion",
                    title="总结与认知升华",
                    reason="原视频尾部总结段落"
                ))

        # Fallback if no clips found
        if not clips and transcript.segments:
            first = transcript.segments[0]
            clips.append(HighlightClip(
                start=first.start,
                end=first.end,
                narrative_role="hook",
                title="精选片段",
                reason="默认推荐片段"
            ))

        if self.config.style == "funny":
            title = "【爆笑高能】全程离谱反转！当场立Flag光速打脸合集"
            hook_summary = "开局直接暴击社死瞬间，瞬间笑喷，好奇心拉满。"
            narrative_arc = "光速社死开头 -> 奇葩逻辑/立Flag -> 光速翻车打脸 -> 绝望破防"
        else:
            title = "【AI二创】深度解析：未来关键变革与核心真相"
            hook_summary = "以最具戏剧性/反差性的观点作为开局，迅速激发好奇心。"
            narrative_arc = "Hook悬念抓人 -> 冲突与干货展开 -> 认知收束与号召互动"

        plan = RemixPlan(
            title=title,
            hook_summary=hook_summary,
            narrative_arc=narrative_arc,
            clips=clips
        )

        self._validate_and_sanitize(plan, total_duration)
        return plan

    def _validate_and_sanitize(self, plan: RemixPlan, total_duration: float):
        """Ensure time ranges are within bounds, non-empty, and valid."""
        valid_clips = []
        for c in plan.clips:
            start = max(0.0, min(c.start, total_duration))
            end = max(0.0, min(c.end, total_duration))
            if end > start + 0.5:
                c.start = round(start, 2)
                c.end = round(end, 2)
                valid_clips.append(c)

        # Sort clips by narrative: hook first, then others, or chronological
        plan.clips = valid_clips
