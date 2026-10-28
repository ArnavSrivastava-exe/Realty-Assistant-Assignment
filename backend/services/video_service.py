"""Video rendering: Pillow-composed frames + MoviePy 2.x timeline + FFmpeg (H.264/AAC)."""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from proglog import ProgressBarLogger

from config import FONT_PATH, TRANSITION_SECONDS, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH
from models.schemas import VideoScript

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    VideoClip,
    VideoFileClip,
    vfx,
)

logger = logging.getLogger("propertymotion.video")

GOLD = (255, 214, 102, 255)
WHITE = (255, 255, 255, 255)


class VideoRenderError(Exception):
    """Raised with a user-presentable message."""


# --------------------------------------------------------------------------- image preparation
def prepare_images(raw_paths: list[Path], out_dir: Path) -> list[Path]:
    """Fully decode, fix EXIF rotation, convert to RGB JPEG, cap size at 2000 px."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[Path] = []
    for index, raw in enumerate(raw_paths, start=1):
        dest = out_dir / f"photo_{index:02d}.jpg"
        try:
            with Image.open(raw) as img:
                img.load()
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                img.save(dest, "JPEG", quality=92)
        except Exception as exc:
            raise VideoRenderError(
                f"Photo {index} could not be read ({type(exc).__name__}). "
                "Please re-export it as a standard JPG or PNG."
            ) from exc
        prepared.append(dest)
    return prepared


# --------------------------------------------------------------------------- frame composition
@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        FONT_PATH,
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    nw, nh = max(w, round(img.width * scale)), max(h, round(img.height * scale))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _contain(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.Resampling.LANCZOS)


def build_photo_layer(path: str, w: int, h: int) -> Image.Image:
    """Portrait photos fill the frame; wider photos sit on a blurred copy of themselves (never stretched)."""
    img = Image.open(path).convert("RGB")
    if img.width / img.height < 0.85:
        return _cover(img, w, h)
    bg = _cover(img, w, h).filter(ImageFilter.GaussianBlur(radius=max(12, w // 28)))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    fg = _contain(img, w, int(h * 0.58))
    bg.paste(fg, ((w - fg.width) // 2, int(h * 0.43 - fg.height / 2)))
    return bg


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def build_overlay(caption: str, scene_type: str, w: int, h: int) -> Image.Image:
    """Static RGBA overlay: bottom gradient + caption panel (kept out of the zooming photo layer)."""
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    gradient_h = int(h * 0.5)
    grad = np.zeros((gradient_h, w, 4), dtype=np.uint8)
    grad[..., 3] = np.linspace(0, 170, gradient_h).astype(np.uint8)[:, None]
    overlay.alpha_composite(Image.fromarray(grad), (0, h - gradient_h))

    draw = ImageDraw.Draw(overlay)
    margin = int(w * 0.08)
    pad = int(w * 0.05)
    max_text_w = w - 2 * margin - 2 * pad

    size = int(w * 0.075) if scene_type in ("intro", "outro") else int(w * 0.066)
    font = _font(size)
    lines = _wrap(draw, caption, font, max_text_w)
    while len(lines) > 5 and size > int(w * 0.04):
        size -= 2
        font = _font(size)
        lines = _wrap(draw, caption, font, max_text_w)

    line_h = int(size * 1.28)
    panel_h = line_h * len(lines) + 2 * pad + 6
    panel_bottom = int(h * 0.9)
    panel_top = panel_bottom - panel_h
    draw.rounded_rectangle((margin, panel_top, w - margin, panel_bottom), radius=int(w * 0.04), fill=(12, 16, 28, 190))

    accent_y = panel_top + int(pad * 0.45)
    draw.rectangle((w // 2 - int(w * 0.06), accent_y - 3, w // 2 + int(w * 0.06), accent_y + 3), fill=GOLD)

    y = panel_top + pad + 6
    for index, line in enumerate(lines):
        color = GOLD if (scene_type == "outro" and index == 0) else WHITE
        x = (w - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill=color, stroke_width=1, stroke_fill=(0, 0, 0, 160))
        y += line_h
    return overlay


def _segment_clip(photo: Image.Image, overlay: Image.Image, duration: float, zoom_in: bool) -> VideoClip:
    """Slow Ken-Burns zoom on the photo; overlay stays perfectly static."""
    base = photo.convert("RGB")
    w, h = base.size
    zoom = 0.06

    def frame(t: float):
        progress = min(max(t / duration, 0.0), 1.0)
        scale = 1.0 + zoom * (progress if zoom_in else 1.0 - progress)
        cw, ch = w / scale, h / scale
        x0, y0 = (w - cw) / 2, (h - ch) / 2
        img = base.resize((w, h), Image.Resampling.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)).convert("RGBA")
        img.alpha_composite(overlay)
        return np.array(img.convert("RGB"))

    return VideoClip(frame_function=frame, duration=duration)


# --------------------------------------------------------------------------- planning
def _assign_images(n_scenes: int, images: list) -> list[list]:
    """Use every photo, in the order uploaded."""
    m = len(images)
    if m == n_scenes:
        return [[p] for p in images]
    if m < n_scenes:
        plan = [[images[i % m]] for i in range(n_scenes - 1)]
        plan.append([images[0]])  # closing scene returns to the cover photo
        return plan
    counts = [1] * n_scenes
    order = list(range(1, n_scenes - 1)) + [0, n_scenes - 1]  # extra photos go to feature scenes first
    for k in range(m - n_scenes):
        counts[order[k % len(order)]] += 1
    plan, cursor = [], 0
    for count in counts:
        plan.append(list(images[cursor:cursor + count]))
        cursor += count
    return plan


class _RenderLogger(ProgressBarLogger):
    """Turns MoviePy's frame bar into 0..1 progress callbacks."""

    def __init__(self, callback: Callable[[float], None]):
        super().__init__(min_time_interval=0.5)
        self._callback = callback

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr != "index" or bar not in ("frame_index", "t"):
            return
        total = self.bars.get(bar, {}).get("total")
        if total:
            try:
                self._callback(min(value / total, 1.0))
            except Exception:
                pass


