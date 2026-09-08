import cgi
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

from video_remix.config import RemixConfig
from video_remix.demo_generator import generate_sample_video_and_subtitles
from video_remix.pipeline import VideoRemixPipeline

# In-memory jobs registry
JOBS: Dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class VideoRemixWebHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler for Video Remix Web GUI with JSON API and Video Streaming."""

    def log_message(self, format, *args):
        # Silence default access logs to keep terminal tidy
        pass

    def send_json(self, data: dict, status_code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Static assets and index
        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/static/style.css":
            self.serve_file(os.path.join(STATIC_DIR, "style.css"), "text/css; charset=utf-8")
        elif path == "/static/app.js":
            self.serve_file(os.path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8")

        # API: Get Config
        elif path == "/api/config":
            config = RemixConfig()
            self.send_json({
                "status": "ok",
                "config": {
                    "active_provider": config.active_provider,
                    "style": config.style,
                    "analysis_mode": "multimodal",
                    "llm_model": config.llm_model,
                    "enable_golden_hook": config.enable_golden_hook,
                    "work_dir": config.work_dir
                }
            })

        # API: Job Status
        elif path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("job_id", [None])[0]
            with JOBS_LOCK:
                if job_id and job_id in JOBS:
                    self.send_json({"status": "ok", **JOBS[job_id]})
                else:
                    self.send_json({"status": "error", "message": "Job not found"}, status_code=404)

        # Stream Media (Videos) with HTTP Range support
        elif path.startswith("/media/"):
            rel_media_path = urllib.parse.unquote(path[len("/media/"):])
            self.serve_media_with_range(rel_media_path)

        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API: Save Config
        if path == "/api/config":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}

            if "active_provider" in data:
                os.environ["ACTIVE_PROVIDER"] = data["active_provider"]
            if "style" in data:
                os.environ["REMIX_STYLE"] = data["style"]
            if "analysis_mode" in data:
                os.environ["ANALYSIS_MODE"] = data["analysis_mode"]
            if "enable_golden_hook" in data:
                os.environ["ENABLE_GOLDEN_HOOK"] = "true" if data["enable_golden_hook"] else "false"

            self.send_json({"status": "ok", "message": "Configuration updated"})

        # API: Run Built-in Demo
        elif path == "/api/demo":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
            data = json.loads(body) if body else {}
            enable_gh = data.get("enable_golden_hook", True)

            job_id = str(uuid.uuid4())
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "job_id": job_id,
                    "state": "running",
                    "current_step": 0,
                    "logs": ["启动演示任务..."],
                    "result": None,
                    "error": None
                }

            threading.Thread(target=self._run_demo_worker, args=(job_id, enable_gh), daemon=True).start()
            self.send_json({"status": "ok", "job_id": job_id})

        # API: Process User Video
        elif path == "/api/process":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body) if body else {}
            video_path = data.get("video_path")
            enable_gh = data.get("enable_golden_hook", True)

            if not video_path or not os.path.exists(video_path):
                self.send_json({"status": "error", "message": "Video file not found"}, status_code=400)
                return

            job_id = str(uuid.uuid4())
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "job_id": job_id,
                    "state": "running",
                    "current_step": 0,
                    "logs": [f"开始处理视频: {video_path}"],
                    "result": None,
                    "error": None
                }

            threading.Thread(target=self._run_process_worker, args=(job_id, video_path, enable_gh), daemon=True).start()
            self.send_json({"status": "ok", "job_id": job_id})

        # API: Upload Video File
        elif path == "/api/upload":
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self.send_json({"status": "error", "message": "Content-Type must be multipart/form-data"}, status_code=400)
                return

            upload_dir = os.path.join(".video_remix_work", "uploads")
            os.makedirs(upload_dir, exist_ok=True)

            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type}
            )

            file_item = form["video"] if "video" in form else None
            if file_item is None or not file_item.filename:
                self.send_json({"status": "error", "message": "No file uploaded"}, status_code=400)
                return

            safe_filename = re.sub(r"[^\w\.-]", "_", file_item.filename)
            saved_path = os.path.abspath(os.path.join(upload_dir, f"{int(time.time())}_{safe_filename}"))

            with open(saved_path, "wb") as f:
                f.write(file_item.file.read())

            self.send_json({
                "status": "ok",
                "file_path": saved_path,
                "filename": safe_filename
            })

        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def _run_demo_worker(self, job_id: str, enable_gh: bool = True):
        def log(msg, step=None):
            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["logs"].append(msg)
                    if step is not None:
                        JOBS[job_id]["current_step"] = step

        try:
            log("🎬 正在合成测试样片...", step=0)
            demo_video, _ = generate_sample_video_and_subtitles("demo_source.mp4", "demo_source.srt")
            log(f"样片就绪: {demo_video}")

            config = RemixConfig()
            pipeline = VideoRemixPipeline(config=config)

            log("[1/4] 探测视频信息...", step=1)
            orig_dur = pipeline.media_helper.get_duration(demo_video)
            log(f"源视频时长: {orig_dur:.2f}s")

            log("[2/4] 多模态 AI 原生视听审片与剪辑策划...", step=2)
            plan = pipeline.multimodal_agent.plan_from_video(
                demo_video, orig_dur, style=config.style
            )

            log(f"成片标题: {plan.title}")
            if plan.golden_hook and enable_gh:
                gh = plan.golden_hook
                log(f"  ⚡️ 黄金3秒钩子: {gh.start:.1f}s -> {gh.end:.1f}s [{gh.duration:.1f}s] | {gh.punchline}")
            if plan.discarded_total_duration > 0:
                log(f"  过滤冗余时长: {plan.discarded_total_duration:.1f}s")
            for i, c in enumerate(plan.clips, 1):
                log(f"  - Clip {i} [{c.narrative_role}]: {c.start:.1f}s -> {c.end:.1f}s | {c.title}")

            active_gh = plan.golden_hook if enable_gh else None

            log("[3/4] FFmpeg 智能分切与无损拼接渲染...", step=3)
            out_video = "output/demo_remix.mp4"
            pipeline.assembler.assemble(
                demo_video, plan.clips, out_video,
                temp_dir=os.path.join(config.work_dir, "clips"),
                golden_hook=active_gh
            )
            remix_dur = pipeline.media_helper.get_duration(out_video)

            log("[4/4] 导出剪映 (JianYing / CapCut) 原生工程草稿...", step=4)
            out_draft = "output/demo_jianying_draft"
            pipeline.draft_generator.export_draft(
                demo_video, plan.clips, plan.title, out_draft,
                golden_hook=active_gh
            )

            result_dict = {
                "source_video": os.path.abspath(demo_video),
                "output_video": os.path.abspath(out_video),
                "draft_dir": os.path.abspath(out_draft),
                "original_duration": orig_dur,
                "remix_duration": remix_dur,
                "compression_ratio": (remix_dur / orig_dur * 100) if orig_dur > 0 else 0,
                "plan": plan.to_dict()
            }

            with JOBS_LOCK:
                JOBS[job_id]["state"] = "completed"
                JOBS[job_id]["result"] = result_dict

        except Exception as e:
            log(f"❌ 演示任务异常: {e}", step=-1)
            with JOBS_LOCK:
                JOBS[job_id]["state"] = "error"
                JOBS[job_id]["job_status"] = "failed"
                JOBS[job_id]["error"] = str(e)

    def _run_process_worker(self, job_id: str, video_path: str, enable_gh: bool = True):
        def log(msg, step=None):
            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["logs"].append(msg)
                    if step is not None:
                        JOBS[job_id]["current_step"] = step

        try:
            config = RemixConfig()
            pipeline = VideoRemixPipeline(config=config)
            base_name = os.path.splitext(os.path.basename(video_path))[0]

            log(f"[1/4] 探测源视频: {video_path}...", step=1)
            orig_dur = pipeline.media_helper.get_duration(video_path)
            log(f"源视频时长: {orig_dur:.2f}s")

            log(f"[2/4] 多模态 AI 原生视听审片 (渠道: {config.active_provider})...", step=2)
            plan = pipeline.multimodal_agent.plan_from_video(
                video_path, orig_dur, style=config.style
            )

            log(f"成片标题: {plan.title}")
            if plan.golden_hook and enable_gh:
                gh = plan.golden_hook
                log(f"  ⚡️ 黄金3秒钩子: {gh.start:.1f}s -> {gh.end:.1f}s [{gh.duration:.1f}s] | {gh.punchline}")
            if plan.discarded_total_duration > 0:
                log(f"  过滤冗余时长: {plan.discarded_total_duration:.1f}s")
            for i, c in enumerate(plan.clips, 1):
                log(f"  - Clip {i} [{c.narrative_role}]: {c.start:.1f}s -> {c.end:.1f}s | {c.title}")

            active_gh = plan.golden_hook if enable_gh else None

            log("[3/4] FFmpeg 智能分切与无损拼接渲染...", step=3)
            out_video = os.path.join("output", f"{base_name}_remix.mp4")
            pipeline.assembler.assemble(
                video_path, plan.clips, out_video,
                temp_dir=os.path.join(config.work_dir, "clips"),
                golden_hook=active_gh
            )
            remix_dur = pipeline.media_helper.get_duration(out_video)

            log("[4/4] 导出剪映 (JianYing / CapCut) 原生工程草稿...", step=4)
            out_draft = os.path.join("output", f"{base_name}_jianying_draft")
            pipeline.draft_generator.export_draft(
                video_path, plan.clips, plan.title, out_draft,
                golden_hook=active_gh
            )

            result_dict = {
                "source_video": os.path.abspath(video_path),
                "output_video": os.path.abspath(out_video),
                "draft_dir": os.path.abspath(out_draft),
                "original_duration": orig_dur,
                "remix_duration": remix_dur,
                "compression_ratio": (remix_dur / orig_dur * 100) if orig_dur > 0 else 0,
                "plan": plan.to_dict()
            }

            with JOBS_LOCK:
                JOBS[job_id]["state"] = "completed"
                JOBS[job_id]["result"] = result_dict

        except Exception as e:
            log(f"❌ 剪辑处理异常: {e}", step=-1)
            with JOBS_LOCK:
                JOBS[job_id]["state"] = "error"
                JOBS[job_id]["job_status"] = "failed"
                JOBS[job_id]["error"] = str(e)

    def serve_file(self, file_path: str, content_type: str):
        if not os.path.exists(file_path):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_media_with_range(self, rel_path: str):
        """Supports HTTP 206 Partial Content Range requests for video playback and seeking."""
        abs_path = os.path.abspath(rel_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            self.send_error(HTTPStatus.NOT_FOUND, f"Media file not found: {rel_path}")
            return

        file_size = os.path.getsize(abs_path)
        range_header = self.headers.get("Range")

        content_type = "video/mp4"
        if abs_path.endswith(".wav"):
            content_type = "audio/wav"
        elif abs_path.endswith(".mp3"):
            content_type = "audio/mpeg"

        if range_header:
            # Parse Range: bytes=start-end
            match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else file_size - 1
                end = min(end, file_size - 1)
                length = end - start + 1

                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                try:
                    with open(abs_path, "rb") as f:
                        f.seek(start)
                        bytes_left = length
                        while bytes_left > 0:
                            chunk_size = min(64 * 1024, bytes_left)
                            data = f.read(chunk_size)
                            if not data:
                                break
                            self.wfile.write(data)
                            bytes_left -= len(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

        # Full file transfer
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        try:
            with open(abs_path, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def start_server(host: str = "127.0.0.1", port: int = 8765):
    """Start the multi-threaded HTTP server."""
    server = ThreadingHTTPServer((host, port), VideoRemixWebHandler)
    print(f"\n=======================================================", flush=True)
    print(f"🚀 Video Remix AI 可视化 Web 工作台已启动！", flush=True)
    print(f"👉 请在浏览器中打开: http://{host}:{port}", flush=True)
    print(f"=======================================================\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止 Web 服务器...")
        server.server_close()


if __name__ == "__main__":
    start_server()
