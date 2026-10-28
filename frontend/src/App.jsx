import { useEffect, useState } from "react";
import { AlertCircle, Clapperboard, RotateCcw, ServerCrash } from "lucide-react";
import PropertyForm from "./components/PropertyForm.jsx";
import ProgressLoader from "./components/ProgressLoader.jsx";
import VideoPlayer from "./components/VideoPlayer.jsx";
import { checkHealth, createJob, parseApiError } from "./services/api.js";

const STEPS = [
  ["Enter details", "Name, location, price, features and a call to action."],
  ["Upload 4–8 photos", "Your first photo becomes the cover shot."],
  ["AI writes the script", "Gemini uses only the facts you provide."],
  ["Narrate & render", "Voice-over, captions and transitions are assembled into an MP4."],
];

export default function App() {
  const [view, setView] = useState("form"); // form | processing | result | failed
  const [jobId, setJobId] = useState(null);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [failure, setFailure] = useState("");
  const [backend, setBackend] = useState(null); // null = checking, object = ok, false = down

  useEffect(() => {
    checkHealth().then(setBackend).catch(() => setBackend(false));
  }, []);

  const handleSubmit = async (formData) => {
    setSubmitting(true);
    setFormError("");
    setFieldErrors({});
    try {
      const created = await createJob(formData);
      setJobId(created.job_id);
      setView("processing");
    } catch (err) {
      const parsed = parseApiError(err);
      setFormError(parsed.message);
      setFieldErrors(parsed.fieldErrors || {});
    } finally {
      setSubmitting(false);
    }
  };

  const backToForm = () => {
    setView("form");
    setResult(null);
    setJobId(null);
    setFailure("");
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900 text-gold-400">
              <Clapperboard size={18} />
            </span>
            <span className="text-lg font-semibold tracking-tight">
              PropertyMotion <span className="text-gold-600">AI</span>
            </span>
          </div>
          <span className="hidden text-sm text-slate-500 sm:block">Promo videos for real estate teams</span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        <div className="mb-8 max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Turn a listing into a narrated video in minutes.</h1>
          <p className="mt-3 text-slate-600">Add the property details and photos. PropertyMotion writes the script, records the voice-over and renders a vertical MP4 ready to share.</p>
        </div>

        {backend === false && (
          <div className="mb-6 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            <ServerCrash size={18} className="mt-0.5 shrink-0" />
            <span>The backend is not reachable. Start it with <code className="rounded bg-red-100 px-1">uvicorn main:app --port 8000</code> and reload this page.</span>
          </div>
        )}
        {backend && !backend.gemini_configured && (
          <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
            No Gemini API key is configured on the backend, so a clearly-labelled template script will be used.
          </div>
        )}

        {formError && view === "form" && (
          <div className="mb-6 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            <AlertCircle size={18} className="mt-0.5 shrink-0" />
            <span>{formError}</span>
          </div>
        )}

        {/* Form stays mounted (hidden) so photos and text survive a failed run. */}
        <div className={view === "form" ? "grid gap-8 lg:grid-cols-[1fr_340px]" : "hidden"}>
          <PropertyForm onSubmit={handleSubmit} submitting={submitting} serverErrors={fieldErrors} />
          <aside className="space-y-4 lg:sticky lg:top-8 lg:self-start">
            <div className="rounded-3xl border border-slate-200 bg-white p-6">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">How it works</h3>
              <ol className="mt-4 space-y-4">
                {STEPS.map(([title, text], index) => (
                  <li key={title} className="flex gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">{index + 1}</span>
                    <div>
                      <p className="text-sm font-medium">{title}</p>
                      <p className="text-xs text-slate-500">{text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="rounded-3xl bg-slate-900 p-6 text-sm text-slate-300">
              <p className="font-semibold text-white">Accuracy first</p>
              <p className="mt-2 text-xs leading-relaxed">The script may only repeat the details you enter. If Gemini invents a number or claim, it is rejected and a safe template is used instead — and the app tells you.</p>
            </div>
          </aside>
        </div>

        {view === "processing" && jobId && (
          <div className="mx-auto max-w-2xl">
            <ProgressLoader
              jobId={jobId}
              onCompleted={(job) => {
                setResult(job);
                setView("result");
              }}
              onFailed={(message) => {
                setFailure(message);
                setView("failed");
              }}
            />
          </div>
        )}

        {view === "result" && result && (
          <div className="mx-auto max-w-4xl">
            <VideoPlayer job={result} onReset={backToForm} />
          </div>
        )}

        {view === "failed" && (
          <div className="mx-auto max-w-2xl rounded-3xl border border-red-200 bg-white p-8 text-center shadow-sm">
            <AlertCircle className="mx-auto text-red-500" size={32} />
            <h2 className="mt-3 text-xl font-semibold">We couldn't finish your video</h2>
            <p className="mt-2 text-sm text-slate-600">{failure}</p>
            <button onClick={backToForm} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800">
              <RotateCcw size={16} /> Back to the form
            </button>
          </div>
        )}
      </main>
    </div>
  );
}