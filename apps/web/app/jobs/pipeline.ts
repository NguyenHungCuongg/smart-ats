// The Application pipeline of FR-A3.2 as the Kanban Board shows it; the API holds the same rules.

import type { Translator } from "../../i18n/messages";

export const STAGES = [
  "APPLIED",
  "SCREENING",
  "SHORTLISTED",
  "INTERVIEW",
  "OFFER",
  "HIRED",
  "REJECTED",
] as const;
export type Stage = (typeof STAGES)[number];
export const SOURCES = ["UPLOAD", "PUBLIC_APPLY", "REDISCOVERY"] as const;
export type Source = (typeof SOURCES)[number];

/** An Application as GET /api/jobs/{id}/applications sends it. */
export type Card = {
  id: string;
  full_name: string | null;
  /** Absent for a Reviewer, who sees no contact details (SRS §2.1). */
  email?: string | null;
  stage: Stage;
  rejected_reason: string | null;
  /** Sent back with each move: the API refuses it if the Application changed since. */
  version: number;
  source: Source;
  /** 0–100, of the newest Scoring Run that scored it. */
  total_score: number | null;
  file_name: string;
};

export type Filter = { source: Source | ""; min: string; max: string };

const ACTIVE: Stage[] = ["APPLIED", "SCREENING", "SHORTLISTED", "INTERVIEW", "OFFER"];

/** The Stages an Application in from may move to. */
export function targets(from: Stage): Stage[] {
  if (from === "HIRED") return [];
  if (from === "REJECTED") return ACTIVE;
  return STAGES.filter((stage) => stage !== from);
}

/** What a move asks for first: an optional reason to reject, a required one to reopen. */
export function ask(from: Stage, to: Stage): "reject" | "reopen" | null {
  if (from === "REJECTED") return "reopen";
  return to === "REJECTED" ? "reject" : null;
}

/** The Stages every selected card may move to at once; a bulk move sends no reason. */
export function bulkTargets(selected: Card[]): Stage[] {
  return STAGES.filter((to) =>
    selected.every((card) => targets(card.stage).includes(to) && ask(card.stage, to) !== "reopen"),
  );
}

/** The cards of filter's source whose Total lies in its range; a range leaves out those never
 * scored. */
export function visible(cards: Card[], filter: Filter): Card[] {
  const min = filter.min === "" ? null : Number(filter.min);
  const max = filter.max === "" ? null : Number(filter.max);
  return cards.filter(
    (card) =>
      (filter.source === "" || card.source === filter.source) &&
      ((min === null && max === null) ||
        (card.total_score !== null &&
          (min === null || card.total_score >= min) &&
          (max === null || card.total_score <= max))),
  );
}

/** Why a move failed. */
export function moveError(t: Translator<"pipeline">, status: number): string {
  // 409: another user moved a card first, or the move breaks a rule of the Stage it is in now.
  if (status === 409) return t("conflict");
  if (status === 422) return t("reasonRequired");
  return t("failed");
}
