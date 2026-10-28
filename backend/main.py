"""PropertyMotion AI - FastAPI backend."""
import io
import logging
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import ValidationError

from config import (
    ALLOWED_EXTENSIONS, ELEVENLABS_API_KEY, FRONTEND_ORIGINS, GEMINI_API_KEY, GEMINI_MODEL,
    MAX_CONCURRENT_JOBS, MAX_IMAGE_BYTES, MAX_IMAGES, MAX_JOBS_IN_MEMORY, MAX_REQUEST_BYTES,
    MAX_TOTAL_BYTES, MIN_IMAGE_SIDE, MIN_IMAGES, OUTPUT_DIR, OUTPUT_RETENTION_HOURS, TEMP_DIR,
    TTS_ENABLED, VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH,
)
from models.schemas import GenerateResponse, JobStatusResponse, PropertyData, parse_features
from services.ai_service import generate_video_script
from services.tts_service import generate_narration
from services.video_service import VideoRenderError, assemble_video, prepare_images

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("propertymotion.api")

STAGE_QUEUED = "Queued"
STAGE_VALIDATING = "Validating uploads"
STAGE_SCRIPT = "Generating promotional script"
STAGE_NARRATION = "Creating narration"
STAGE_RENDER = "Rendering video"
STAGE_FINAL = "Finalizing output"

OUTPUT_NAME_RE = re.compile(r"^property_video_[0-9a-f]{32}\.mp4$")
FORMAT_TO_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="render")


# --------------------------------------------------------------------------- job registry (in memory)
def _create_job(job_id: str) -> None:
    now = time.time()
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id, "status": "queued", "stage": STAGE_QUEUED, "progress": 0,
            "error": None, "warnings": [], "script_source": None, "narration": None,
            "output_file": None, "video_info": None, "created_at": now, "updated_at": now,
        }
        if len(_jobs) > MAX_JOBS_IN_MEMORY:
            finished = sorted(
                (j for j in _jobs.values() if j["status"] in ("completed", "failed")),
                key=lambda j: j["updated_at"],
            )
            for old in finished[: len(_jobs) - MAX_JOBS_IN_MEMORY]:
                _jobs.pop(old["job_id"], None)


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if "progress" in fields and job["status"] != "failed":
            fields["progress"] = max(job["progress"], min(100, int(fields["progress"])))
        job.update(fields)
        job["updated_at"] = time.time()


def _snapshot(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        copy = dict(job)
        copy["warnings"] = list(job["warnings"])
        return copy


def _to_response(job: dict) -> JobStatusResponse:
    done = job["status"] == "completed" and job.get("output_file")
    return JobStatusResponse(
        job_id=job["job_id"], status=job["status"], stage=job["stage"], progress=job["progress"],
        error=job["error"], warnings=job["warnings"], script_source=job["script_source"],
        narration=job["narration"],
        filename=job["output_file"] if done else None,
        video_url=f"/outputs/{job['output_file']}" if done else None,
        download_url=f"/api/jobs/{job['job_id']}/video?download=1" if done else None,
        video_info=job["video_info"],
    )


# --------------------------------------------------------------------------- housekeeping
def _safe_rmtree(path: Path) -> None:
    for _ in range(3):  # Windows may briefly hold file handles
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.5)


def _cleanup_orphans() -> None:
    for child in TEMP_DIR.iterdir():
        if child.is_dir():
            _safe_rmtree(child)


