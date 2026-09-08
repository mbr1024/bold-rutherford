import argparse
import sys

from video_remix.config import RemixConfig
from video_remix.demo_generator import generate_sample_video_and_subtitles
from video_remix.pipeline import VideoRemixPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-remix",
        description="AI-powered medium-length video remixing & highlight curation CLI."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: process
    process_parser = subparsers.add_parser("process", help="Process a source video into a remixed video")
    process_parser.add_argument("-i", "--input", required=True, help="Path to input source video")
    process_parser.add_argument("-s", "--subtitles", default=None, help="Optional path to existing .srt/.vtt subtitle file")
    process_parser.add_argument("-o", "--output", default=None, help="Path for output remixed video")
    process_parser.add_argument("-d", "--draft-dir", default=None, help="Directory to export JianYing draft")
    process_parser.add_argument("--mode", default="multimodal", choices=["multimodal", "transcript"], help="Analysis mode: 'multimodal' (AI watches video) or 'transcript' (ASR text)")
    process_parser.add_argument("--style", default="general", choices=["general", "funny"], help="Remix style: 'general' (universal/narrative) or 'funny' (meme/comedy)")
    process_parser.add_argument("--api-key", default=None, help="OpenAI-compatible LLM API Key")
    process_parser.add_argument("--gemini-api-key", default=None, help="Google Gemini API Key for native video understanding")
    process_parser.add_argument("--base-url", default=None, help="LLM API Base URL (e.g. for DeepSeek/Qwen/Ollama)")
    process_parser.add_argument("--model", default=None, help="LLM Model name")

    # Command: demo
    demo_parser = subparsers.add_parser("demo", help="Generate a synthetic test video and run the full remix pipeline")
    demo_parser.add_argument("--mode", default="multimodal", choices=["multimodal", "transcript"], help="Analysis mode: 'multimodal' or 'transcript'")
    demo_parser.add_argument("--style", default="general", choices=["general", "funny"], help="Remix style: 'general' or 'funny'")
    demo_parser.add_argument("--api-key", default=None, help="Optional LLM API Key for real LLM testing")
    demo_parser.add_argument("--gemini-api-key", default=None, help="Optional Gemini API Key for native video testing")

    # Command: web
    web_parser = subparsers.add_parser("web", help="Start the interactive Web GUI server")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "demo":
        print("🎬 正在生成合成测试样片 (45秒带声画)...")
        demo_video, demo_srt = generate_sample_video_and_subtitles("demo_source.mp4", "demo_source.srt")
        print(f"已创建测试视频: {demo_video} 与字幕: {demo_srt}")

        config = RemixConfig()
        if args.mode:
            config.analysis_mode = args.mode
        if args.style:
            config.style = args.style
        if args.api_key:
            config.llm_api_key = args.api_key
        if args.gemini_api_key:
            config.gemini_api_key = args.gemini_api_key

        pipeline = VideoRemixPipeline(config=config)
        result = pipeline.run(
            video_path=demo_video,
            subtitle_file=demo_srt,
            output_video_path="output/demo_remix.mp4",
            output_draft_dir="output/demo_jianying_draft"
        )
        print("=" * 60)
        print(f"🎉 演示成功！")
        print(f"审片通道: {'多模态 AI 直审 (multimodal)' if config.analysis_mode == 'multimodal' else '逐字稿审片 (transcript)'}")
        print(f"二创模式: {'爆笑整活流 (funny)' if config.style == 'funny' else '深度解析流 (general)'}")
        print(f"原片时长: {result.original_duration:.1f}s -> 二创成片时长: {result.remix_duration:.1f}s")
        print(f"浓缩比率: {result.compression_ratio:.1f}%")
        print(f"成片位置: {result.output_video}")
        print(f"剪映工程: {result.draft_dir}")
        print("=" * 60)

    elif args.command == "process":
        config = RemixConfig()
        if args.mode:
            config.analysis_mode = args.mode
        if args.style:
            config.style = args.style
        if args.api_key:
            config.llm_api_key = args.api_key
        if args.gemini_api_key:
            config.gemini_api_key = args.gemini_api_key
        if args.base_url:
            config.llm_base_url = args.base_url
        if args.model:
            config.llm_model = args.model

        pipeline = VideoRemixPipeline(config=config)
        result = pipeline.run(
            video_path=args.input,
            subtitle_file=args.subtitles,
            output_video_path=args.output,
            output_draft_dir=args.draft_dir
        )
        print("=" * 60)
        print(f"🎉 处理完成！")
        print(f"原片时长: {result.original_duration:.1f}s -> 二创成片时长: {result.remix_duration:.1f}s")
        print(f"成片位置: {result.output_video}")
        print(f"剪映工程: {result.draft_dir}")
        print("=" * 60)

    elif args.command == "web":
        from video_remix.web.server import start_server
        start_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
