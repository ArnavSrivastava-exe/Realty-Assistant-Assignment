import { useEffect, useRef, useState } from "react";
import { Building2, FileText, Loader2, MapPin, Megaphone, Mic, Phone, Sparkles, Star, Tag, UploadCloud, X } from "lucide-react";
import FeatureList from "./FeatureList.jsx";

const PROPERTY_TYPES = ["Apartment", "Villa", "Commercial", "House"];
const ALLOWED_EXT = ["jpg", "jpeg", "png", "webp"];
const ALLOWED_MIME = ["image/jpeg", "image/png", "image/webp"];
const MIN_IMAGES = 4;
const MAX_IMAGES = 8;
const MAX_IMAGE_MB = 10;

const VOICES = [
  { id: "en-female", language: "en", gender: "female", title: "English", sub: "Female narrator" },
  { id: "en-male", language: "en", gender: "male", title: "English", sub: "Male narrator" },
  { id: "hi-female", language: "hi", gender: "female", title: "हिन्दी · Hindi", sub: "Female narrator" },
  { id: "hi-male", language: "hi", gender: "male", title: "हिन्दी · Hindi", sub: "Male narrator" },
];

const EMPTY = { property_name: "", location: "", price: "", property_type: "Apartment", contact: "", cta: "" };

const SAMPLE = {
  values: {
    property_name: "Maple Court 3BHK",
    location: "Riverside Road, Pune",
    price: "₹1.25 Cr",
    property_type: "Apartment",
    contact: "+91 90000 00000",
    cta: "Book your site visit today",
  },
  features: ["3 BHK apartment", "Modular kitchen", "Covered parking", "24/7 security", "Clubhouse access", "Power backup"],
};

const inputClass = (hasError) =>
  `w-full rounded-xl border bg-white px-3.5 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-gold-400 ${
    hasError ? "border-red-400" : "border-slate-300"
  }`;

function Field({ label, icon: Icon, error, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-slate-700">
        {Icon && <Icon size={15} className="text-slate-400" />} {label}
      </span>
      {children}
      {(error || hint) && <span className={`mt-1.5 block text-xs ${error ? "text-red-600" : "text-slate-500"}`}>{error || hint}</span>}
    </label>
  );
}

function validate(values, features, images) {
  const e = {};
  if (!values.property_name.trim()) e.property_name = "Property name is required.";
  if (!values.location.trim()) e.location = "Location is required.";
  if (!values.price.trim()) e.price = "Price is required.";
  if (!values.cta.trim()) e.cta = "Call-to-action text is required.";
  if (features.length < 2) e.features = "Add at least 2 key features.";
  if (images.length < MIN_IMAGES) e.images = `Upload at least ${MIN_IMAGES} photos (you have ${images.length}).`;
  if (images.length > MAX_IMAGES) e.images = `Upload at most ${MAX_IMAGES} photos.`;
  return e;
}

let imageCounter = 0;

