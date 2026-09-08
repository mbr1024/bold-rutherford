import os
import subprocess
from typing import Tuple


def generate_sample_video_and_subtitles(
    output_video_path: str = "sample_video.mp4",
    output_srt_path: str = "sample_video.srt",
    ffmpeg_path: str = "ffmpeg"
) -> Tuple[str, str]:
    """Generate a clean synthetic 45-second test video with 4 distinct scenes and an accompanying SRT subtitle file.

    Scene breakdown:
    - 00:00 - 00:08 (8s) : [Intro] 大家好，欢迎来到本期深度访谈，今天我们聊聊AI二创的未来。
    - 00:08 - 00:18 (10s): [Filler] 稍微喝一口水，大家平时看短视频多还是中视频多？弹幕扣个1。
    - 00:18 - 00:32 (14s): [Climax] 核心颠覆点来了：传统的机械拼接必死无疑，未来的核心竞争是叙事重构能力！
    - 00:32 - 00:38 (6s) : [Filler] 现场的麦克风稍微调一下，我们刚才说到哪里了。
    - 00:38 - 00:45 (7s) : [Conclusion] 总结一句话：用AI赋能创意，而不是被AI取代，这就是破局关键！
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)) or ".", exist_ok=True)

    # 45-second synthetic video with color changes and sine audio tones
    filter_complex = (
        "color=c=navy:s=640x360:d=8[v0];"
        "color=c=gray:s=640x360:d=10[v1];"
        "color=c=crimson:s=640x360:d=14[v2];"
        "color=c=gray:s=640x360:d=6[v3];"
        "color=c=darkgreen:s=640x360:d=7[v4];"
        "[v0][v1][v2][v3][v4]concat=n=5:v=1:a=0[v];"
        "sine=f=440:d=8[a0];"
        "sine=f=220:d=10[a1];"
        "sine=f=880:d=14[a2];"
        "sine=f=220:d=6[a3];"
        "sine=f=520:d=7[a4];"
        "[a0][a1][a2][a3][a4]concat=n=5:v=0:a=1[a]"
    )

    cmd = [
        ffmpeg_path,
        "-y",
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        output_video_path
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to generate synthetic demo video: {res.stderr}")

    # Write matching SRT
    srt_content = """1
00:00:00,000 --> 00:00:08,000
大家好，欢迎来到本期深度访谈，今天我们聊聊AI二创的未来。

2
00:00:08,000 --> 00:00:18,000
稍微喝一口水，大家平时看短视频多还是中视频多？弹幕扣个1。

3
00:00:18,000 --> 00:00:32,000
核心颠覆点来了：传统的机械拼接必死无疑，未来的核心竞争是叙事重构能力！

4
00:00:32,000 --> 00:00:38,000
现场的麦克风稍微调一下，我们刚才说到哪里了。

5
00:00:38,000 --> 00:00:45,000
总结一句话：用AI赋能创意，而不是被AI取代，这就是破局关键！
"""
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content.strip() + "\n")

    return output_video_path, output_srt_path


if __name__ == "__main__":
    v, s = generate_sample_video_and_subtitles()
    print(f"Generated sample video: {v}, subtitles: {s}")