def _purge_old_outputs() -> None:
    if OUTPUT_RETENTION_HOURS <= 0:
        return
    cutoff = time.time() - OUTPUT_RETENTION_HOURS * 3600
    for file in OUTPUT_DIR.glob("property_video_*.mp4"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink()
        except OSError:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _cleanup_orphans()
    _purge_old_outputs()
    yield


# --------------------------------------------------------------------------- app + middleware
app = FastAPI(title="PropertyMotion AI", version="1.1.0", lifespan=lifespan)


@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/api/generate-video":
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            limit_mb = MAX_TOTAL_BYTES // (1024 * 1024)
            message = f"Upload is too large. Keep the total under {limit_mb} MB."
            return JSONResponse(status_code=413, content={"detail": {"message": message, "errors": {"images": message}}})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- helpers
def _validation_error(errors: dict, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": "Please fix the highlighted fields.", "errors": errors})


def _check_image(data: bytes, name: str) -> str:
    """Return the file extension to store, or raise ValueError with a user-friendly message."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            if fmt not in FORMAT_TO_EXT:
                raise ValueError(f"'{name}' is not a JPG, PNG or WebP image.")
            if min(img.size) < MIN_IMAGE_SIDE:
                raise ValueError(f"'{name}' is too small (minimum {MIN_IMAGE_SIDE}px on the short side).")
            img.verify()
            return FORMAT_TO_EXT[fmt]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"'{name}' is not a valid or readable image.") from exc


def _safe_output_path(filename: str) -> Path:
    if not OUTPUT_NAME_RE.fullmatch(filename or ""):
        raise HTTPException(status_code=404, detail={"message": "Video not found."})
    path = (OUTPUT_DIR / filename).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail={"message": "Video not found. It may have been cleaned up."})
    return path


# --------------------------------------------------------------------------- worker
def _run_job(job_id: str, prop: PropertyData, raw_paths: list[Path], job_dir: Path) -> None:
    started = time.time()
    try:
        _update_job(job_id, status="processing", stage=STAGE_VALIDATING, progress=5)
        prepared = prepare_images(raw_paths, job_dir / "prepared")
        _update_job(job_id, progress=12)

        _update_job(job_id, stage=STAGE_SCRIPT, progress=15)
        script = generate_video_script(prop)
        warnings = [script.warning] if script.warning else []
        _update_job(job_id, script_source=script.source, warnings=list(warnings), progress=35)

        _update_job(job_id, stage=STAGE_NARRATION, progress=40)
        narration, tts_warning = generate_narration(
            script.scenes, job_dir / "audio", prop.voice_language, prop.voice_gender
        )
        if tts_warning:
            warnings.append(tts_warning)
        _update_job(job_id, narration=any(narration), warnings=list(warnings), progress=52)

        _update_job(job_id, stage=STAGE_RENDER, progress=55)
        tmp_video = job_dir / "render_tmp.mp4"
        info = assemble_video(
            script, prepared, narration, tmp_video, job_dir,
            progress_cb=lambda fraction: _update_job(job_id, progress=55 + int(40 * fraction)),
        )

        _update_job(job_id, stage=STAGE_FINAL, progress=97)
        final_path = OUTPUT_DIR / f"property_video_{job_id}.mp4"
        shutil.move(str(tmp_video), str(final_path))
        if not final_path.exists() or final_path.stat().st_size == 0:
            raise VideoRenderError("The final video file is missing or empty.")

        _update_job(job_id, status="completed", stage="Completed", progress=100,
                    output_file=final_path.name, video_info=info)
        logger.info("Job %s completed in %.1fs", job_id, time.time() - started)
    except VideoRenderError as exc:
        logger.warning("Job %s failed: %s", job_id, exc)
        _update_job(job_id, status="failed", stage="Failed", error=str(exc))
    except Exception:
        logger.exception("Job %s crashed", job_id)
        _update_job(job_id, status="failed", stage="Failed",
                    error="Something went wrong while generating the video. Please try again; details are in the backend log.")
    finally:
        _safe_rmtree(job_dir)


# --------------------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "gemini_configured": bool(GEMINI_API_KEY),
        "gemini_model": GEMINI_MODEL,
        "elevenlabs_configured": bool(ELEVENLABS_API_KEY),
        "tts_enabled": TTS_ENABLED,
        "video": f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}@{VIDEO_FPS}fps",
    }


@app.post("/api/generate-video", response_model=GenerateResponse, status_code=202)
async def generate_video(
    property_name: str = Form(""),
    location: str = Form(""),
    price: str = Form(""),
    property_type: str = Form(""),
    features: str = Form(""),
    contact: str = Form(""),
    cta: str = Form(""),
    voice_language: str = Form("en"),
    voice_gender: str = Form("female"),
    images: list[UploadFile] = File(default=[]),
):
    errors: dict[str, str] = {}

    prop: Optional[PropertyData] = None
    try:
        prop = PropertyData(
            property_name=property_name, location=location, price=price, property_type=property_type,
            features=parse_features(features), contact=contact, cta=cta,
            voice_language=voice_language, voice_gender=voice_gender,
        )
    except ValidationError as exc:
        for err in exc.errors():
            key = str(err["loc"][0]) if err["loc"] else "form"
            errors.setdefault(key, err["msg"].removeprefix("Value error, "))

    if len(images) < MIN_IMAGES:
        errors["images"] = f"Upload at least {MIN_IMAGES} photos (received {len(images)})."
    elif len(images) > MAX_IMAGES:
        errors["images"] = f"Upload at most {MAX_IMAGES} photos (received {len(images)})."
    if errors:
        raise _validation_error(errors)

    blobs: list[tuple[bytes, str]] = []
    total = 0
    for index, upload in enumerate(images, start=1):
        name = upload.filename or f"photo {index}"
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise _validation_error({"images": f"'{name}' must be a JPG, JPEG, PNG or WebP file."})
        data = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise _validation_error({"images": f"'{name}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."}, 413)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise _validation_error({"images": f"Total upload must be under {MAX_TOTAL_BYTES // (1024 * 1024)} MB."}, 413)
        try:
            ext = _check_image(data, name)
        except ValueError as exc:
            raise _validation_error({"images": str(exc)})
        blobs.append((data, ext))

    _purge_old_outputs()
    job_id = uuid.uuid4().hex
    job_dir = TEMP_DIR / job_id
    raw_dir = job_dir / "raw"
    raw_paths: list[Path] = []
    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
        for index, (data, ext) in enumerate(blobs):
            path = raw_dir / f"upload_{index:02d}.{ext}"
            path.write_bytes(data)
            raw_paths.append(path)
    except OSError:
        _safe_rmtree(job_dir)
        logger.exception("Could not store uploads")
        raise HTTPException(status_code=500, detail={"message": "The server could not store the uploaded photos."})

    _create_job(job_id)
    _executor.submit(_run_job, job_id, prop, raw_paths, job_dir)
    return GenerateResponse(job_id=job_id, status="queued", message="Video generation started")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    job = _snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"message": "Job not found. It may have expired or the server was restarted."})
    return _to_response(job)


@app.get("/api/jobs/{job_id}/video")
def get_job_video(job_id: str, download: bool = False):
    job = _snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"message": "Job not found. It may have expired or the server was restarted."})
    if job["status"] == "failed":
        raise HTTPException(status_code=409, detail={"message": job["error"] or "This job failed; there is no video."})
    if job["status"] != "completed" or not job["output_file"]:
        raise HTTPException(status_code=409, detail={"message": "The video is still being generated."})
    path = _safe_output_path(job["output_file"])
    return FileResponse(
        path, media_type="video/mp4", filename=path.name,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/outputs/{filename}")
def get_output(filename: str):
    path = _safe_output_path(filename)
    return FileResponse(path, media_type="video/mp4", filename=path.name, content_disposition_type="inline")