def _verify_video(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise VideoRenderError("The renderer produced an empty video file.")
    try:
        with VideoFileClip(str(path)) as clip:
            clip.get_frame(min(0.5, max(clip.duration - 0.1, 0)))
            return {
                "duration": round(float(clip.duration), 2),
                "width": int(clip.w),
                "height": int(clip.h),
                "fps": round(float(clip.fps or VIDEO_FPS), 2),
                "has_audio": clip.audio is not None,
                "size_bytes": path.stat().st_size,
            }
    except Exception as exc:
        raise VideoRenderError(f"The rendered MP4 could not be opened for verification ({type(exc).__name__}).") from exc


# --------------------------------------------------------------------------- main entry point
def assemble_video(
    script_data: VideoScript,
    image_paths: list,
    narration: Optional[list],
    output_path: Path,
    work_dir: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> dict:
    """Render the promo video to `output_path` (a temp path) and return verified file info."""
    report = progress_cb or (lambda _f: None)
    width, height, fps = VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
    scenes = script_data.scenes
    if not image_paths:
        raise VideoRenderError("No photos were available for rendering.")

    assignments = _assign_images(len(scenes), [str(p) for p in image_paths])

    durations: list[float] = []
    for index, scene in enumerate(scenes):
        clip_info = narration[index] if narration and index < len(narration) else None
        hint = float(scene.duration_hint)
        durations.append(max(hint, clip_info.duration + 1.0) if clip_info else hint)
    total = sum(durations)

    video = None
    video_clips: list = []
    audio_clips: list = []
    photo_cache: dict[str, Image.Image] = {}
    fade = TRANSITION_SECONDS

    try:
        cursor = 0.0
        segment_index = 0
        for index, scene in enumerate(scenes):
            overlay = build_overlay(scene.caption, scene.type, width, height)
            photos = assignments[index]
            segment_len = durations[index] / len(photos)
            for j, photo_path in enumerate(photos):
                if photo_path not in photo_cache:
                    photo_cache[photo_path] = build_photo_layer(photo_path, width, height)
                start = cursor + j * segment_len
                is_last = index == len(scenes) - 1 and j == len(photos) - 1
                clip = _segment_clip(
                    photo_cache[photo_path], overlay,
                    segment_len + (0 if is_last else fade),   # tail runs under the next clip's fade-in
                    zoom_in=(segment_index % 2 == 0),
                ).with_start(start)
                if segment_index == 0:
                    clip = clip.with_effects([vfx.FadeIn(0.5)])
                else:
                    clip = clip.with_effects([vfx.CrossFadeIn(fade)])
                if is_last:
                    clip = clip.with_effects([vfx.FadeOut(0.7)])
                video_clips.append(clip)
                segment_index += 1

            clip_info = narration[index] if narration and index < len(narration) else None
            if clip_info:
                audio_clips.append(AudioFileClip(clip_info.path).with_start(cursor + 0.35))
            cursor += durations[index]
            report(0.1 * (index + 1) / len(scenes))

        video = CompositeVideoClip(video_clips, size=(width, height)).with_duration(total)
        if audio_clips:
            video = video.with_audio(CompositeAudioClip(audio_clips))

        render_logger = _RenderLogger(lambda f: report(0.1 + 0.9 * f))
        video.write_videofile(
            str(output_path),
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            preset="veryfast",
            threads=os.cpu_count() or 2,
            pixel_format="yuv420p",
            ffmpeg_params=["-movflags", "+faststart"],
            temp_audiofile_path=str(work_dir),
            logger=render_logger,
        )
    except VideoRenderError:
        raise
    except Exception as exc:
        logger.exception("Rendering failed")
        raise VideoRenderError(
            f"Video rendering failed ({type(exc).__name__}). Check the backend console for details."
        ) from exc
    finally:
        for item in [video, *video_clips, *audio_clips]:
            try:
                if item is not None:
                    item.close()
            except Exception:
                pass

    info = _verify_video(output_path)
    info["scene_count"] = len(scenes)
    info["photos_used"] = len(image_paths)
    return info