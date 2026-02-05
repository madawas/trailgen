from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise FFmpegError("ffmpeg not found in PATH. Install ffmpeg to encode videos.")


def encode_video(
    frames_dir: Path,
    output_path: Path,
    fps: int,
    crf: int,
    preset: str,
) -> None:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pattern = str(frames_dir / "frame_%06d.png")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-crf",
        str(crf),
        "-preset",
        preset,
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(result.stderr.strip())
