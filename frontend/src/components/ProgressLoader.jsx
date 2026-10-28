import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { getJob, parseApiError } from "../services/api.js";

// Must match the stage names sent by the backend.
const STAGES = [
  "Validating uploads",
  "Generating promotional script",
  "Creating narration",
  "Rendering video",
  "Finalizing output",
];

const POLL_MS = 1200;

export default function ProgressLoader({ jobId, onCompleted, onFailed }) {
  const [job, setJob] = useState(null);
  const handlers = useRef({ onCompleted, onFailed });
  handlers.current = { onCompleted, onFailed };

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let failures = 0;

    const tick = async () => {
      try {
        const data = await getJob(jobId);
        if (cancelled) return;
        failures = 0;
        setJob(data);
        if (data.status === "completed") return handlers.current.onCompleted(data);
        if (data.status === "failed") return handlers.current.onFailed(data.error || "Video generation failed.");
      } catch (err) {
        if (cancelled) return;
        const parsed = parseApiError(err);
        if (parsed.status === 404) return handlers.current.onFailed(parsed.message);
        failures += 1;
        if (failures >= 5) return handlers.current.onFailed(parsed.message);
      }
      timer = setTimeout(tick, POLL_MS);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  const progress = job?.progress ?? 0;
  const currentIndex = job ? STAGES.indexOf(job.stage) : -1;
  const queued = !job || job.status === "queued";

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <h2 className="text-xl font-semibold text-slate-900">{queued ? "Waiting to start…" : "Creating your video"}</h2>
      <p className="mt-1 text-sm text-slate-500">This usually takes 1–3 minutes. Progress below comes straight from the server.</p>

      <div className="mt-6">
        <div className="mb-2 flex justify-between text-sm">
          <span className="font-medium text-slate-700">{job?.stage || "Queued"}</span>
          <span className="tabular-nums text-slate-500">{progress}%</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-gradient-to-r from-gold-500 to-gold-400 transition-all duration-500" style={{ width: `${progress}%` }} />
        </div>
      </div>

      <ol className="mt-6 space-y-3">
        {STAGES.map((stage, index) => {
          const done = index < currentIndex;
          const active = index === currentIndex;
          return (
            <li key={stage} className="flex items-center gap-3 text-sm">
              {done ? (
                <CheckCircle2 size={18} className="text-emerald-500" />
              ) : active ? (
                <Loader2 size={18} className="animate-spin text-gold-600" />
              ) : (
                <Circle size={18} className="text-slate-300" />
              )}
              <span className={done ? "text-slate-500" : active ? "font-medium text-slate-900" : "text-slate-400"}>{stage}</span>
            </li>
          );
        })}
      </ol>

      {job?.warnings?.length > 0 && (
        <div className="mt-6 space-y-2">
          {job.warnings.map((warning) => (
            <div key={warning} className="flex gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}