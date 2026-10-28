import axios from "axios";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const client = axios.create({ baseURL: API_BASE_URL, timeout: 120000 });

/** Turns any axios/JS error into { message, fieldErrors, status }. */
export function parseApiError(error) {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return {
        message: `Cannot reach the backend at ${API_BASE_URL}. Make sure it is running.`,
        fieldErrors: {},
        status: 0,
      };
    }
    const { status, data } = error.response;
    const detail = data && !(data instanceof Blob) ? data.detail : undefined;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      return { message: detail.message || "Request failed.", fieldErrors: detail.errors || {}, status };
    }
    if (typeof detail === "string") return { message: detail, fieldErrors: {}, status };
    if (Array.isArray(detail)) return { message: "Some fields are invalid.", fieldErrors: {}, status };
    return { message: `Request failed (HTTP ${status}).`, fieldErrors: {}, status };
  }
  return { message: error?.message || "Unexpected error.", fieldErrors: {}, status: -1 };
}

export async function checkHealth() {
  const { data } = await client.get("/api/health", { timeout: 8000 });
  return data;
}

export async function createJob(formData) {
  const { data } = await client.post("/api/generate-video", formData);
  return data;
}

export async function getJob(jobId) {
  const { data } = await client.get(`/api/jobs/${jobId}`, { timeout: 15000 });
  return data;
}

export function resolveUrl(path) {
  if (!path) return "";
  return /^https?:\/\//i.test(path) ? path : `${API_BASE_URL}${path}`;
}

/** Downloads through axios so failures can be reported (an <a download> link cannot report errors). */
export async function downloadVideo(job) {
  const response = await client.get(job.download_url, { responseType: "blob", timeout: 300000 });
  const blobUrl = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = job.filename || "property_video.mp4";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
}