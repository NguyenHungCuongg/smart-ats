// The Job lifecycle of FR-A3.1 as the pages show it; the API holds the same edges.

import type { Translator } from "../../i18n/messages";
import type { Role } from "../settings/members/members";

export const JOB_STATUSES = ["DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
export type Action = "publish" | "pause" | "resume" | "close" | "archive" | "reopen";

const EDGES: Record<JobStatus, Action[]> = {
  DRAFT: ["publish"],
  PUBLISHED: ["pause", "close"],
  PAUSED: ["resume", "close"],
  CLOSED: ["archive", "reopen"],
  ARCHIVED: [],
};

/** The actions that move a Job out of status. */
export function actionsFor(status: JobStatus): Action[] {
  return EDGES[status];
}

/** Whether role may change the Job: Reviewers only read, and ARCHIVED is read-only. */
export function canEdit(role: Role, status: JobStatus): boolean {
  return role !== "REVIEWER" && status !== "ARCHIVED";
}

/** Why POST /api/jobs/{id}/transitions failed. */
export function transitionError(t: Translator<"lifecycle">, status: number): string {
  // 409: another tab or Recruiter moved the Job first.
  return status === 409 ? t("conflict") : t("failed");
}
