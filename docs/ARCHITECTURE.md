# 系统架构设计说明文档 (ARCHITECTURE.md)

本文档详细描述 **Video Remix AI**（中视频二创自动化智能系统）的核心系统架构、模块接口规范与数据流设计。

---

## 1. 核心架构设计与分层

系统遵循**管道-过滤器（Pipes & Filters）**与**插件化适配器（Adapter Pattern）**设计原则，共分为五大核心层次：

```
+-------------------------------------------------------------------------+
|                          1. 用户交互与接口层                             |
|       CLI 命令行工具 (cli.py)  |  WebUI 可视化工作台 (未来扩展)           |
+------------------------------------+------------------------------------+
                                     |
+------------------------------------v------------------------------------+
|                         2. 流程编排与控制器层                            |
|             VideoRemixPipeline (pipeline.py) - 生命周期调度              |
+------------------------------------+------------------------------------+
                                     |
      +------------------------------+------------------------------+
      |                              |                              |
+-----v---------------+   +----------v-----------+   +--------------v-----+
| 3. 感知与特征提取层 |   | 4. 智能编导与决策层  |   | 5. 组装与工程协议层 |
| - MediaHelper       |   | - HighlightAgent     |   | - VideoAssembler   |
| - BaseASR (Whisper) |   | - Prompts Engine     |   | - JianYingDraft    |
| - Acoustic (声学)   |   | - Narrative Planner  |   | - Subtitle Burner  |
+---------------------+   +----------------------+   +--------------------+
```

---

## 2. 核心数据流 (Data Flow)

整个处理周期中的数据流转格式如下：

1. **输入阶段**：原始视频文件（MP4 / MKV / MOV 等）。
2. **感知阶段**：
   - 提取 16kHz 单声道音频（PCM S16LE WAV）。
   - 生成带时间戳的词级/段落级字幕 `Transcript`，内部表示：
     ```python
     TranscriptSegment(id=0, start=12.5, end=18.3, text="核心观点是...")
     ```
3. **规划阶段 (AI Director)**：
   - 组装带时间码的 Prompt 发送至大模型（或离线启发式引擎）。
   - 输出结构化中视频剧本 `RemixPlan`：
     ```json
     {
       "title": "二创视频标题",
       "hook_summary": "前3秒悬念",
       "narrative_arc": "黄金开头 -> 冲突爆发 -> 观点升华",
       "clips": [
         {
           "start": 12.5,
           "end": 28.0,
           "narrative_role": "hook",
           "title": "颠覆性开头",
           "reason": "强冲突与悬念",
           "voiceover_commentary": "大家注意看，这里..."
         }
       ]
     }
     ```
4. **生成阶段**：
   - **成片直出**：FFmpeg 快速定位关键帧，切片输出并利用 Concat Demuxer 缝合为 `remix.mp4`。
   - **剪映工程**：将切片区间映射为剪映标准微秒时间码，输出 `draft_content.json` 与 `draft_meta_info.json`。

---

## 3. 核心模块与接口规范

### 3.1 ASR 模块 (`video_remix/asr.py`)
- **接口契约**：继承 `BaseASR`，实现 `transcribe(audio_path, video_path) -> Transcript`。
- **扩展性**：支持无缝插拔 `faster-whisper`（本地高性能推断）、OpenAI Whisper API、阿里云 FunASR 或外挂字幕文件。

### 3.2 智能编导模块 (`video_remix/agent.py`)
- **接口契约**：`plan(transcript: Transcript, total_duration: float) -> RemixPlan`。
- **兼容性**：底层通过 OpenAI 兼容协议适配 DeepSeek、Qwen、Claude、GPT 等几乎所有主流大模型，同时自带离线启发式规则兜底，确保在无网络或无 Token 时系统永不崩溃。

### 3.3 剪映工程生成模块 (`video_remix/jianying.py`)
- **时间单位换算**：剪映底层协议均以**微秒（Microsecond，1s = 1,000,000 μs）**为基准单位。
- **无损引用**：草稿直接通过绝对路径引用原始视频文件，只在时间轴上记录入点与出点（In/Out Point），导入剪映时秒级加载，无需重新拷贝巨大媒体文件。

---

## 4. 后续扩展插槽 (Extension Slots)

1. **多模态感知插槽**：在 `audio.py` 中引入 `AcousticAnalyzer`（检测笑声、高音量掌声），在 `asr.py` 中结合文本得分进行加权打分。
2. **弹幕热度加权插槽**：通过 B站/YouTube 弹幕抓取器，在 `TranscriptSegment` 中注入 `danmaku_density` 字段，作为焦点选取的最高优先级因子。
3. **TTS 旁白插槽**：在 `VideoAssembler` 拼接片段之间，若 `clip.voiceover_commentary` 存在，自动调用 Edge-TTS 或 CosyVoice 合成解说音频并作为画外音插入。
