import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Download, FileText, Languages, RotateCw, ShieldCheck, Upload, Moon, Sun, Layers, Clock, Brain, CheckCircle2 } from "lucide-react";

import {
  approveSegment,
  approveUnflagged,
  detectSourceLanguage,
  downloadFeedbackPack,
  exportDocument,
  exportDownloadUrl,
  getDocument,
  getHealth,
  getSegments,
  patchTranslation,
  processDocument,
  resetDemoState,
  uploadDocument,
  type Segment,
  type SourceLanguageDetection,
  type TrustSummary
} from "./lib/api";
import {
  coverageStatusLabel,
  evidenceSourceLabel,
  LANGUAGE_PATH_MATRIX,
  languageCodeLabel,
  MAIN_DEMO_PATH,
  type CoverageStatus,
  type LanguagePathReadiness
} from "./lib/languageCoverage";
import { useSanadStore } from "./lib/store";
import { Badge, Button, Input, LiveStatusIndicator, MiniProgressBar, ProcessingPipeline, SecondaryButton, Select, Textarea, ExportDropdown } from "./components/ui";
import { AnalyticsDashboard, DocumentHistorySidebar, GlossaryPanel, MemoryBrowserPanel } from "./components/features";

export default function App() {
  const queryClient = useQueryClient();
  const { documentId, setDocumentId } = useSanadStore();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ title: string; detail: string } | null>(null);
  const [sessionResetKey, setSessionResetKey] = useState(0);
  const [isDarkMode, setIsDarkMode] = useState(() => localStorage.getItem("sanad_theme") === "dark");

  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem("sanad_theme", "dark");
    } else {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("sanad_theme", "light");
    }
  }, [isDarkMode]);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: 1,
  });

  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const providerTier = (() => {
    if (healthQuery.isError) return "offline";
    if (!isOnline) return "fixture_fallback";
    if (!healthQuery.data) return "none";
    const p = healthQuery.data.provider;
    // If a translation has been done, show the actual tier
    if (p.tier && p.tier !== "none") return p.tier;
    // If official API is configured but no translation yet, show ready state
    if (p.official_api_configured) return "tmt_official";
    if (p.name === "fixture") return "fixture";
    return p.name ?? "none";
  })();

  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId!),
    enabled: Boolean(documentId)
  });

  const segmentsQuery = useQuery({
    queryKey: ["segments", documentId],
    queryFn: () => getSegments(documentId!),
    enabled: Boolean(documentId)
  });

  const invalidateDocument = async (targetDocumentId?: string | null) => {
    const id = targetDocumentId ?? documentId;
    if (!id) return;
    await queryClient.invalidateQueries({ queryKey: ["document", id] });
    await queryClient.invalidateQueries({ queryKey: ["segments", id] });
    await queryClient.invalidateQueries({ queryKey: ["documentHistory"] });
    await queryClient.invalidateQueries({ queryKey: ["analyticsSummary"] });
  };

  const processMutation = useMutation({
    mutationFn: processDocument,
    onMutate: () => setError(null),
    onSuccess: async (document) => {
      queryClient.setQueryData(["document", document.id], document);
      await invalidateDocument(document.id);
    },
    onError: (err) => setError((err as Error).message)
  });

  const approveUnflaggedMutation = useMutation({
    mutationFn: approveUnflagged,
    onMutate: () => setError(null),
    onSuccess: () => invalidateDocument(),
    onError: (err) => setError((err as Error).message)
  });

  const exportMutation = useMutation({
    mutationFn: ({ documentId, format }: { documentId: string; format: string }) => exportDocument(documentId, format),
    onMutate: () => setError(null),
    onSuccess: async (_, { documentId }) => {
      await invalidateDocument();
      if (documentId) window.location.href = exportDownloadUrl(documentId);
    },
    onError: (err) => setError((err as Error).message)
  });

  const feedbackPackMutation = useMutation({
    mutationFn: downloadFeedbackPack,
    onMutate: () => setError(null),
    onError: (err) => setError((err as Error).message)
  });

  const resetDemoMutation = useMutation({
    mutationFn: resetDemoState,
    onMutate: () => {
      setError(null);
      setNotice(null);
    },
    onSuccess: async () => {
      window.location.reload();
    },
    onError: (err) => setError((err as Error).message)
  });

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(null), 4800);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  const supportedFormats = useMemo(() => {
    if (!documentQuery.data) return [];
    const type = documentQuery.data.file_type;
    if (type === "csv" || type === "tsv") return [type, "docx", "pdf", "txt"];
    if (type === "pdf") return ["pdf", "docx", "txt"];
    return ["docx", "pdf", "txt"];
  }, [documentQuery.data]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (!(event.altKey && event.shiftKey && event.code === "KeyR")) return;

      event.preventDefault();
      // Defer to avoid keyup events auto-dismissing the confirm dialog
      window.setTimeout(() => {
        const confirmed = window.confirm(
          "Reset local SANAD demo state? This clears the local database, storage, and current review session, then regenerates demo fixtures."
        );
        if (!confirmed) return;
        resetDemoMutation.mutate();
      }, 10);
    };

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [resetDemoMutation]);

  return (
    <main className="min-h-screen transition-colors">
      {/* Gradient accent bar */}
      <div className="sanad-header-accent" />

      <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        <header className="sanad-animate-in flex flex-col gap-4 border-b border-[var(--border-medium)]/60 pb-5 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <div className="flex items-center gap-3">
              <p className="text-xs font-bold uppercase tracking-[0.22em] text-[#2d8a5e]">SPAN</p>
              <LiveStatusIndicator tier={providerTier} />
            </div>
            <h1 className="mt-1.5 text-[2.35rem] font-extrabold leading-none tracking-tight">
              SANAD
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
              Trust-first document translation for public-service workflows, with human review, scoped memory, and export in one place.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 md:justify-end">
            <button
              onClick={() => setIsDarkMode(!isDarkMode)}
              className="p-1.5 rounded-full border border-[var(--border-medium)] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-colors"
              title={isDarkMode ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {isDarkMode ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <Badge tone="status">Public-service workflow</Badge>
            <Badge tone="memory">Scoped memory</Badge>
          </div>
        </header>

        <div className="flex flex-col lg:flex-row gap-6">
          <DocumentHistorySidebar currentDocumentId={documentId} onSelect={(id) => {
            setError(null);
            setNotice(null);
            setDocumentId(id);
          }} />
          
          <div className={`flex-1 min-w-0 flex flex-col gap-6 transition-all duration-300 ${!(segmentsQuery.data && segmentsQuery.data.length > 0) ? 'max-w-4xl mx-auto w-full' : ''}`}>
            <AnalyticsDashboard />

            <UploadPanel
              key={sessionResetKey}
              processing={processMutation.isPending}
              onUploaded={async (id, isDuplicate) => {
                setError(null);
                setNotice(null);
                setDocumentId(id);
                if (isDuplicate) {
                  setNotice({ title: "Duplicate Document Detected", detail: "We loaded the existing translation session instead of reprocessing." });
                  // No need to process, just invalidate queries to fetch
                  await invalidateDocument(id);
                } else {
                  await processMutation.mutateAsync(id);
                }
              }}
              onError={setError}
            />

            <ProcessingPipeline active={processMutation.isPending} documentId={documentId} />

        {notice ? (
          <div className="pointer-events-none fixed top-4 right-4 z-50 max-w-[340px] animate-[sanad-slide-down_0.3s_ease-out] rounded-lg border border-emerald-200 dark:border-emerald-500/30 bg-white dark:bg-emerald-500/10 px-4 py-3 shadow-lg dark:shadow-[0_4px_12px_rgba(0,0,0,0.6)] backdrop-blur-sm">
            <div className="flex items-center gap-2.5">
              <div className="shrink-0 rounded-full bg-emerald-100 dark:bg-emerald-500/20 p-1 text-emerald-600 dark:text-emerald-400">
                <Check size={14} />
              </div>
              <div className="min-w-0">
                <p className="text-[13px] font-semibold leading-5 text-[var(--text-primary)]">{notice.title}</p>
                <p className="text-[12px] leading-4 text-[var(--text-secondary)]">{notice.detail}</p>
              </div>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="flex items-start gap-3 rounded-md border border-red-300 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 px-4 py-3 text-sm font-medium leading-6 text-red-900 dark:text-red-400 shadow-sm">
            <AlertTriangle className="mt-0.5 shrink-0" size={17} />
            <span>{error}</span>
          </div>
        ) : null}

        {documentQuery.data ? (
          <div className="flex flex-col gap-5">
            <section className="sanad-animate-in sanad-card-hover rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] p-6 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="status">{statusLabel(documentQuery.data.status)}</Badge>
                    <span className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Current document</span>
                  </div>
                  <h2 className="mt-3 truncate text-[1.15rem] font-bold text-[var(--text-primary)]">
                    {documentQuery.data.original_filename}
                  </h2>
                  <p className="mt-1 text-sm font-medium leading-6 text-[var(--text-secondary)]">
                    {languageLabel(documentQuery.data.source_lang)} → {languageLabel(documentQuery.data.target_lang)}
                    <span className="mx-2 text-[var(--border-medium)]">•</span>
                    {scopeLabel(documentQuery.data.domain, documentQuery.data.subdomain)}
                  </p>

                  <TrustSummaryPanel summary={documentQuery.data.trust_summary} />
                </div>
                <div className="flex w-full flex-col gap-3 md:w-auto md:shrink-0">
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap md:justify-end">
                <SecondaryButton
                  className="w-full sm:w-auto"
                  onClick={() => documentId && processMutation.mutate(documentId)}
                  disabled={!documentId || processMutation.isPending}
                  title="Re-run document checks"
                >
                  <RotateCw size={16} />
                  Re-run checks
                </SecondaryButton>

                <SecondaryButton
                  className="w-full sm:w-auto"
                  onClick={() => documentId && approveUnflaggedMutation.mutate(documentId)}
                  disabled={!documentId || approveUnflaggedMutation.isPending}
                >
                  <Check size={16} />
                  Approve clear segments
                </SecondaryButton>

                <SecondaryButton
                  className="w-full sm:w-auto"
                  onClick={() => documentId && feedbackPackMutation.mutate(documentId)}
                  disabled={!documentId || feedbackPackMutation.isPending || !allSegmentsApproved(documentQuery.data.counts)}
                  title={
                    allSegmentsApproved(documentQuery.data.counts)
                      ? "Download privacy-reduced contribution pack"
                      : "Approve all segments before downloading the contribution pack"
                  }
                >
                  <Download size={16} />
                  {feedbackPackMutation.isPending ? "Preparing contribution pack" : "Contribution Pack"}
                </SecondaryButton>
                
                <ExportDropdown 
                  className="w-full sm:w-auto"
                  formats={supportedFormats}
                  onExport={(format) => documentId && exportMutation.mutate({ documentId, format })}
                  disabled={!documentId || exportMutation.isPending || !allSegmentsApproved(documentQuery.data.counts)}
                  title={
                    allSegmentsApproved(documentQuery.data.counts)
                      ? "Export document"
                      : "Approve all segments before exporting"
                  }
                />
              </div>
              <p className="text-sm font-medium leading-6 text-[var(--text-tertiary)] md:text-right">
                {approvalHint(documentQuery.data.counts)}
              </p>
              <p className="text-xs font-medium leading-5 text-[var(--text-tertiary)] md:max-w-[36rem] md:text-right">
                {feedbackPackHint(documentQuery.data.counts)}
              </p>
              </div>
              </div>
            </section>
          <div className="flex flex-col gap-3">
            <GlossaryPanel />
            <MemoryBrowserPanel />
          </div>
        </div>
        ) : null}

        <ReviewList
          segments={segmentsQuery.data ?? []}
          loading={segmentsQuery.isFetching}
          onError={setError}
          afterChange={invalidateDocument}
        />
        </div>
        </div>
      </div>
    </main>
  );
}

function UploadPanel({
  processing,
  onUploaded,
  onError
}: {
  processing: boolean;
  onUploaded: (id: string, isDuplicate: boolean) => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const fileInputId = useId();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceLang, setSourceLang] = useState(MAIN_DEMO_PATH.source_lang);
  const [targetLang, setTargetLang] = useState(MAIN_DEMO_PATH.target_lang);
  const [domain, setDomain] = useState(() => localStorage.getItem("sanad_scope_domain") || "public_service");
  const [subdomain, setSubdomain] = useState(() => localStorage.getItem("sanad_scope_subdomain") || "residence");
  const [showScopeEditor, setShowScopeEditor] = useState(false);
  const [showCoverage, setShowCoverage] = useState(false);
  const [sourceDetection, setSourceDetection] = useState<SourceLanguageDetection | null>(null);
  const [detectingSource, setDetectingSource] = useState(false);
  const detectRequestRef = useRef(0);

  useEffect(() => {
    localStorage.setItem("sanad_scope_domain", domain);
  }, [domain]);

  useEffect(() => {
    localStorage.setItem("sanad_scope_subdomain", subdomain);
  }, [subdomain]);

  const selectedPath =
    LANGUAGE_PATH_MATRIX.find((path) => path.source_lang === sourceLang && path.target_lang === targetLang) ?? null;

  const uploadMutation = useMutation({
    mutationFn: uploadDocument,
    onMutate: () => onError(null),
    onSuccess: (result: any) => onUploaded(result.id, result.is_duplicate || false),
    onError: (err) => onError((err as Error).message)
  });

  return (
    <section className="sanad-animate-in rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] p-5 shadow-sm">
      <div className="mb-5 border-b border-[var(--border-light)]/70 pb-4">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#2d8a5e]">Document intake</p>
          <h2 className="mt-1 text-[1.05rem] font-bold text-[var(--text-primary)]">Start a translation review</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
            Upload a source document, confirm the language pair, and SANAD prepares the review queue for approval and export.
          </p>
        </div>
      </div>
      <form
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-[minmax(0,1.6fr)_minmax(180px,0.8fr)_minmax(180px,0.8fr)]"
        onSubmit={(event) => {
          event.preventDefault();
          onError(null);
          const selectedFile = fileInputRef.current?.files?.[0] ?? file;
          if (!selectedFile) {
            onError("Choose a supported document first.");
            return;
          }
          if (!selectedPath) {
            onError("Choose a supported SANAD language direction.");
            return;
          }
          uploadMutation.mutate({
            file: selectedFile,
            sourceLang,
            targetLang,
            domain,
            subdomain
          });
        }}
      >
        <div className="flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-[var(--text-secondary)]">
          <label htmlFor={fileInputId}>Source document</label>
          <input
            id={fileInputId}
            ref={fileInputRef}
            className="sr-only"
            type="file"
            accept=".pdf,.docx,.doc,.odt,.rtf,.txt,.md,.html,.htm,.csv,.tsv"
            onChange={async (event) => {
              const nextFile = event.target.files?.[0] ?? null;
              setFile(nextFile);
              setSourceDetection(null);
              if (!nextFile) return;

              const requestId = detectRequestRef.current + 1;
              detectRequestRef.current = requestId;
              setDetectingSource(true);
              try {
                const detection = await detectSourceLanguage(nextFile);
                if (detectRequestRef.current !== requestId) return;
                setSourceDetection(detection);
                if (detection.source_lang && detection.confidence === "high") {
                  setSourceLang(detection.source_lang as "en" | "ne" | "tmg");
                  if (detection.source_lang === targetLang) {
                    const fallbackTarget = ["en", "ne", "tmg"].find((code) => code !== detection.source_lang) as "en" | "ne" | "tmg";
                    setTargetLang(fallbackTarget);
                  }
                }
              } catch (error) {
                if (detectRequestRef.current !== requestId) return;
                setSourceDetection({
                  source_lang: null,
                  confidence: "low",
                  explanation: error instanceof Error ? error.message : "Could not detect the document source language.",
                  segment_count: 0,
                });
              } finally {
                if (detectRequestRef.current === requestId) setDetectingSource(false);
              }
            }}
          />
          <label
            htmlFor={fileInputId}
            className="flex h-12 cursor-pointer items-center gap-3 rounded-md border border-[var(--border-medium)] bg-[var(--surface-card)] px-3.5 text-sm font-medium text-[var(--text-secondary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.04)] transition hover:border-[var(--text-secondary)] hover:bg-[var(--surface-hover)] focus-within:border-[#2d8a5e] focus-within:ring-2 focus-within:ring-[#2d8a5e]/20"
          >
            <FileText size={17} className="shrink-0 text-[var(--text-secondary)]" />
            <span className="min-w-0 truncate">{file ? file.name : "Choose document"}</span>
          </label>
          <span className="text-xs font-medium leading-5 text-[var(--text-tertiary)]">Supported: PDF, DOCX, CSV, TSV, DOC, ODT, RTF, TXT, MD, and HTML. All documents can be flexibly exported.</span>
        </div>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--text-secondary)]">
          Source
          <Select
            value={sourceLang}
            onChange={(event) => {
              const nextSource = event.target.value as "en" | "ne" | "tmg";
              setSourceLang(nextSource);
              if (nextSource === targetLang) {
                const fallbackTarget = ["en", "ne", "tmg"].find((code) => code !== nextSource) as "en" | "ne" | "tmg";
                setTargetLang(fallbackTarget);
              }
            }}
          >
            <option value="en">English</option>
            <option value="ne">Nepali</option>
            <option value="tmg">Tamang</option>
          </Select>
          <span className="text-xs font-medium leading-5 text-[var(--text-tertiary)]">
            {detectingSource
              ? "Reading the document to suggest the source language..."
              : sourceDetection
                ? sourceDetectionMessage(sourceDetection)
                : "SANAD can suggest the source language after file selection."}
          </span>
        </label>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--text-secondary)]">
          Target
          <Select value={targetLang} onChange={(event) => setTargetLang(event.target.value as "en" | "ne" | "tmg")}>
            {["en", "ne", "tmg"]
              .filter((code) => code !== sourceLang)
              .map((code) => (
                <option key={code} value={code}>
                  {languageCodeLabel(code)}
                </option>
              ))}
          </Select>
          <span className="text-xs font-medium leading-5 text-[var(--text-tertiary)]">Change before upload if needed.</span>
        </label>
        {selectedPath ? (
          <div className="md:col-span-2 xl:col-span-3">
            <div className="grid gap-3 rounded-md border border-[var(--border-light)] bg-[var(--surface-hover)]/70 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold text-[var(--text-primary)]">
                    {languageCodeLabel(selectedPath.source_lang)} → {languageCodeLabel(selectedPath.target_lang)}
                  </p>
                  <Badge tone={coverageTone(selectedPath.status)}>{coverageStatusLabel(selectedPath.status)}</Badge>
                </div>
                <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{selectedPath.judge_copy}</p>
              </div>
              <p className="flex items-center gap-1.5 text-xs font-medium leading-5 text-[var(--text-tertiary)] lg:justify-end">
                <Languages size={14} className="text-[var(--text-tertiary)]" />
                {evidenceSourceLabel(selectedPath.evidence_source)}
              </p>
            </div>
          </div>
        ) : null}
        <div className="grid gap-3 border-t border-[var(--border-light)]/80 pt-4 md:col-span-2 xl:col-span-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <p className="text-sm font-medium leading-6 text-[var(--text-tertiary)]">All documents can be exported to multiple formats including DOCX and TXT.</p>
          <Button className="h-12 px-5 lg:min-w-[220px]" type="submit" disabled={uploadMutation.isPending || processing}>
            <Upload size={16} />
            {processing ? "Preparing" : uploadMutation.isPending ? "Uploading" : "Start review"}
          </Button>
        </div>
      </form>
      <div className="mt-5 grid gap-4 border-t border-[var(--border-light)]/80 pt-5 xl:grid-cols-2">
        <div className="rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] p-5 shadow-sm transition-shadow hover:shadow-md">
          <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Scope</h3>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <span className="rounded-md border border-[var(--border-light)] bg-[var(--surface-hover)] px-3 py-1.5 text-[13px] font-semibold text-[var(--text-primary)] shadow-sm">
                  {humanizeLabel(domain)}
                </span>
                <span className="text-[13px] font-medium text-[var(--text-tertiary)]">/</span>
                <span className="rounded-md border border-[var(--border-light)] bg-[var(--surface-hover)] px-3 py-1.5 text-[13px] font-semibold text-[var(--text-primary)] shadow-sm">
                  {humanizeLabel(subdomain)}
                </span>
                <SecondaryButton className="shrink-0 ml-auto" type="button" onClick={() => setShowScopeEditor((value) => !value)}>
                  {showScopeEditor ? "Done" : "Change scope"}
                </SecondaryButton>
              </div>
          <p className="mt-3.5 text-[13px] font-medium leading-relaxed text-[var(--text-tertiary)]">
            Scope keeps glossary matches and memory reuse aligned to this document family.
          </p>
          {showScopeEditor ? (
            <div className="mt-5 border-t border-stone-100 pt-5">
              <div className="grid gap-5 md:grid-cols-2">
                <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--text-secondary)]">
                  Domain
                  <Input value={domain} onChange={(event) => setDomain(event.target.value)} />
                </label>
                <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-[var(--text-secondary)]">
                  Subdomain
                  <Input value={subdomain} onChange={(event) => setSubdomain(event.target.value)} />
                </label>
              </div>
              <p className="mt-3 text-[12px] font-medium text-[#2d8a5e]">Changes apply automatically to the next document upload.</p>
            </div>
          ) : null}
        </div>
        
        <div className="rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] p-5 shadow-sm transition-shadow hover:shadow-md">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Language coverage</h3>
              <p className="mt-2.5 text-[13px] font-medium leading-relaxed text-[var(--text-tertiary)] pr-4">
                Open the route list to inspect the currently validated language pairs.
              </p>
            </div>
            <SecondaryButton className="shrink-0" type="button" onClick={() => setShowCoverage((value) => !value)}>
              {showCoverage ? "Hide coverage" : "View coverage"}
            </SecondaryButton>
          </div>
          {showCoverage ? (
            <div className="mt-4 rounded-md border border-[var(--border-light)] bg-[var(--surface-card)]">
              {LANGUAGE_PATH_MATRIX.map((path, index) => (
                <LanguageCoverageRow key={`${path.source_lang}-${path.target_lang}`} path={path} isFirst={index === 0} />
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function ReviewList({
  segments,
  loading,
  onError,
  afterChange
}: {
  segments: Segment[];
  loading: boolean;
  onError: (message: string | null) => void;
  afterChange: () => Promise<void>;
}) {
  const [filter, setFilter] = useState<"all" | "flagged" | "needs_approval" | "memory" | "approved">("all");
  const [search, setSearch] = useState("");

  const orderedSegments = useMemo(() => [...segments].sort((a, b) => a.sequence - b.sequence), [segments]);
  const approvedCount = orderedSegments.filter((segment) => segment.status === "approved").length;
  const flaggedCount = orderedSegments.filter((segment) => (segment.translation?.risk_reasons ?? []).length > 0).length;
  const memoryCount = orderedSegments.filter((segment) => segment.translation?.source_type === "memory").length;
  const awaitingApprovalCount = orderedSegments.length - approvedCount;

  const filteredSegments = useMemo(() => {
    return orderedSegments.filter((segment) => {
      // Search filter
      if (search) {
        const q = search.toLowerCase();
        const src = segment.source_text.toLowerCase();
        const tgt = (segment.translation?.approved_text ?? segment.translation?.candidate_text ?? "").toLowerCase();
        if (!src.includes(q) && !tgt.includes(q)) return false;
      }
      
      // Category filter
      if (filter === "all") return true;
      if (filter === "flagged") return (segment.translation?.risk_reasons ?? []).length > 0;
      if (filter === "needs_approval") return segment.status !== "approved";
      if (filter === "memory") return segment.translation?.source_type === "memory";
      if (filter === "approved") return segment.status === "approved";
      return true;
    });
  }, [orderedSegments, filter, search]);

  if (loading && !segments.length) {
    return <div className="rounded-md border border-[var(--border-light)] bg-[var(--surface-card)] p-5 text-sm font-medium text-[var(--text-secondary)] shadow-sm">Loading segments...</div>;
  }
  if (!segments.length) {
    return (
      <div className="sanad-animate-in flex min-h-[220px] items-center justify-center rounded-xl border border-dashed border-[var(--border-medium)] bg-[var(--surface-card)] p-8 text-center text-sm font-medium text-[var(--text-tertiary)]">
        <div>
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[#eef7f2] dark:bg-[#2d8a5e]/15">
            <FileText className="text-[#2d8a5e] dark:text-[#45b784]" size={26} />
          </div>
          <p className="text-[var(--text-secondary)] font-semibold">Upload a document to prepare the review queue</p>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">Supported: DOCX, CSV, TSV, DOC, ODT, RTF, TXT, MD, HTML</p>
        </div>
      </div>
    );
  }
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 pt-1">
        <div>
          <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">Review queue</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            <FilterChip
              active={filter === "all"}
              onClick={() => setFilter("all")}
              icon={<Layers size={14} />}
              label="All"
              count={orderedSegments.length}
            />
            <FilterChip
              active={filter === "needs_approval"}
              onClick={() => setFilter("needs_approval")}
              icon={<Clock size={14} />}
              label="Needs Approval"
              count={awaitingApprovalCount}
              activeColor="text-blue-600 dark:text-blue-400"
              activeBg="bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800"
            />
            <FilterChip
              active={filter === "flagged"}
              onClick={() => setFilter("flagged")}
              icon={<AlertTriangle size={14} />}
              label="Flagged"
              count={flaggedCount}
              activeColor="text-amber-600 dark:text-amber-500"
              activeBg="bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800/50"
            />
            <FilterChip
              active={filter === "memory"}
              onClick={() => setFilter("memory")}
              icon={<Brain size={14} />}
              label="Memory"
              count={memoryCount}
              activeColor="text-purple-600 dark:text-purple-400"
              activeBg="bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800/50"
            />
            <FilterChip
              active={filter === "approved"}
              onClick={() => setFilter("approved")}
              icon={<CheckCircle2 size={14} />}
              label="Approved"
              count={approvedCount}
              activeColor="text-green-600 dark:text-green-500"
              activeBg="bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800/50"
            />
          </div>
        </div>
        <div className="w-full md:w-64">
          <Input 
            value={search} 
            onChange={(e) => setSearch(e.target.value)} 
            placeholder="Search segments..." 
            className="h-9 text-xs"
          />
        </div>
      </div>
      <div className="hidden lg:grid lg:grid-cols-[minmax(0,0.92fr)_minmax(380px,1fr)_152px] lg:gap-5 lg:px-5 mt-2">
        <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Source</span>
        <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Working translation</span>
        <span className="text-right text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Actions</span>
      </div>
      {filteredSegments.map((segment) => (
        <SegmentRow key={segment.id} segment={segment} onError={onError} afterChange={afterChange} />
      ))}
      {filteredSegments.length === 0 && (
        <div className="p-8 text-center text-sm text-[var(--text-tertiary)] border border-dashed border-[var(--border-medium)] rounded-lg">
          No segments match your current filters.
        </div>
      )}
    </section>
  );
}

function FilterChip({ 
  active, 
  onClick, 
  icon, 
  label, 
  count,
  activeColor = "text-[var(--text-primary)]",
  activeBg = "bg-[var(--surface-hover)] border-[var(--border-medium)] shadow-sm"
}: { 
  active: boolean; 
  onClick: () => void; 
  icon: React.ReactNode; 
  label: string; 
  count: number;
  activeColor?: string;
  activeBg?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`group flex items-center gap-2 px-3 py-1.5 rounded-full text-[13px] font-medium border transition-all duration-200 ${
        active
          ? `${activeBg} ${activeColor}`
          : "bg-[var(--surface-card)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] border-[var(--border-light)] hover:border-[var(--border-medium)]"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span className={active ? activeColor : "text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)] transition-colors"}>
          {icon}
        </span>
        <span className="whitespace-nowrap">{label}</span>
      </div>
      <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold leading-none ${
        active 
          ? "bg-black/5 dark:bg-white/10"
          : "bg-[var(--border-light)]/50 group-hover:bg-[var(--border-light)] text-[var(--text-secondary)]"
      }`}>
        {count}
      </span>
    </button>
  );
}

function SegmentRow({
  segment,
  onError,
  afterChange
}: {
  segment: Segment;
  onError: (message: string | null) => void;
  afterChange: () => Promise<void>;
}) {
  const [text, setText] = useState(segment.translation?.approved_text ?? segment.translation?.candidate_text ?? "");
  useEffect(() => {
    setText(segment.translation?.approved_text ?? segment.translation?.candidate_text ?? "");
  }, [segment.id, segment.translation?.approved_text, segment.translation?.candidate_text]);
  const saveMutation = useMutation({
    mutationFn: () => patchTranslation(segment.id, text),
    onMutate: () => onError(null),
    onSuccess: () => afterChange(),
    onError: (err) => onError((err as Error).message)
  });
  const approveMutation = useMutation({
    mutationFn: () => approveSegment(segment.id, text),
    onMutate: () => onError(null),
    onSuccess: () => afterChange(),
    onError: (err) => onError((err as Error).message)
  });

  const riskReasons = segment.translation?.risk_reasons ?? [];
  const primaryRiskReason = riskReasons[0];
  const secondaryRiskLabels = riskReasons.slice(1).map((reason) => reason.label);
  const isApproved = segment.status === "approved";
  const hasMemoryHit = segment.translation?.source_type === "memory";
  const hasGlossaryHit = segment.glossary_hits.length > 0;
  const baselineText = (segment.translation?.approved_text ?? segment.translation?.candidate_text ?? "").trim();
  const isDirty = text.trim() !== baselineText;
  const canSave = Boolean(segment.translation && text.trim() && isDirty && !saveMutation.isPending);
  const canApprove = Boolean(segment.translation && text.trim() && (!isApproved || isDirty));
  const isCompactRow = Math.max(segment.source_text.length, text.length) < 44 && !segment.source_text.includes("\n") && !text.includes("\n");
  const rowAccentClass = riskReasons.length
    ? "border-l-[3px] border-l-amber-400 dark:border-l-amber-500 border-amber-200/90 dark:border-amber-500/30 bg-amber-50/40 dark:bg-amber-500/10"
    : hasMemoryHit
      ? "border-l-[3px] border-l-sky-400 dark:border-l-sky-500 border-sky-200/90 dark:border-sky-500/30 bg-sky-50/30 dark:bg-sky-500/10"
      : isApproved
        ? "border-l-[3px] border-l-emerald-400 dark:border-l-emerald-500 border-emerald-200/90 dark:border-emerald-500/30 bg-emerald-50/20 dark:bg-emerald-500/10"
        : "border-l-[3px] border-l-[var(--border-medium)] border-[var(--border-light)] bg-[var(--surface-card)]";

  return (
    <article className={`grid gap-4 rounded-md border p-4 shadow-[0_1px_2px_rgba(31,36,31,0.05)] lg:grid-cols-[minmax(0,0.92fr)_minmax(380px,1fr)_152px] ${rowAccentClass}`}>
      <div className="min-w-0 lg:col-span-3">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge tone="neutral">#{segment.sequence}</Badge>
          <Badge>{segmentTypeLabel(segment.segment_type)}</Badge>
          {riskReasons.length ? <Badge tone="risk">Flagged for review</Badge> : null}
          {hasMemoryHit ? <Badge tone="memory">Memory hit</Badge> : null}
          {isApproved ? <Badge tone="approved">Approved</Badge> : null}
          {hasGlossaryHit ? <Badge tone="glossary">Glossary match</Badge> : null}
        </div>
        {primaryRiskReason ? (
          <div className="mb-1 flex items-start gap-2 rounded-md border border-amber-200 dark:border-amber-500/30 bg-amber-50/80 dark:bg-amber-500/10 px-3 py-2 text-sm leading-5 text-amber-950 dark:text-amber-300">
            <AlertTriangle className="mt-0.5 shrink-0" size={16} />
            <div className="min-w-0">
              <p className="font-semibold">{isApproved ? "Approved after review" : "Review before approval"}</p>
              <p className="text-amber-900/90 dark:text-amber-400/90">{primaryRiskReason.detail ?? primaryRiskReason.label}</p>
              {secondaryRiskLabels.length ? (
                <p className="mt-1 text-xs font-medium leading-5 text-amber-900/80 dark:text-amber-400/70">
                  Also checked: {secondaryRiskLabels.join(", ")}
                </p>
              ) : null}
              <p className="mt-1 text-xs font-medium leading-5 text-amber-900/80 dark:text-amber-400/70">
                {isApproved
                  ? "This difference stays visible in the review record."
                  : "If the change is intentional, approve the segment after checking it."}
              </p>
            </div>
          </div>
        ) : null}
      </div>
      <div className="min-w-0 border-b border-[var(--border-light)] pb-4 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-4">
        <div className="mb-3">
          <p className="text-sm font-semibold text-[var(--text-primary)]">Source text</p>
        </div>
        <p className="whitespace-pre-wrap text-[15px] leading-6 text-[var(--text-primary)]">{segment.source_text}</p>
        {segment.protected_entities.length ? (
          <div className="mt-3">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Protected spans</p>
            <div className="flex flex-wrap gap-2">
              {segment.protected_entities.map((entity, index) => (
                <Badge key={`${entity.kind}-${entity.text}-${index}`}>
                  {entityKindLabel(entity.kind)}: {entity.text}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </div>
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {isApproved ? "Approved translation" : "Working translation"}
            </p>
            <p className="text-xs font-medium leading-5 text-[var(--text-tertiary)]">
              {translationSourceLabel(segment.translation?.source_type, segment.translation?.provider_name)}
            </p>
            {hasMemoryHit && segment.translation?.memory_provenance ? (
              <p className="mt-1 text-xs font-medium leading-5 text-[var(--text-tertiary)]">
                {memoryProvenanceLabel(segment.translation.memory_provenance)}
              </p>
            ) : null}
          </div>
          {isApproved ? (
            riskReasons.length ? (
              <div className="inline-flex items-center gap-1.5 rounded-md border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-950 dark:text-amber-400">
                <ShieldCheck className="shrink-0 text-amber-800 dark:text-amber-400" size={15} />
                Approved after review
              </div>
            ) : (
              <div className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-900 dark:text-emerald-400">
                <ShieldCheck className="shrink-0 text-emerald-700 dark:text-emerald-400" size={15} />
                Ready for export
              </div>
            )
          ) : null}
        </div>
        <Textarea
          className={isCompactRow ? "min-h-[84px]" : "min-h-[108px]"}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              event.preventDefault();
              if (canApprove) approveMutation.mutate();
            }
          }}
          aria-label={`Translation for segment ${segment.sequence}`}
          title="Press Ctrl+Enter to approve"
        />
      </div>
      <div className="flex flex-row gap-2 lg:flex-col lg:items-stretch lg:justify-start">
        <SecondaryButton className="w-full" onClick={() => saveMutation.mutate()} disabled={!canSave}>
          {saveMutation.isPending ? "Saving" : isApproved ? "Save revision" : "Save draft"}
        </SecondaryButton>
        <Button className="w-full" onClick={() => approveMutation.mutate()} disabled={approveMutation.isPending || !canApprove}>
          <Check size={16} />
          {approveMutation.isPending ? "Approving" : isApproved && isDirty ? "Re-approve" : isApproved ? "Approved" : "Approve"}
        </Button>
      </div>
    </article>
  );
}

function CountPill({ label, value, max, tone }: { label: string; value: number; max?: number; tone?: "green" | "amber" | "sky" }) {
  return (
    <span className="flex min-h-[70px] flex-col justify-between rounded-lg border border-[var(--border-light)] bg-[var(--surface-hover)]/60 px-3 py-3 text-xs font-medium text-[var(--text-secondary)]">
      <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{label}</span>
      <span className="text-lg font-bold tabular-nums text-[var(--text-primary)]">{value}</span>
      {max != null && max > 0 && tone && <MiniProgressBar value={value} max={max} tone={tone} />}
    </span>
  );
}

function TrustSummaryPanel({ summary }: { summary: TrustSummary }) {
  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-[12px] font-bold uppercase tracking-[0.15em] text-[#2d8a5e]">Trust summary</h3>
          <p className="mt-1.5 text-[13px] font-medium leading-5 text-[var(--text-tertiary)]">
            What SANAD has verified in the current review state.
          </p>
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-light)] bg-[var(--surface-card)] px-3 py-1.5 text-[12px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] shadow-sm">
          <ShieldCheck size={14} className="text-[#2d8a5e]" />
          Export-readiness
        </div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <TrustStat value={`${summary.approved_segments}/${summary.total_segments}`} label="Approved segments" progress={summary.total_segments > 0 ? summary.approved_segments / summary.total_segments : 0} />
        <TrustStat value={String(summary.memory_reused_segments)} label="Memory hits" />
        <TrustStat
          value={
            summary.protected_values_total > 0
              ? `${summary.protected_values_preserved}/${summary.protected_values_total}`
              : "None detected"
          }
          label="Protected values"
          progress={summary.protected_values_total > 0 ? summary.protected_values_preserved / summary.protected_values_total : undefined}
        />
        <TrustStat value={String(summary.unresolved_review_flags)} label="Unresolved flags" highlight={summary.unresolved_review_flags > 0} />
      </div>
    </div>
  );
}

function TrustStat({ value, label, progress, highlight }: { value: string; label: string; progress?: number; highlight?: boolean }) {
  return (
    <div className={`flex flex-col justify-between rounded-xl border bg-[var(--surface-card)] px-4 py-4 shadow-sm transition-shadow hover:shadow-md ${highlight ? "border-amber-200 dark:border-amber-500/30 bg-amber-50/40 dark:bg-amber-500/10" : "border-[var(--border-light)]"}`}>
      <div>
        <p className={`text-[11px] font-bold uppercase tracking-[0.14em] break-words whitespace-normal ${highlight ? "text-amber-600/80 dark:text-amber-500/90" : "text-[var(--text-tertiary)]"}`}>{label}</p>
        <p className={`mt-1.5 text-xl font-bold tabular-nums leading-none break-words whitespace-normal ${highlight ? "text-amber-700 dark:text-amber-400" : "text-[var(--text-primary)]"}`}>{value}</p>
      </div>
      {progress != null && (
        <div className="mt-4">
          <MiniProgressBar value={Math.round(progress * 100)} max={100} tone="green" />
        </div>
      )}
    </div>
  );
}

function LanguageCoverageRow({ path, isFirst }: { path: LanguagePathReadiness; isFirst: boolean }) {
  return (
    <div className={`grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start ${isFirst ? "" : "border-t border-[var(--border-light)]"}`}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-[var(--text-primary)]">
            {languageCodeLabel(path.source_lang)} → {languageCodeLabel(path.target_lang)}
          </p>
        </div>
        <p className="mt-1 text-xs font-medium leading-5 text-[var(--text-secondary)]">{path.judge_copy}</p>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
          Evidence: {evidenceSourceLabel(path.evidence_source)}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 md:justify-end">
        <Badge tone={coverageTone(path.status)}>{coverageStatusLabel(path.status)}</Badge>
      </div>
    </div>
  );
}

function allSegmentsApproved(counts: Record<string, number>) {
  const segments = counts.segments ?? 0;
  return segments > 0 && (counts.approved ?? 0) === segments;
}

function remainingApprovalCount(counts: Record<string, number>) {
  return Math.max(0, (counts.segments ?? 0) - (counts.approved ?? 0));
}

function segmentTypeLabel(segmentType: string) {
  if (segmentType === "paragraph") return "Text segment";
  if (segmentType === "table_cell_paragraph") return "Table segment";
  return "Segment";
}

function statusLabel(status: string) {
  return humanizeLabel(status);
}

function languageLabel(language: string) {
  return languageCodeLabel(language);
}

function humanizeLabel(value: string | null | undefined) {
  if (!value) return "";
  return value
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function scopeLabel(domain: string, subdomain: string | null) {
  return [humanizeLabel(domain), humanizeLabel(subdomain)].filter(Boolean).join(" / ");
}

function entityKindLabel(kind: string) {
  const labels: Record<string, string> = {
    date: "Date",
    money: "Money",
    number: "Number",
    phone: "Phone",
    url: "URL",
    office: "Office",
    id: "ID",
    ward: "Ward"
  };
  return labels[kind] ?? humanizeLabel(kind);
}

function translationSourceLabel(sourceType?: string, providerName?: string) {
  if (sourceType === "memory") return "From scoped translation memory";
  if (sourceType === "provider") {
    if (providerName === "official_api") return "From official TMT API (live)";
    if (providerName === "tmt_official") return "From official TMT API (live)";
    if (providerName === "legacy_api") return "From TMT public endpoint";
    if (providerName === "tmt_legacy") return "From TMT public endpoint";
    if (providerName === "fixture_fallback") return "From offline fixture (API unavailable)";
    if (providerName === "fixture") return "Prepared review candidate";
    if (providerName === "tmt_api") return "From live TMT translation";
    if (providerName === "mock") return "From test translation provider";
    if (providerName) return `From ${humanizeLabel(providerName)} provider`;
    return "From translation provider";
  }
  return "Ready for reviewer confirmation";
}

function memoryProvenanceLabel(provenance: {
  source_document_filename: string | null;
  scope_label: string;
  approved_at: string;
  times_used: number;
}) {
  const parts = [
    provenance.source_document_filename ? `Reused from ${provenance.source_document_filename}` : "Reused from approved memory",
    provenance.scope_label,
    `approved ${formatShortDate(provenance.approved_at)}`,
    `${provenance.times_used} use${provenance.times_used === 1 ? "" : "s"}`
  ];
  return parts.join(" · ");
}

function formatShortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function coverageTone(status: CoverageStatus) {
  const tones: Record<CoverageStatus, "status" | "memory" | "neutral"> = {
    preferred_demo: "status",
    featured_multilingual: "memory",
    supported_workflow: "neutral"
  };
  return tones[status];
}

function approvalHint(counts: Record<string, number>) {
  const remaining = remainingApprovalCount(counts);
  const flagged = counts.needs_review ?? 0;
  if (remaining === 0) return "Everything is approved. Export is ready.";
  if (flagged === 0) return `${remaining} segment${remaining === 1 ? "" : "s"} still need approval before export.`;
  if (flagged === remaining) {
    return `${remaining} flagged segment${remaining === 1 ? "" : "s"} still need reviewer approval before export.`;
  }
  return `${remaining} segments still need approval, including ${flagged} flagged for review.`;
}

function feedbackPackHint(counts: Record<string, number>) {
  if (allSegmentsApproved(counts)) {
    return "Approved, privacy-reduced review data is ready as a contribution pack for feedback or corpus use.";
  }
  return "Contribution pack becomes available after every segment is approved.";
}

function exportFormatLabel(fileType: string) {
  if (fileType === "csv") return "CSV";
  if (fileType === "tsv") return "TSV";
  if (fileType === "pdf") return "PDF";
  return "DOCX";
}

function sourceDetectionMessage(detection: SourceLanguageDetection) {
  if (detection.source_lang && detection.confidence === "high") {
    return `Detected ${languageCodeLabel(detection.source_lang)} from the document preview. Change if needed.`;
  }
  if (detection.source_lang && detection.confidence === "medium") {
    return `Suggested ${languageCodeLabel(detection.source_lang)} from the document preview. Please confirm.`;
  }
  return detection.explanation;
}
