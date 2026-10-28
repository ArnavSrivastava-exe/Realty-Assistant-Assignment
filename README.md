# PropertyMotion AI

Turn property details and 4-8 photos into a narrated, captioned 9:16 promotional video (MP4).

## 1. Overview

Real estate teams need short promo videos for every listing, but editing them by hand is slow.
PropertyMotion AI takes a listing form plus photos and automatically:

1. writes a structured script with **Google Gemini** (using only the facts you supply),
2. narrates it with **gTTS**,
3. renders an MP4 with **MoviePy** (Ken-Burns motion, cross-fades, readable captions),
4. lets you preview and download it in the browser.

No paid AI video API is used.

## 2. Features and limitations

Features
- Real background jobs with real progress (queued -> processing -> completed/failed).
- Gemini structured JSON output, validated; limited retries; clearly-labelled template fallback.
- Fact guard: output containing numbers or "invented claim" words (spacious, modern, nearby...) that you did not supply is rejected and retried.
- Narration is never cut off: scene length = max(duration hint, narration length + 1 s).
- Portrait 1080x1920-style layout (default 720x1280), landscape photos get a blurred background (no stretching).
- Frontend + backend validation, upload size limits, magic-byte image verification, path-traversal-safe file serving.

Limitations
- Jobs live in memory: they are lost if the backend restarts (the UI shows a clear message).
- Portrait output only. No background music (no licensed asset is bundled).
- gTTS needs internet. If TTS fails, the video is rendered silently and the UI says so.
- Run ONE uvicorn worker (the job registry is per-process).
- Video length follows narration; it is usually 20-40 s but is never truncated to hit a number.

## 3. Architecture

```
React (Vite) --multipart POST--> FastAPI /api/generate-video
                                   |  validates fields + images, saves to temp_uploads/<job_id>/
                                   |  returns {job_id, status: queued}
                                   v
                         ThreadPoolExecutor (1 worker)
                           1. Validating uploads  (Pillow decode, normalise)
                           2. Generating script   (Gemini -> validate -> retry -> template fallback)
                           3. Creating narration  (gTTS per scene)
                           4. Rendering video     (Pillow frames + MoviePy + FFmpeg/libx264/AAC)
                           5. Finalizing output   (move to outputs/, verify, cleanup temp)
React polls GET /api/jobs/{id} every ~1.2 s -> shows real stage/progress
Completed -> <video> plays /outputs/property_video_<id>.mp4, download via /api/jobs/{id}/video?download=1
```

## 4. Tech stack

React 18, Vite, Tailwind CSS v4, Lucide, Axios | FastAPI, Uvicorn, Pydantic v2 | google-genai, gTTS, MoviePy 2.x, Pillow, NumPy.

## 5. Prerequisites (Windows)

