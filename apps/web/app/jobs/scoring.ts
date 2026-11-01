// A Job's latest Scoring Run as the API sends it, and when a new one may start (FR-A1.3).

import type { Translator } from "../../i18n/messages";
import type { Job, Weights } from "./criteria";

/** One Fit-Gap Report item or rubric reason; `grounded` is false when no Evidence is left. */
export type Claim = { text?: string; reason?: string; evidence: string[]; grounded: boolean };
export type Axis = "technical" | "soft_skills" | "experience";

/** How a must-have matched a CV skill, from Scoring v1 on. */
export type Match = {
  must_have: string;
  cv_skill: string;
  method: "EXACT" | "ALIAS" | "SEMANTIC";
  /** The cosine of the two names, for a SEMANTIC match. */
  similarity: number | null;
};

/** A work history entry; `months` is null when its dates could not be counted. */
export type TimelineEntry = {
  company: string | null;
  title: string | null;
  start: string | null;
  end: string | null;
  months: number | null;
};

export type ScoreResult = {
  application_id: string;
  full_name: string | null;
  status: "PENDING" | "SCORED" | "FAILED";
  /** The CV scored, and the Application's CV now. */
  cv_document_id: string;
  current_cv_document_id: string;
  technical_score: number | null;
  soft_skills_score: number | null;
  experience_score: number | null;
  total_score: number | null;
  /** 0–1. */
  must_have_coverage: number | null;
  /** `matches` is absent from a v0 Score Result. */
  must_have_detail: { matched: string[]; missing: string[]; matches?: Match[] } | null;
  /** The Experience timeline, computed from the CV; null before v1. */
  experience_detail: {
    entries: TimelineEntry[];
    /** A month several entries share counts once. */
    total_months: number;
    unreadable: TimelineEntry[];
  } | null;
  rubric_grades: Record<Axis, Claim & { grade: number }> | null;
  fit_gap_report: Record<"strengths" | "gaps" | "recommendations", Claim[]> | null;
  error_code: string | null;
};

export type ScoringRun = {
  id: string;
  status: "RUNNING" | "COMPLETED" | "PARTIAL";
  /** Whether it still blocks a new run; the API owns that rule. */
  running: boolean;
  weights: Weights;
  model: string;
  created_at: string;
  completed_at: string | null;
  results: ScoreResult[];
};

/** Why the Job cannot be scored now, or null when it can. */
export function scoreBlocker(
  t: Translator<"scoring">,
  job: Pick<Job, "criteria_confirmed_at">,
  applications: number,
  run: Pick<ScoringRun, "running"> | null,
): string | null {
  if (!job.criteria_confirmed_at) return t("notConfirmed");
  if (applications === 0) return t("noApplications");
  if (run?.running) return t("running");
  return null;
}

/**
 * Wraps deliver so that, of loads started one after another, only the newest is delivered:
 * one that finishes after a newer one started is dropped.
 */
export function newestOnly<T>(deliver: (value: T) => void): (load: Promise<T>) => Promise<void> {
  let started = 0;
  return async (load) => {
    const mine = ++started;
    const value = await load;
    if (mine === started) deliver(value);
  };
}
