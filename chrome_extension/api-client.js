"use strict";

const API_BASE_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 300_000;

export class ApiError extends Error {
  constructor(message, { status = 0 } = {}) { super(message); this.name = "ApiError"; this.status = status; }
}

function safeDetail(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (typeof detail?.message === "string") return detail.message;
  if (status === 409) return "Upload a PDF resume in career chat first.";
  if (status === 422) return "Check the job description and try again.";
  return "The backend could not complete the request.";
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) }, signal: controller.signal });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(safeDetail(payload, response.status), { status: response.status });
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") throw new ApiError("The analysis timed out. The run may still be processing; open this job in career chat.");
    if (error instanceof ApiError) throw error;
    throw new ApiError("Cannot reach eregion at http://localhost:8000.");
  } finally { clearTimeout(timeout); }
}

export const health = () => request("/health", { timeoutMs: 8_000 });
export const saveWorkspace = (workspace) => request("/api/workspaces", {
  method: "POST",
  body: JSON.stringify({ ...workspace, reopen_existing: true }),
});
export const analyzeApplication = (applicationId, expectedVersion) => request(
  `/api/applications/${encodeURIComponent(applicationId)}/analyze-with-resume`,
  { method: "POST", body: JSON.stringify({ expected_version: expectedVersion, resume_id: null }) },
);
