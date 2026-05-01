export type CoverageStatus = "preferred_demo" | "featured_multilingual" | "supported_workflow";
export type EvidenceSource = "workflow_validation" | "live_observation";

export type LanguagePathReadiness = {
  source_lang: "en" | "ne" | "tmg";
  target_lang: "en" | "ne" | "tmg";
  status: CoverageStatus;
  show_in_main_form: boolean;
  judge_copy: string;
  evidence_source: EvidenceSource;
};

export const LANGUAGE_PATH_MATRIX: LanguagePathReadiness[] = [
  {
    source_lang: "en",
    target_lang: "ne",
    status: "preferred_demo",
    show_in_main_form: true,
    judge_copy: "Fastest path through SANAD's parser, review, memory reuse, and export workflow.",
    evidence_source: "workflow_validation"
  },
  {
    source_lang: "en",
    target_lang: "tmg",
    status: "featured_multilingual",
    show_in_main_form: true,
    judge_copy: "Lower-resource path on the same trust-first review, memory, and export workflow.",
    evidence_source: "workflow_validation"
  },
  {
    source_lang: "ne",
    target_lang: "en",
    status: "supported_workflow",
    show_in_main_form: true,
    judge_copy: "Runs through the same parser, protected-entity checks, review, memory, and export flow.",
    evidence_source: "workflow_validation"
  },
  {
    source_lang: "ne",
    target_lang: "tmg",
    status: "supported_workflow",
    show_in_main_form: true,
    judge_copy: "Runs through the same parser, protected-entity checks, review, memory, and export flow.",
    evidence_source: "workflow_validation"
  },
  {
    source_lang: "tmg",
    target_lang: "en",
    status: "supported_workflow",
    show_in_main_form: true,
    judge_copy: "Runs through the same parser, protected-entity checks, review, memory, and export flow.",
    evidence_source: "workflow_validation"
  },
  {
    source_lang: "tmg",
    target_lang: "ne",
    status: "supported_workflow",
    show_in_main_form: true,
    judge_copy: "Runs through the same parser, protected-entity checks, review, memory, and export flow.",
    evidence_source: "workflow_validation"
  }
];

export const MAIN_DEMO_PATH = LANGUAGE_PATH_MATRIX.find((path) => path.show_in_main_form) ?? LANGUAGE_PATH_MATRIX[0];
export const TAMANG_PROOF_PATH =
  LANGUAGE_PATH_MATRIX.find((path) => path.source_lang === "en" && path.target_lang === "tmg") ?? LANGUAGE_PATH_MATRIX[1];

export function languageCodeLabel(language: string) {
  const labels: Record<string, string> = {
    en: "English",
    ne: "Nepali",
    tmg: "Tamang"
  };
  return labels[language] ?? language;
}

export function coverageStatusLabel(status: CoverageStatus) {
  const labels: Record<CoverageStatus, string> = {
    preferred_demo: "Primary workflow",
    featured_multilingual: "Featured multilingual",
    supported_workflow: "Validated workflow"
  };
  return labels[status];
}

export function evidenceSourceLabel(source: EvidenceSource) {
  const labels: Record<EvidenceSource, string> = {
    workflow_validation: "Validated in SANAD",
    live_observation: "Live TMT response",
  };
  return labels[source];
}

export function sameLanguagePath(
  left: Pick<LanguagePathReadiness, "source_lang" | "target_lang">,
  right: Pick<LanguagePathReadiness, "source_lang" | "target_lang">
) {
  return left.source_lang === right.source_lang && left.target_lang === right.target_lang;
}
