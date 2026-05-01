import { useEffect, useState, useRef } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes
} from "react";
import { ChevronDown, Download } from "lucide-react";

/* ──────────────────────────────────────────────────────────
  Core UI components
  ────────────────────────────────────────────────────────── */

export function Button({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-[#1a5c3a] px-5 text-sm font-semibold text-white shadow-[0_1px_3px_rgba(15,23,18,0.2),0_1px_1px_rgba(15,23,18,0.1)] transition-all duration-200 hover:bg-[#164e32] hover:shadow-[0_2px_6px_rgba(15,23,18,0.22)] hover:-translate-y-[0.5px] active:translate-y-0 active:shadow-[0_1px_2px_rgba(15,23,18,0.15)] focus:outline-none focus:ring-2 focus:ring-[#2d8a5e]/30 focus:ring-offset-1 disabled:cursor-not-allowed disabled:bg-[var(--surface-hover)] disabled:text-[var(--text-tertiary)] disabled:shadow-none disabled:translate-y-0 ${className}`}
      {...props}
    />
  );
}

export function SecondaryButton({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-[var(--border-light)] bg-[var(--surface-card)] px-4 text-sm font-semibold text-[var(--text-primary)] shadow-[0_1px_2px_rgba(28,25,23,0.05)] transition-all duration-200 hover:border-[var(--border-medium)] hover:bg-[var(--surface-hover)] hover:shadow-[0_2px_4px_rgba(28,25,23,0.08)] hover:-translate-y-[0.5px] active:translate-y-0 focus:outline-none focus:ring-2 focus:ring-[var(--border-light)] disabled:cursor-not-allowed disabled:border-[var(--border-light)] disabled:bg-[var(--surface-page)] disabled:text-[var(--text-tertiary)] disabled:shadow-none disabled:translate-y-0 ${className}`}
      {...props}
    />
  );
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-12 w-full rounded-lg border border-[var(--border-medium)] bg-[var(--surface-card)] px-3.5 text-sm text-[var(--text-primary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.04)] outline-none transition-all duration-200 placeholder:text-[var(--text-tertiary)] hover:border-[var(--text-secondary)] focus:border-[#2d8a5e] focus:ring-2 focus:ring-[#2d8a5e]/15 focus:shadow-[0_0_0_1px_rgba(45,138,94,0.1)] disabled:bg-[var(--surface-page)] disabled:text-[var(--text-tertiary)] ${className}`}
      {...props}
    />
  );
}

export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative w-full">
      <select
        className={`h-12 w-full appearance-none rounded-lg border border-[var(--border-medium)] bg-[var(--surface-card)] px-3.5 pr-11 text-sm font-medium text-[var(--text-primary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.04)] outline-none transition-all duration-200 hover:border-[var(--text-secondary)] focus:border-[#2d8a5e] focus:ring-2 focus:ring-[#2d8a5e]/15 disabled:bg-[var(--surface-page)] disabled:text-[var(--text-tertiary)] ${className}`}
        {...props}
      />
      <span className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-[var(--text-tertiary)]">
        <ChevronDown size={18} strokeWidth={2.1} />
      </span>
    </div>
  );
}