- Python 3.11 or 3.12 (https://www.python.org/downloads/) - tick "Add to PATH"
- Node.js 20+ and npm
- FFmpeg: **not required separately** (MoviePy uses the bundled `imageio-ffmpeg`). Optional system install: `winget install Gyan.FFmpeg`

## 6. Get a Gemini API key

1. Open https://aistudio.google.com/apikey and sign in.
2. Click "Create API key" and copy it.
3. Put it in `backend/.env` as `GEMINI_API_KEY=...` (never commit this file).
4. To change model, edit `GEMINI_MODEL` in `.env` (e.g. `gemini-2.5-flash`). If you get a "model unavailable" warning, pick a model your key can access from AI Studio.

## 7. Setup and run

Backend (PowerShell):

```
cd property-video-generator\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn main:app --host 127.0.0.1 --port 8000
```

If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Avoid `--reload` while testing: a reload wipes the in-memory job list.

Frontend (second terminal):

```
cd property-video-generator\frontend
npm install
copy .env.example .env
npm run dev
```

Open http://localhost:5173.

## 8. Environment variables

backend/.env

| Variable | Default | Meaning |
|---|---|---|
| GEMINI_API_KEY | (empty) | Gemini key. Empty -> template script fallback |
| GEMINI_MODEL | gemini-2.5-flash | Model name |
| FRONTEND_ORIGIN | http://localhost:5173 | CORS origin(s), comma separated |
| GEMINI_TIMEOUT_SECONDS | 40 | Per-request timeout |
| GEMINI_MAX_ATTEMPTS | 3 | Attempts before template fallback |
| VIDEO_WIDTH / VIDEO_HEIGHT / VIDEO_FPS | 720 / 1280 / 24 | Output format (use 1080 / 1920 for HD, slower) |
| TTS_ENABLED / TTS_LANG / TTS_TLD | true / en / com | Narration settings (TTS_TLD=co.in for Indian English accent) |
| FONT_PATH | (empty) | Optional .ttf for captions |
| MAX_CONCURRENT_JOBS | 1 | Parallel renders |
| OUTPUT_RETENTION_HOURS | 24 | Old videos are deleted (0 = keep forever) |

frontend/.env: `VITE_API_BASE_URL=http://localhost:8000` (no secrets ever go here).

Upload limits: JPG/JPEG/PNG/WebP, 4-8 photos, 10 MB each, 60 MB total, minimum 400 px on the short side.

## 9. API

`GET /api/health`
```
{"status":"ok","gemini_configured":true,"gemini_model":"gemini-2.5-flash","tts_enabled":true,"video":"720x1280@24fps"}
```

`POST /api/generate-video` (multipart: property_name, location, price, property_type, features [JSON array string], contact, cta, images x4-8)
```
curl.exe -X POST http://localhost:8000/api/generate-video ^
  -F "property_name=Maple Court 3BHK" -F "location=Riverside Road, Pune" -F "price=Rs 1.25 Cr" ^
  -F "property_type=Apartment" -F "features=[\"3 BHK apartment\",\"Modular kitchen\"]" ^
  -F "cta=Book your site visit today" -F "contact=+91 90000 00000" ^
  -F "images=@sample_data/images/sample_01.jpg" -F "images=@sample_data/images/sample_02.jpg" ^
  -F "images=@sample_data/images/sample_03.jpg" -F "images=@sample_data/images/sample_04.jpg"
```
-> `202 {"job_id":"...","status":"queued","message":"Video generation started"}`
Validation errors -> `422 {"detail":{"message":"...","errors":{"field":"msg"}}}`

`GET /api/jobs/{job_id}`
```
{"job_id":"..","status":"processing","stage":"Rendering video","progress":72,"error":null,"warnings":[],
 "script_source":"gemini","narration":true,"filename":null,"video_url":null,"download_url":null,"video_info":null}
```
`404` for unknown jobs (including after a restart).

`GET /api/jobs/{job_id}/video[?download=1]` -> MP4, or `409` if not finished / failed.
`GET /outputs/{filename}` -> MP4 only if the name matches `property_video_<32 hex>.mp4`.

## 10. Test data

- Listing: `sample_data/property.json` (the form also has a "Load sample listing" button).
- Photos: `python sample_data\generate_sample_images.py` creates 6 synthetic illustrations in `sample_data\images\` (synthetic = safe to commit). Real photos from your own camera or royalty-free sites also work.

## 11. Generating a video

1. Click "Load sample listing" (or fill the form).
2. Drag 4-8 photos in (first photo = cover/hero shot).
3. Click "Generate video", watch the stages, then play/download.
4. The MP4 is also saved in `backend\outputs\`. Copy one to `sample_data\sample_output.mp4` for your submission.

## 12. Troubleshooting

- **"GEMINI_API_KEY is not configured"** -> check `backend/.env`, restart backend.
- **Quota / 429** -> wait or use another key/model; the template fallback is used meanwhile (the UI says so).
- **"Model unavailable" / 404** -> change `GEMINI_MODEL`.
- **Narration missing** -> gTTS needs internet; check firewall/VPN.
- **Garbled or missing glyphs (e.g. rupee sign)** -> set `FONT_PATH=C:\Windows\Fonts\segoeuib.ttf` in `.env`.
- **MoviePy import errors** -> make sure `pip install -r requirements.txt` ran in the activated venv and MoviePy is 2.x (`pip show moviepy`).
- **FFmpeg errors** -> `pip install -U imageio-ffmpeg`, or install system FFmpeg and add it to PATH.
- **CORS error in browser** -> `FRONTEND_ORIGIN` must match the URL shown by Vite.
- **"Job not found"** -> the backend restarted; start again.

## 13. Security notes

API key only in backend `.env`; never returned by any endpoint or logged. Uploads are extension- and content-checked, renamed server-side, size-limited. Only `property_video_<hex>.mp4` files can be served. Temp folders are deleted after every job (success or failure) and at startup.