export default function PropertyForm({ onSubmit, submitting, serverErrors }) {
  const [values, setValues] = useState(EMPTY);
  const [features, setFeatures] = useState([]);
  const [images, setImages] = useState([]);
  const [voice, setVoice] = useState("en-female");
  const [errors, setErrors] = useState({});
  const [imageNotice, setImageNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef(null);
  const imagesRef = useRef(images);
  imagesRef.current = images;

  useEffect(() => {
    if (serverErrors && Object.keys(serverErrors).length) setErrors(serverErrors);
  }, [serverErrors]);

  useEffect(() => () => imagesRef.current.forEach((i) => URL.revokeObjectURL(i.url)), []);

  const setField = (name) => (e) => {
    setValues((v) => ({ ...v, [name]: e.target.value }));
    setErrors((prev) => ({ ...prev, [name]: undefined }));
  };

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList || []);
    const problems = [];
    const accepted = [];
    let room = MAX_IMAGES - images.length;
    const sameFile = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

    for (const file of incoming) {
      const ext = (file.name.split(".").pop() || "").toLowerCase();
      if (!ALLOWED_EXT.includes(ext) || (file.type && !ALLOWED_MIME.includes(file.type))) {
        problems.push(`${file.name}: only JPG, PNG or WebP images are allowed.`);
      } else if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
        problems.push(`${file.name}: larger than ${MAX_IMAGE_MB} MB.`);
      } else if (images.some((i) => sameFile(i.file, file)) || accepted.some((i) => sameFile(i.file, file))) {
        problems.push(`${file.name}: already added.`);
      } else if (room <= 0) {
        problems.push(`${file.name}: maximum of ${MAX_IMAGES} photos reached.`);
      } else {
        imageCounter += 1;
        accepted.push({ id: imageCounter, file, url: URL.createObjectURL(file) });
        room -= 1;
      }
    }
    setImageNotice(problems.join(" "));
    if (accepted.length) {
      setImages((prev) => [...prev, ...accepted]);
      setErrors((prev) => ({ ...prev, images: undefined }));
    }
  };

  const removeImage = (id) => {
    setImages((prev) => {
      const target = prev.find((i) => i.id === id);
      if (target) URL.revokeObjectURL(target.url);
      return prev.filter((i) => i.id !== id);
    });
    setImageNotice("");
  };

  const makeCover = (id) =>
    setImages((prev) => {
      const target = prev.find((i) => i.id === id);
      return target ? [target, ...prev.filter((i) => i.id !== id)] : prev;
    });

  const resetForm = () => {
    images.forEach((i) => URL.revokeObjectURL(i.url));
    setValues(EMPTY);
    setFeatures([]);
    setImages([]);
    setErrors({});
    setImageNotice("");
  };

  const loadSample = () => {
    setValues(SAMPLE.values);
    setFeatures(SAMPLE.features);
    setErrors({});
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const found = validate(values, features, images);
    setErrors(found);
    if (Object.keys(found).length) return;

    const selected = VOICES.find((v) => v.id === voice) || VOICES[0];
    const fd = new FormData();
    Object.entries(values).forEach(([key, value]) => fd.append(key, value.trim()));
    fd.append("features", JSON.stringify(features));
    fd.append("voice_language", selected.language);
    fd.append("voice_gender", selected.gender);
    images.forEach((i) => fd.append("images", i.file, i.file.name));
    await onSubmit(fd);
  };

  const voiceError = errors.voice_language || errors.voice_gender;

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">Property details</h2>
          <p className="text-sm text-slate-500">Only the facts you enter here are used in the video.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={loadSample} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
            Load sample listing
          </button>
          <button type="button" onClick={resetForm} className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100">
            Clear
          </button>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Property name" icon={Building2} error={errors.property_name}>
          <input value={values.property_name} onChange={setField("property_name")} maxLength={80} placeholder="Maple Court 3BHK" className={inputClass(errors.property_name)} />
        </Field>
        <Field label="Location" icon={MapPin} error={errors.location}>
          <input value={values.location} onChange={setField("location")} maxLength={100} placeholder="Riverside Road, Pune" className={inputClass(errors.location)} />
        </Field>
        <Field label="Price" icon={Tag} error={errors.price} hint="Shown exactly as typed, e.g. ₹1.25 Cr">
          <input value={values.price} onChange={setField("price")} maxLength={40} placeholder="₹1.25 Cr" className={inputClass(errors.price)} />
        </Field>
        <Field label="Property type" icon={Building2} error={errors.property_type}>
          <select value={values.property_type} onChange={setField("property_type")} className={inputClass(errors.property_type)}>
            {PROPERTY_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
      </div>

      <div>
        <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-slate-700">
          <FileText size={15} className="text-slate-400" /> Key features
        </span>
        <FeatureList
          features={features}
          onChange={(next) => {
            setFeatures(next);
            setErrors((prev) => ({ ...prev, features: undefined }));
          }}
          error={errors.features}
        />
      </div>

      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Contact information (optional)" icon={Phone} error={errors.contact}>
          <input value={values.contact} onChange={setField("contact")} maxLength={80} placeholder="+91 90000 00000" className={inputClass(errors.contact)} />
        </Field>
        <Field label="Call-to-action text" icon={Megaphone} error={errors.cta}>
          <input value={values.cta} onChange={setField("cta")} maxLength={80} placeholder="Book your site visit today" className={inputClass(errors.cta)} />
        </Field>
      </div>

      <div>
        <span className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-slate-700">
          <Mic size={15} className="text-slate-400" /> Narrator voice
        </span>
        <div role="radiogroup" aria-label="Narrator voice" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {VOICES.map((v) => {
            const selected = voice === v.id;
            return (
              <button
                key={v.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => {
                  setVoice(v.id);
                  setErrors((prev) => ({ ...prev, voice_language: undefined, voice_gender: undefined }));
                }}
                className={`rounded-xl border px-3 py-3 text-left transition ${
                  selected ? "border-gold-500 bg-gold-100 ring-2 ring-gold-400" : "border-slate-300 bg-white hover:border-slate-400"
                }`}
              >
                <span className="block text-sm font-semibold text-slate-900">{v.title}</span>
                <span className="block text-xs text-slate-500">{v.sub}</span>
              </button>
            );
          })}
        </div>
        <p className={`mt-1.5 text-xs ${voiceError ? "text-red-600" : "text-slate-500"}`}>
          {voiceError || "Hindi narration is spoken in Hindi; on-screen captions stay in English."}
        </p>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-700">Property photos</span>
          <span className={`text-xs ${images.length >= MIN_IMAGES ? "text-emerald-600" : "text-slate-500"}`}>
            {images.length}/{MAX_IMAGES} added · minimum {MIN_IMAGES}
          </span>
        </div>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            addFiles(e.dataTransfer.files);
          }}
          onClick={() => fileInput.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-8 text-center transition ${
            dragging ? "border-gold-500 bg-gold-100" : errors.images ? "border-red-400 bg-red-50" : "border-slate-300 bg-slate-50 hover:border-slate-400"
          }`}
        >
          <UploadCloud className="mb-2 text-slate-400" size={30} />
          <p className="text-sm font-medium text-slate-700">Drag & drop photos here, or click to browse</p>
          <p className="mt-1 text-xs text-slate-500">JPG, PNG or WebP · up to {MAX_IMAGE_MB} MB each · first photo is the cover</p>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {(errors.images || imageNotice) && <p className="mt-2 text-xs text-red-600">{[errors.images, imageNotice].filter(Boolean).join(" ")}</p>}

        {images.length > 0 && (
          <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {images.map((img, index) => (
              <li key={img.id} className="group relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
                <img src={img.url} alt={img.file.name} className="aspect-[4/3] w-full object-cover" />
                {index === 0 ? (
                  <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-gold-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                    <Star size={10} /> Cover
                  </span>
                ) : (
                  <button type="button" onClick={() => makeCover(img.id)} className="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium text-white opacity-0 transition group-hover:opacity-100">
                    Set as cover
                  </button>
                )}
                <button type="button" onClick={() => removeImage(img.id)} aria-label={`Remove ${img.file.name}`} className="absolute right-2 top-2 rounded-full bg-black/60 p-1 text-white hover:bg-red-600">
                  <X size={14} />
                </button>
                <p className="truncate px-2 py-1 text-[11px] text-slate-600">{img.file.name}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-5 py-3.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} className="text-gold-400" />}
        {submitting ? "Uploading photos…" : "Generate video"}
      </button>
    </form>
  );
}