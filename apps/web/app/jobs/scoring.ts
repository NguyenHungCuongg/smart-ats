// A Job's latest Scoring Run as the API sends it, and when a new one may start (FR-A1.3).

import type { Job, Weights } from "./criteria";

/** One Fit-Gap Report item or rubric reason; `grounded` is false when no Evidence is left. */
export type Claim = { text?: string; reason?: string; evidence: string[]; grounded: boolean };
export type Axis = "technical" | "soft_skills" | "experience";

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
  must_have_detail: { matched: string[]; missing: string[] } | null;
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
  job: Pick<Job, "criteria_confirmed_at">,
  applications: number,
  run: Pick<ScoringRun, "running"> | null,
): string | null {
  if (!job.criteria_confirmed_at) return "Xác nhận criteria trước khi chấm điểm.";
  if (applications === 0) return "Job chưa có Application nào.";
  if (run?.running) return "Đang chấm điểm…";
  return null;
}
