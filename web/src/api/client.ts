const API = "/api";
const DEFAULT_TIMEOUT_MS = 35_000;

const API_DOWN_HINT =
  "API не отвечает. Запустите start_web.bat (или: legal-monitor serve на порту 8000). Не запускайте только npm run dev.";

function formatApiError(status: number, statusText: string, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const msg = detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
    if (msg) return msg;
  }
  if (status === 500 || status === 502 || status === 504) {
    return API_DOWN_HINT;
  }
  return statusText || API_DOWN_HINT;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(formatApiError(res.status, res.statusText, err.detail));
    }
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Превышено время ожидания ответа API. Возможно, база занята ingest/classify.");
    }
    if (err instanceof TypeError) {
      throw new Error(API_DOWN_HINT);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export interface Dashboard {
  period: string;
  documents_total: number;
  shortlist_documents: number;
  shortlist_matches: number;
  memos_total: number;
  enabled_profiles: string[];
  exports_count: number;
  job_running: boolean;
  llm_provider: string;
}

export interface FileItem {
  id: string;
  name: string;
  path: string;
  category: string;
  size: number;
  modified_at: string;
  extension: string;
}

export interface DocumentItem {
  id: number;
  title: string;
  source: string;
  external_id: string;
  register_date: string | null;
  stage: string | null;
  profile_name: string;
  relevance_score: number;
  analysis_preview: string;
  url: string | null;
}

export interface Job {
  id: string;
  type: string;
  status: string;
  created_at: string;
  events: { ts: string; level: string; message: string }[];
  result?: Record<string, unknown>;
  error?: string;
}

export interface Profile {
  id: string;
  name: string;
  enabled: boolean;
  description: string;
  keywords_any: string[];
}

export interface ReviewSession {
  stamp: string;
  period: string;
  rows_count: number;
  modified_at: number;
}

export interface ReviewRow {
  row_id: string;
  document_id: number;
  profile_id: string;
  register_date: string | null;
  source: string;
  title: string;
  stage: string;
  profile_name: string;
  relevance_score: number;
  brief_summary?: string;
  analysis_preview: string;
  url?: string;
}

export interface ReviewData {
  stamp: string;
  period: string;
  date_from: string;
  date_to: string;
  rows: ReviewRow[];
}

export const api = {
  health: () => request<{ status: string; job_running: boolean; db_ok?: boolean }>("/health", undefined, 8_000),
  dashboard: () => request<Dashboard>("/dashboard"),
  documents: (params?: { limit?: number; offset?: number; source?: string }) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    if (params?.source) q.set("source", params.source);
    return request<{ items: DocumentItem[]; total: number }>(`/documents?${q}`);
  },
  document: (id: number) => request<Record<string, unknown>>(`/documents/${id}`),
  files: () => request<{ items: FileItem[] }>("/files"),
  fileRawUrl: (file: FileItem) => {
    const root =
      file.category === "download" || file.category === "document_attachment"
        ? "downloads"
        : "output";
    const q = new URLSearchParams({ root, path: file.path });
    return `${API}/files/raw?${q}`;
  },
  profiles: () => request<{ items: Profile[] }>("/profiles"),
  toggleProfile: (id: string, enabled: boolean) =>
    request<{ ok: boolean }>(`/profiles/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),
  jobs: () => request<{ items: Job[]; running: boolean }>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  startJob: (type: string, withAnalysis = false) =>
    request<Job>(`/jobs/${type}`, {
      method: "POST",
      body: JSON.stringify({ with_analysis: withAnalysis }),
    }),
  ingestHistory: () => request<{ items: Record<string, unknown>[] }>("/ingest/history"),
  reviewSessions: () => request<{ items: ReviewSession[] }>("/review/sessions"),
  reviewRows: (stamp: string) => request<ReviewData>(`/review/${encodeURIComponent(stamp)}/rows`),
  reviewAnalyze: (stamp: string, selections: { document_id: number; profile_id: string }[]) =>
    request<Job>("/review/analyze", {
      method: "POST",
      body: JSON.stringify({ stamp, selections }),
    }),
};

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ru-RU");
  } catch {
    return iso;
  }
}
