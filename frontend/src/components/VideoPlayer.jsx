import { useState } from "react";
import { AlertTriangle, Download, Loader2, Mic, MicOff, RotateCcw, Sparkles } from "lucide-react";
import { downloadVideo, parseApiError, resolveUrl } from "../services/api.js";

function Stat({ label, value }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="truncate text-sm font-medium text-slate-800">{value}</p>
    </div>
  );
}

export default function VideoPlayer({ job, onReset }) {
  const [playbackError, setPlaybackError] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  const info = job.video_info || {};
  const src = resolveUrl(job.video_url);

  const handleDownload = async () => {
    setDownloading(true);
    setDownloadError("");
    try {
      await downloadVideo(job);
    } catch (err) {
      setDownloadError(parseApiError(err).message || "Download failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <div className="grid gap-8 md:grid-cols-[minmax(0,320px)_1fr]">
        <div>
          {playbackError ? (
            <div className="flex aspect-[9/16] flex-col items-center justify-center gap-2 rounded-2xl bg-slate-100 p-6 text-center text-sm text-slate-600">
              <AlertTriangle className="text-amber-500" />
              The video could not be played in this browser. Try downloading it instead.
            </div>
          ) : (
            <video
              key={src}
              src={src}
              controls
              playsInline
              preload="metadata"
              onError={() => setPlaybackError(true)}
              className="aspect-[9/16] w-full rounded-2xl bg-black object-contain shadow-lg"
            />
          )}
        </div>

        <div className="flex flex-col">
          <h2 className="text-xl font-semibold text-slate-900">Your video is ready</h2>
          <p className="mt-1 text-sm text-slate-500">Preview it, download the MP4, or start another one.</p>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <Stat label="File" value={job.filename} />
            <Stat label="Duration" value={info.duration ? `${info.duration}s` : "—"} />
            <Stat label="Resolution" value={info.width ? `${info.width}×${info.height}` : "—"} />
            <Stat label="Size" value={info.size_bytes ? `${(info.size_bytes / 1048576).toFixed(1)} MB` : "—"} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
              <Sparkles size={12} /> Script: {job.script_source === "gemini" ? "Gemini" : "Template fallback"}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">
              {job.narration ? <Mic size={12} /> : <MicOff size={12} />} {job.narration ? "Narrated" : "No narration"}
            </span>
          </div>

          {job.warnings?.length > 0 && (
            <div className="mt-4 space-y-2">
              {job.warnings.map((w) => (
                <div key={w} className="flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}

          {downloadError && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">{downloadError}</p>}

          <div className="mt-auto flex flex-wrap gap-3 pt-6">
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
            >
              {downloading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
              {downloading ? "Downloading…" : "Download MP4"}
            </button>
            <button onClick={onReset} className="inline-flex items-center gap-2 rounded-xl border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
              <RotateCcw size={16} /> Generate another
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}