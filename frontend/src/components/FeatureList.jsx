import { useState } from "react";
import { Plus, X } from "lucide-react";

export default function FeatureList({ features, onChange, error, max = 6, maxLen = 60 }) {
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState("");

  const commit = (text) => {
    const value = text.trim();
    if (!value) return;
    if (value.length > maxLen) return setLocalError(`Keep each feature under ${maxLen} characters.`);
    if (features.some((f) => f.toLowerCase() === value.toLowerCase())) return setLocalError("That feature is already added.");
    if (features.length >= max) return setLocalError(`You can add up to ${max} features.`);
    setLocalError("");
    onChange([...features, value]);
    setDraft("");
  };

  const handleChange = (e) => {
    const value = e.target.value;
    if (value.includes(",")) {
      const parts = value.split(",");
      const last = parts.pop();
      let next = [...features];
      for (const part of parts) {
        const v = part.trim();
        if (v && v.length <= maxLen && next.length < max && !next.some((f) => f.toLowerCase() === v.toLowerCase())) next.push(v);
      }
      onChange(next);
      setDraft(last);
      return;
    }
    setDraft(value);
    setLocalError("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit(draft);
    } else if (e.key === "Backspace" && !draft && features.length) {
      onChange(features.slice(0, -1));
    }
  };

  const shownError = localError || error;

  return (
    <div>
      <div
        className={`flex flex-wrap items-center gap-2 rounded-xl border bg-white px-3 py-2.5 focus-within:ring-2 focus-within:ring-gold-400 ${
          shownError ? "border-red-400" : "border-slate-300"
        }`}
      >
        {features.map((feature) => (
          <span key={feature} className="inline-flex items-center gap-1 rounded-full bg-slate-900 py-1 pl-3 pr-1.5 text-sm text-white">
            {feature}
            <button
              type="button"
              onClick={() => onChange(features.filter((f) => f !== feature))}
              className="rounded-full p-0.5 hover:bg-white/20"
              aria-label={`Remove ${feature}`}
            >
              <X size={14} />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={() => commit(draft)}
          placeholder={features.length ? "Add another…" : "e.g. 3 BHK apartment"}
          className="min-w-[10rem] flex-1 bg-transparent py-1 text-sm outline-none placeholder:text-slate-400"
        />
        <button
          type="button"
          onClick={() => commit(draft)}
          className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200"
        >
          <Plus size={14} /> Add
        </button>
      </div>
      <div className="mt-1.5 flex justify-between text-xs">
        <span className={shownError ? "text-red-600" : "text-slate-500"}>
          {shownError || "Press Enter or comma to add. 2–6 features, used exactly as written."}
        </span>
        <span className="text-slate-400">{features.length}/{max}</span>
      </div>
    </div>
  );
}