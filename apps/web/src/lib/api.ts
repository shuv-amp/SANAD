const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export type HealthStatus = {
  status: string;
  provider: {
    name: string;
    implemented: boolean;
    tier?: string;
    official_api_configured?: boolean;
    fallback_enabled?: boolean;
    api_available?: boolean | null;
  };
};

export async function getHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error("Health check failed");
  return response.json();
}

export type DocumentSummary = {
  id: string;
  original_filename: string;
  file_type: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  subdomain: string | null;
  status: string;
  export_file_uri: string | null;
  counts: Record<string, number>;
  trust_summary: TrustSummary;
};

export type TrustSummary = {
  total_segments: number;
  approved_segments: number;
  memory_reused_segments: number;
  protected_values_total: number;
  protected_values_preserved: number;
  unresolved_review_flags: number;
};

export type Translation = {
  id: string;
  candidate_text: string;
  raw_candidate_text: string | null;
  approved_text: string | null;
  source_type: string;
  provider_name: string;
  memory_entry_id: string | null;
  risk_score: number;
  risk_reasons: Array<{ code: string; label: string; detail: string; severity?: "high" | "medium" | "low" }>;
  status: string;
  is_repaired: boolean;
  memory_provenance: {
    source_document_filename: string | null;
    scope_label: string;
    approved_at: string;
    times_used: number;
  } | null;
};

export type Segment = {
  id: string;
  sequence: number;
  segment_type: string;
  source_text: string;
  normalized_source: string;
  protected_entities: Array<{ kind: string; text: string }>;
  glossary_hits: Array<{ source_term: string; target_term: string; term_type: string }>;
  status: string;
  translation: Translation | null;
};

export type SourceLanguageDetection = {
  source_lang: string | null;
  confidence: "high" | "medium" | "low";
  explanation: string;
  segment_count: number;
};

export async function uploadDocument(payload: {
  file: File;
  sourceLang: string;
  targetLang: string;
  domain: string;
  subdomain?: string;
}) {
  const formData = new FormData();
  formData.append("file", payload.file);
  formData.append("source_lang", payload.sourceLang);
  formData.append("target_lang", payload.targetLang);
  formData.append("domain", payload.domain);
  if (payload.subdomain) {
    formData.append("subdomain", payload.subdomain);
  }
  return request<{ id: string; status: string; original_filename: string }>("/documents", {
    method: "POST",
    body: formData
  });
}

export async function detectSourceLanguage(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return request<SourceLanguageDetection>("/documents/detect-source", {
    method: "POST",
    body: formData
  });
}

export async function deleteDocument(id: string) {
  const response = await fetch(`${API_BASE}/documents/${id}`, { method: "DELETE" });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {}
    throw new Error(Array.isArray(detail) ? detail.map((i) => i.msg).join(", ") : detail);
  }
}

export async function processDocument(documentId: string) {
  return request<DocumentSummary>(`/documents/${documentId}/process-async`, { method: "POST" });
}

export async function getDocument(documentId: string) {
  return request<DocumentSummary>(`/documents/${documentId}`);
}

export async function getSegments(documentId: string) {
  return request<Segment[]>(`/documents/${documentId}/segments`);
}

export async function patchTranslation(segmentId: string, candidateText: string) {
  return request<Segment>(`/segments/${segmentId}/translation`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_text: candidateText })
  });
}

export async function approveSegment(segmentId: string, text: string) {
  return request<Segment>(`/segments/${segmentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, actor: "demo-reviewer" })
  });
}

export async function propagateApproval(segmentId: string, text: string) {
  return request<{ segment: Segment; propagated_count: number }>(`/segments/${segmentId}/approve-globally`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, actor: "demo-reviewer" })
  });
}

export async function approveUnflagged(documentId: string) {
  return request<{ approved: number }>(`/documents/${documentId}/approve-unflagged`, { method: "POST" });
}

export async function exportDocument(documentId: string, format: string) {
  return request<{ document_id: string; format: string; export_file_uri: string }>(`/documents/${documentId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format })
  });
}

export async function downloadFeedbackPack(documentId: string) {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/documents/${documentId}/feedback-pack`);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Network request failed.";
    if (message === "Failed to fetch") {
      throw new Error(`Cannot reach the SANAD API at ${API_BASE}. Start the backend or check VITE_API_BASE_URL.`);
    }
    throw new Error(message);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep status text.
    }
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(", ") : detail);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
  const filename = match?.[1] ?? `sanad-${documentId}-feedback-pack.zip`;
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 0);
}

export async function resetDemoState() {
  return request<{ status: string; fixtures_regenerated: boolean; storage_root: string }>("/debug/reset-demo", {
    method: "POST"
  });
}

export function exportDownloadUrl(documentId: string) {
  return `${API_BASE}/documents/${documentId}/exports/latest`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Network request failed.";
    if (message === "Failed to fetch") {
      throw new Error(`Cannot reach the SANAD API at ${API_BASE}. Start the backend or check VITE_API_BASE_URL.`);
    }
    throw new Error(message);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep status text.
    }
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(", ") : detail);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Platform endpoints
// ---------------------------------------------------------------------------

export type DocumentListItem = {
  id: string;
  original_filename: string;
  file_type: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  subdomain: string | null;
  status: string;
  created_at: string;
  segment_count: number;
  approved_count: number;
  memory_count: number;
};

export async function getDocumentHistory() {
  return request<DocumentListItem[]>("/documents");
}

export type AnalyticsSummary = {
  total_documents: number;
  total_segments: number;
  total_approved: number;
  total_memory_entries: number;
  memory_reuse_count: number;
  total_review_corrections: number;
  total_glossary_terms: number;
  provider_breakdown: Record<string, number>;
  avg_risk_score: number;
  total_exports: number;
};

export async function getAnalyticsSummary() {
  return request<AnalyticsSummary>("/analytics/summary");
}

export type GlossaryTerm = {
  id: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  subdomain: string | null;
  source_term: string;
  target_term: string;
  term_type: string;
};

export async function getGlossaryTerms() {
  return request<GlossaryTerm[]>("/glossary");
}

export async function createGlossaryTerm(payload: {
  source_lang: string;
  target_lang: string;
  domain: string;
  subdomain?: string;
  source_term: string;
  target_term: string;
  term_type: string;
}) {
  return request<GlossaryTerm>("/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteGlossaryTerm(termId: string) {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/glossary/${termId}`, { method: "DELETE" });
  } catch (error) {
    throw new Error("Network request failed.");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {}
    throw new Error(Array.isArray(detail) ? detail.map((i) => i.msg).join(", ") : detail);
  }
}

export type MemoryEntry = {
  id: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  subdomain: string | null;
  source_text: string;
  target_text: string;
  approved_by: string;
  approved_at: string;
  times_used: number;
  last_used_at: string | null;
  source_document_filename: string | null;
};

export async function getMemoryEntries() {
  return request<MemoryEntry[]>("/memory");
}

export async function deleteMemoryEntry(id: string) {
  const response = await fetch(`${API_BASE}/memory/${id}`, { method: "DELETE" });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {}
    throw new Error(Array.isArray(detail) ? detail.map((i) => i.msg).join(", ") : detail);
  }
}

export function getSseProgressUrl(documentId: string) {
  return `${API_BASE}/documents/${documentId}/progress`;
}
