import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { 
  BarChart3, 
  BookOpen, 
  Brain, 
  Clock, 
  FileText, 
  Globe, 
  Trash2, 
  Plus 
} from "lucide-react";
import {
  getDocumentHistory,
  getAnalyticsSummary,
  getGlossaryTerms,
  createGlossaryTerm,
  deleteGlossaryTerm,
  getMemoryEntries,
  deleteMemoryEntry,
  deleteDocument
} from "../lib/api";
import { Badge, Button, Input, SecondaryButton, Select } from "./ui";
import { languageCodeLabel } from "../lib/languageCoverage";

/* ──────────────────────────────────────────────────────────
   Document History Sidebar
   ────────────────────────────────────────────────────────── */

export function DocumentHistorySidebar({ 
  currentDocumentId, 
  onSelect 
}: { 
  currentDocumentId: string | null; 
  onSelect: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["documentHistory"],
    queryFn: getDocumentHistory,
    refetchInterval: 15000 // Refetch every 15s to keep status updated
  });

  const deleteDocMutation = useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["documentHistory"] });
      queryClient.invalidateQueries({ queryKey: ["analyticsSummary"] });
      if (currentDocumentId === deletedId) {
        onSelect(""); // Clear selection
      }
    }
  });

  if (!query.data || query.data.length === 0) {
    return null;
  }

  return (
    <div className="w-full lg:w-64 shrink-0 flex flex-col gap-3">
      <div className="flex items-center gap-2 px-1">
        <Clock size={16} className="text-[var(--text-tertiary)]" />
        <h3 className="text-[13px] font-bold uppercase tracking-[0.1em] text-[var(--text-tertiary)]">Recent Documents</h3>
      </div>
      <div className="flex flex-col gap-2 max-h-[calc(100vh-200px)] overflow-y-auto pr-1 sanad-scrollbar">
        {query.data.map(doc => (
          <button
            key={doc.id}
            onClick={() => onSelect(doc.id)}
            className={`group flex flex-col gap-1.5 p-3 rounded-lg border text-left transition-all ${
              currentDocumentId === doc.id 
                ? "border-[#2d8a5e]/40 bg-[var(--sanad-green-50)]/80 shadow-sm"
                : "border-[var(--border-light)] bg-[var(--surface-card)] hover:border-[var(--border-medium)] hover:bg-[var(--surface-hover)]"
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-semibold text-[var(--text-primary)] truncate" title={doc.original_filename}>
                {doc.original_filename}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm("Are you sure you want to delete this document?")) {
                    deleteDocMutation.mutate(doc.id);
                  }
                }}
                disabled={deleteDocMutation.isPending}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-[var(--text-tertiary)] hover:text-red-500 rounded-md hover:bg-red-50 dark:hover:bg-red-500/20"
                title="Delete document"
              >
                <Trash2 size={14} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-[var(--text-tertiary)]">
                {languageCodeLabel(doc.source_lang)} → {languageCodeLabel(doc.target_lang)}
              </span>
              {doc.status === "processed" && <Badge tone="success">Ready</Badge>}
              {doc.status === "exported" && <Badge tone="neutral">Exported</Badge>}
              {doc.status === "failed" && <Badge tone="risk">Failed</Badge>}
              {["uploaded", "processing"].includes(doc.status) && <Badge tone="status">Processing</Badge>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   Analytics Dashboard
   ────────────────────────────────────────────────────────── */

export function AnalyticsDashboard() {
  const query = useQuery({
    queryKey: ["analyticsSummary"],
    queryFn: getAnalyticsSummary,
    refetchInterval: 30000
  });

  if (!query.data) return null;

  return (
    <section className="sanad-animate-in rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] p-5 shadow-sm mb-6">
      <div className="mb-4 flex items-center gap-2">
        <BarChart3 className="text-[#2d8a5e] dark:text-[#45b784]" size={20} />
        <h2 className="text-[1.1rem] font-bold text-[var(--text-primary)]">Translation Overview</h2>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
        <StatCard label="Total Docs" value={query.data.total_documents} />
        <StatCard label="Segments Translated" value={query.data.total_segments} />
        <StatCard label="Memory Entries" value={query.data.total_memory_entries} />
        <StatCard label="Memory Reuse" value={query.data.memory_reuse_count} />
        <StatCard label="Exports" value={query.data.total_exports} />
      </div>
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex flex-col p-3 rounded-lg border border-[var(--border-light)] bg-[var(--surface-hover)]/50">
      <span className="text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--text-tertiary)]">{label}</span>
      <span className="text-xl font-bold tabular-nums mt-1 text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   Glossary Management Panel
   ────────────────────────────────────────────────────────── */

export function GlossaryPanel() {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const [sourceTerm, setSourceTerm] = useState("");
  const [targetTerm, setTargetTerm] = useState("");
  const [sourceLang, setSourceLang] = useState("en");
  const [targetLang, setTargetLang] = useState("ne");
  const [domain, setDomain] = useState("public_service");
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["glossaryTerms"],
    queryFn: getGlossaryTerms,
    enabled: isOpen
  });

  const createMutation = useMutation({
    mutationFn: createGlossaryTerm,
    onMutate: () => setError(null),
    onSuccess: () => {
      setSourceTerm("");
      setTargetTerm("");
      queryClient.invalidateQueries({ queryKey: ["glossaryTerms"] });
    },
    onError: (err) => setError((err as Error).message)
  });

  const deleteMutation = useMutation({
    mutationFn: deleteGlossaryTerm,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossaryTerms"] })
  });

  if (!isOpen) {
    return (
      <SecondaryButton className="w-full justify-start" onClick={() => setIsOpen(true)}>
        <BookOpen size={16} className="text-violet-600 dark:text-violet-400" />
        Manage Glossary Terms
      </SecondaryButton>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] shadow-sm overflow-hidden mt-4">
      <div className="bg-violet-50/50 dark:bg-violet-500/10 p-4 border-b border-violet-100 dark:border-violet-500/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="text-violet-600 dark:text-violet-400" size={18} />
          <h3 className="font-bold text-violet-950 dark:text-violet-300">Terminology Glossary</h3>
        </div>
        <button onClick={() => setIsOpen(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] text-sm font-medium">Close</button>
      </div>

      <div className="p-4 bg-[var(--surface-hover)]/30 border-b border-[var(--border-light)]">
        <form 
          className="flex flex-wrap md:flex-nowrap gap-3 items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!sourceTerm.trim() || !targetTerm.trim()) return;
            createMutation.mutate({
              source_lang: sourceLang,
              target_lang: targetLang,
              domain,
              source_term: sourceTerm,
              target_term: targetTerm,
              term_type: "term"
            });
          }}
        >
          <div className="flex-1 min-w-[120px]">
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">Source Term</label>
            <Input value={sourceTerm} onChange={e => setSourceTerm(e.target.value)} placeholder="e.g. resident" required />
          </div>
          <div className="flex-1 min-w-[120px]">
            <label className="block text-[11px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] mb-1">Target Term</label>
            <Input value={targetTerm} onChange={e => setTargetTerm(e.target.value)} placeholder="e.g. निवासी" required />
          </div>
          <Button type="submit" disabled={createMutation.isPending || !sourceTerm.trim() || !targetTerm.trim()} className="bg-violet-600 hover:bg-violet-700">
            <Plus size={16} /> Add Term
          </Button>
        </form>
        {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
      </div>

      <div className="max-h-[300px] overflow-y-auto">
        {query.isLoading ? (
          <div className="p-8 text-center text-[var(--text-tertiary)] text-sm">Loading terms...</div>
        ) : query.data?.length === 0 ? (
          <div className="p-8 text-center text-[var(--text-tertiary)] text-sm">No glossary terms found.</div>
        ) : (
          <table className="w-full text-sm text-left">
            <thead className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] bg-[var(--surface-hover)] sticky top-0">
              <tr>
                <th className="px-4 py-3 border-b">Source Term</th>
                <th className="px-4 py-3 border-b">Target Term</th>
                <th className="px-4 py-3 border-b hidden sm:table-cell">Context</th>
                <th className="px-4 py-3 border-b text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {query.data?.map(term => (
                <tr key={term.id} className="hover:bg-[var(--surface-hover)]">
                  <td className="px-4 py-2.5 font-medium text-[var(--text-primary)]">{term.source_term}</td>
                  <td className="px-4 py-2.5 text-[var(--text-secondary)]">{term.target_term}</td>
                  <td className="px-4 py-2.5 hidden sm:table-cell">
                    <div className="flex gap-1.5">
                      <Badge tone="neutral">{term.source_lang}→{term.target_lang}</Badge>
                      <Badge tone="neutral">{term.domain}</Badge>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button 
                      onClick={() => deleteMutation.mutate(term.id)}
                      disabled={deleteMutation.isPending}
                      className="text-[var(--text-tertiary)] hover:text-red-500 transition-colors p-1"
                      title="Delete term"
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
   Memory Browser Panel
   ────────────────────────────────────────────────────────── */

export function MemoryBrowserPanel() {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(false);
  const query = useQuery({
    queryKey: ["memoryEntries"],
    queryFn: getMemoryEntries,
    enabled: isOpen
  });

  const deleteMutation = useMutation({
    mutationFn: deleteMemoryEntry,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memoryEntries"] })
  });

  if (!isOpen) {
    return (
      <SecondaryButton className="w-full justify-start mt-2" onClick={() => setIsOpen(true)}>
        <Brain size={16} className="text-sky-600 dark:text-sky-400" />
        Browse Translation Memory
      </SecondaryButton>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border-light)] bg-[var(--surface-card)] shadow-sm overflow-hidden mt-4">
      <div className="bg-sky-50/50 dark:bg-sky-500/10 p-4 border-b border-sky-100 dark:border-sky-500/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="text-sky-600 dark:text-sky-400" size={18} />
          <h3 className="font-bold text-sky-950 dark:text-sky-300">Translation Memory</h3>
        </div>
        <button onClick={() => setIsOpen(false)} className="text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] text-sm font-medium">Close</button>
      </div>

      <div className="max-h-[400px] overflow-y-auto">
        {query.isLoading ? (
          <div className="p-8 text-center text-[var(--text-tertiary)] text-sm">Loading memory...</div>
        ) : query.data?.length === 0 ? (
          <div className="p-8 text-center text-[var(--text-tertiary)] text-sm">No memory entries yet. Approve translations to build memory.</div>
        ) : (
          <table className="w-full text-sm text-left">
            <thead className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-tertiary)] bg-[var(--surface-hover)] sticky top-0">
              <tr>
                <th className="px-4 py-3 border-b">Source Text</th>
                <th className="px-4 py-3 border-b">Approved Translation</th>
                <th className="px-4 py-3 border-b hidden sm:table-cell">Usage</th>
                <th className="px-4 py-3 border-b text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {query.data?.map(entry => (
                <tr key={entry.id} className="hover:bg-[var(--surface-hover)]">
                  <td className="px-4 py-3 text-[var(--text-primary)] max-w-xs truncate" title={entry.source_text}>
                    {entry.source_text}
                  </td>
                  <td className="px-4 py-3 text-[var(--text-secondary)] max-w-xs truncate" title={entry.target_text}>
                    {entry.target_text}
                  </td>
                  <td className="px-4 py-3 hidden sm:table-cell">
                    <div className="flex flex-col gap-1 text-xs">
                      <span className="text-[var(--text-secondary)]">Used {entry.times_used} times</span>
                      {entry.source_document_filename && (
                        <span className="text-[var(--text-tertiary)] truncate max-w-[150px]" title={entry.source_document_filename}>
                          From: {entry.source_document_filename}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button 
                      onClick={() => deleteMutation.mutate(entry.id)}
                      disabled={deleteMutation.isPending}
                      className="text-[var(--text-tertiary)] hover:text-red-500 transition-colors p-1"
                      title="Remove from memory"
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
