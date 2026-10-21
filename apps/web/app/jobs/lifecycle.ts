// The Job lifecycle of FR-A3.1 as the pages show it; the API holds the same edges.

import type { Role } from "../settings/members/members";

export const JOB_STATUSES = ["DRAFT", "PUBLISHED", "PAUSED", "CLOSED", "ARCHIVED"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
export type Action = "publish" | "pause" | "resume" | "close" | "archive" | "reopen";

export const STATUS_NAMES: Record<JobStatus, string> = {
  DRAFT: "Nháp",
  PUBLISHED: "Đang tuyển",
  PAUSED: "Tạm dừng",
  CLOSED: "Đã đóng",
  ARCHIVED: "Lưu trữ",
};

export const ACTION_NAMES: Record<Action, string> = {
  publish: "Đăng tuyển",
  pause: "Tạm dừng",
  resume: "Tiếp tục",
  close: "Đóng",
  archive: "Lưu trữ",
  reopen: "Mở lại",
};

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
export function transitionError(status: number): string {
  // 409: another tab or Recruiter moved the Job first.
  return status === 409
    ? "Trạng thái Job vừa thay đổi. Tải lại trang để xem."
    : "Không đổi được trạng thái Job. Vui lòng thử lại.";
}
