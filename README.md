# Video Remix AI (中视频二创智能剪辑系统)

> 利用 AI 从长视频中自动识别高能/焦点内容，重构叙事逻辑，并自动混剪拼接为高留存率的中视频二创成片，同时一键导出剪映/CapCut工程草稿。

---

## ✨ 核心特性

- 🎯 **中视频专业叙事编排**：区别于简单的切片堆砌，AI 编导遵循“黄金前3秒悬念 (Hook) -> 情境铺陈 (Context) -> 冲突高潮 (Climax) -> 认知升华 (Conclusion)”的叙事模型。
- ⚡ **无外部依赖一键自测**：内置合成测试样片生成器与离线启发式规则引擎，即使当前没有 API Key 或 GPU 模型，也能 3 秒跑通全流程闭环！
- ✂️ **FFmpeg 极速精准剪辑**：支持关键帧修正，无损拼接，彻底告别音画不同步。
- 🎬 **剪映 / CapCut 草稿直出**：直接生成原生工程草稿（`draft_content.json`），方便创作者花 5-10 分钟在剪映中做终审与卡点精修。
- 🔌 **全主流大模型兼容**：原生支持 OpenAI、DeepSeek、阿里通义千问、Kimi、Ollama 等任何 OpenAI 协议兼容的大模型。

---

## 🚀 快速上手 (Quick Start)

### 1. 启动可视化 Web GUI 工作台（推荐 ⭐）

无需安装繁重的第三方依赖，系统已内置原生 Web 工作台。在终端执行：

```bash
python3 -m video_remix.cli web
```

启动后在浏览器打开 **`http://127.0.0.1:8765`**，即可体验：
- 🎛️ **一键切换渠道与模型**（Google Gemini 中转站 / 阿里云百炼 Qwen）；
- 📁 **长视频拖拽上传与即时样片自测**；
- 📊 **5 步实时进度跟踪与控制台日志流**；
- 🎬 **成片即时播放与交互式分镜时间轴**（点击分镜卡片，播放器秒级跳转）；
- ✂️ **一键复制/打开剪映工程草稿路径**。

---

### 2. 命令行一键运行自测 Demo (CLI)

系统已内置测试样片生成与全流程自动化演示，在终端执行以下命令：

```bash
python3 -m video_remix.cli demo
```

执行后将自动：
1. 合成一段带声画、色块分镜与字幕的 45 秒测试长视频；
2. 提取音轨并完成语义转录；
3. AI 编导提取核心颠覆观点（Hook 与 Climax）；
4. FFmpeg 自动切割并渲染为 `output/demo_remix.mp4`；
5. 生成剪映工程草稿至 `output/demo_jianying_draft`。

---

### 2. 剪辑自己的长视频

```bash
# 1. 多模态 AI 原生审片（默认推荐：视觉表情 + 听觉情绪 + 对话剧情一体化）
python3 -m video_remix.cli process -i my_long_video.mp4 --mode multimodal --style funny

# 2. 接入 Gemini 原生视频审片（视听超强，支持 1~2 小时长视频直传）
python3 -m video_remix.cli process \
  -i my_long_video.mp4 \
  --mode multimodal \
  --gemini-api-key "AIzaSy..."

# 3. 接入 OpenAI / DeepSeek / 通用多模态（自动按秒抽帧视觉理解）
python3 -m video_remix.cli process \
  -i my_long_video.mp4 \
  --mode multimodal \
  --api-key "sk-xxxxxx" \
  --model "gpt-4o"

# 4. 纯逐字稿文本审片模式（省 Token 极速模式）
python3 -m video_remix.cli process -i my_long_video.mp4 --mode transcript
```

---

## 📂 项目结构

```
bold-rutherford/
├── video_remix/
│   ├── config.py             # 配置管理 (API Key, 时长阈值, FFmpeg路径)
│   ├── audio.py              # 音频抽取与时长探测工具
│   ├── asr.py                # 语音转写层 (Whisper, SRT, Mock)
│   ├── prompts.py            # 中视频专业编导 Prompt 模板
│   ├── agent.py              # AI 编导大脑 (LLM与离线规则引擎)
│   ├── assembler.py          # 视频精准分切与无损拼接
│   ├── jianying.py           # 剪映 / CapCut 原生工程草稿协议生成器
│   ├── demo_generator.py     # 合成测试样片生成器
│   ├── pipeline.py           # 全流程调度控制器
│   └── cli.py                # 命令行统一入口
├── docs/
│   ├── ARCHITECTURE.md       # 系统架构与接口规范
│   └── ROADMAP.md            # 中视频全景技术演进与商业化指南
├── tests/
│   └── test_pipeline.py      # 端到端自动化测试
└── requirements.txt
```

---

## 📖 进阶文档

- [系统架构与模块设计 (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [中视频二创路线图与商业化实操指南 (docs/ROADMAP.md)](docs/ROADMAP.md)