export function Textarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`min-h-[96px] w-full resize-y rounded-lg border border-[var(--border-medium)] bg-[var(--surface-card)] px-3 py-2.5 text-[15px] leading-6 text-[var(--text-primary)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.04)] outline-none transition-all duration-200 hover:border-[var(--text-secondary)] focus:border-[#2d8a5e] focus:ring-2 focus:ring-[#2d8a5e]/15 disabled:bg-[var(--surface-page)] disabled:text-[var(--text-tertiary)] ${className}`}
      {...props}
    />
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "risk" | "memory" | "glossary" | "approved" | "status"; children: ReactNode }) {
  const tones = {
    neutral: "border-[var(--border-medium)] bg-[var(--surface-hover)] text-[var(--text-secondary)]",
    status: "border-[#2d8a5e]/20 dark:border-[#2d8a5e]/40 bg-[#eef7f2] dark:bg-[#1a5c3a]/20 text-[#1a5c3a] dark:text-[#4ade80]",
    risk: "border-amber-300 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 text-amber-950 dark:text-amber-400",
    memory: "border-sky-300 dark:border-sky-500/30 bg-sky-50 dark:bg-sky-500/10 text-sky-950 dark:text-sky-400",
    glossary: "border-violet-300 dark:border-violet-500/30 bg-violet-50 dark:bg-violet-500/10 text-violet-950 dark:text-violet-400",
    approved: "border-emerald-300 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-950 dark:text-emerald-400"
  };
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold leading-none tracking-wide ${tones[tone]}`}>{children}</span>;
}

export function ExportDropdown({
  formats,
  onExport,
  disabled,
  title,
  className = ""
}: {
  formats: string[];
  onExport: (format: string) => void;
  disabled: boolean;
  title: string;
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className={`relative inline-block text-left ${className}`} ref={dropdownRef}>
      <Button
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled}
        title={title}
        className={`justify-between ${className ? 'w-full' : 'w-[140px]'}`}
      >
        <span className="flex items-center gap-2">
          <Download size={16} />
          Export
        </span>
        <ChevronDown size={16} />
      </Button>
      {isOpen && !disabled && (
        <div className="absolute right-0 z-10 mt-2 w-48 origin-top-right rounded-md bg-[var(--surface-card)] shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none">
          <div className="py-1" role="menu" aria-orientation="vertical">
            {formats.map((format) => (
              <button
                key={format}
                className="block w-full px-4 py-2 text-left text-sm text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]"
                role="menuitem"
                onClick={() => {
                  setIsOpen(false);
                  onExport(format);
                }}
              >
                {format === "pdf" ? "PDF Document" : format === "docx" ? "Word Document" : "Plain Text"} ({format.toUpperCase()})
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
  Live API status indicator
  ────────────────────────────────────────────────────────── */

type ProviderTier = "tmt_official" | "tmt_legacy" | "fixture_fallback" | "fixture" | "none" | string;

const TIER_CONFIG: Record<string, { dotClass: string; label: string }> = {
  tmt_official: { dotClass: "sanad-live-dot sanad-live-dot--green", label: "Live TMT API" },
  tmt_legacy: { dotClass: "sanad-live-dot sanad-live-dot--amber", label: "TMT Public" },
  fixture_fallback: { dotClass: "sanad-live-dot sanad-live-dot--red", label: "Offline Mode" },
  fixture: { dotClass: "sanad-live-dot sanad-live-dot--gray", label: "Demo Fixtures" },
  offline: { dotClass: "sanad-live-dot sanad-live-dot--red", label: "Backend Offline" },
  none: { dotClass: "sanad-live-dot sanad-live-dot--gray", label: "Connecting…" },
};

export function LiveStatusIndicator({ tier, compact }: { tier?: ProviderTier; compact?: boolean }) {
  const config = TIER_CONFIG[tier ?? "none"] ?? TIER_CONFIG["none"];

  if (compact) {
    return (
      <span className="inline-flex items-center gap-1.5" title={config.label}>
        <span className={config.dotClass} />
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[var(--border-light)] bg-[var(--surface-card)]/80 backdrop-blur-sm px-3 py-1.5 text-xs font-semibold text-[var(--text-secondary)] shadow-[0_1px_3px_rgba(0,0,0,0.06)] transition-all sanad-animate-in">
      <span className={config.dotClass} />
      <span>{config.label}</span>
    </span>
  );
}

/* ──────────────────────────────────────────────────────────
  Processing pipeline visualization
  ────────────────────────────────────────────────────────── */

const PIPELINE_STEPS = [
  { label: "Parsing", detail: "Extracting segments" },
  { label: "Translating", detail: "TMT provider" },
  { label: "Scoring", detail: "Risk analysis" },
  { label: "Ready", detail: "Review queue" },
] as const;

export function ProcessingPipeline({ active, documentId }: { active: boolean; documentId?: string | null }) {
  const [currentStep, setCurrentStep] = useState(0);
  const [progressDetails, setProgressDetails] = useState<string>("");

  useEffect(() => {
    if (!active || !documentId) {
      setCurrentStep(0);
      setProgressDetails("");
      return;
    }

    let eventSource: EventSource | null = null;
    
    // We import getSseProgressUrl dynamically or assume API_BASE is known here.
    // For simplicity, we can construct the URL if we pass it, but let's just 
    // fetch from the api lib since it's already in the project.
    import("../lib/api").then(({ getSseProgressUrl }) => {
      if (!active) return;
      eventSource = new EventSource(getSseProgressUrl(documentId));
      
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.status === "failed") {
            eventSource?.close();
            setProgressDetails("Processing failed.");
          } else if (data.status === "processed") {
            // If backend finished super fast, animate the remaining steps quickly for visual satisfaction
            eventSource?.close();
            setProgressDetails("");
            setCurrentStep((prev) => {
              if (prev < 3) {
                let step = prev;
                const interval = setInterval(() => {
                  step++;
                  setCurrentStep(step);
                  if (step >= 3) clearInterval(interval);
                }, 300); // 300ms per step fast-forward
              }
              return prev; // keep current for now, interval will update it
            });
          } else if (data.step === "parsing") {
            setCurrentStep((prev) => Math.max(prev, 0));
            setProgressDetails("");
          } else if (data.step === "translating") {
            setCurrentStep((prev) => Math.max(prev, 1));
            if (data.progress !== undefined && data.total !== undefined) {
              setProgressDetails(`(${data.progress}/${data.total} segments)`);
            }
          } else if (data.step === "scoring") {
            setCurrentStep((prev) => Math.max(prev, 2));
            setProgressDetails("");
          }
        } catch (err) {}
      };

      eventSource.onerror = () => {
        eventSource?.close();
      };
    });

    // Fallback timer if SSE fails or takes too long to connect
    const fallbackInterval = setInterval(() => {
      setCurrentStep((prev) => (prev < 2 ? prev + 1 : prev));
    }, 1500);

    return () => {
      clearInterval(fallbackInterval);
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [active, documentId]);

  if (!active) return null;

  return (
    <div className="sanad-animate-in rounded-lg border border-[var(--border-light)] bg-[var(--surface-card)] p-4 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <span className="sanad-spinner" />
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          Processing document… {progressDetails && <span className="text-[var(--text-tertiary)] font-normal">{progressDetails}</span>}
        </span>
      </div>
      <div className="flex items-center gap-1">
        {PIPELINE_STEPS.map((step, i) => {
          const isDone = i < currentStep;
          const isActive = i === currentStep;
          return (
            <div key={step.label} className="flex items-center gap-1 flex-1">
              <div className="flex-1">
                <div className={`h-1.5 rounded-full transition-all duration-500 ${
                  isDone ? "bg-[#2d8a5e]" : isActive ? "bg-[#3da06e] dark:bg-[#2d8a5e] sanad-shimmer" : "bg-[var(--border-light)]"
                }`} />
                <p className={`mt-1.5 text-[11px] font-semibold transition-colors ${
                  isDone || isActive ? "text-[#1a5c3a] dark:text-[#45b784]" : "text-[var(--text-tertiary)]"
                }`}>
                  {step.label}
                </p>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <div className={`w-2 h-[1.5px] mt-[-14px] ${isDone ? "bg-[#2d8a5e]" : "bg-[var(--border-light)]"}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────
  Mini progress bar (for trust summary)
  ────────────────────────────────────────────────────────── */

export function MiniProgressBar({ value, max, tone = "green" }: { value: number; max: number; tone?: "green" | "amber" | "sky" }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const colors = {
    green: "bg-[#2d8a5e]",
    amber: "bg-amber-500",
    sky: "bg-sky-500",
  };
  return (
    <div className="sanad-progress-bar mt-2">
      <div
        className={`sanad-progress-bar__fill ${colors[tone]}`}
        style={{ width: `${pct}%`, background: tone === "green" ? undefined : undefined }}
      />
    </div>
  );
}
