// Activity Timeline formatting for a Job (FR-A3.3, NFR-USE-03).

import type { Translator } from "../../i18n/messages";
import type { JobStatus } from "./lifecycle";

export type ActorType = "USER" | "AGENT" | "SYSTEM" | "PUBLIC";

export type ActivityActor = {
  id: string;
  full_name: string;
};

export type JobActivityAction =
  | "job.created"
  | "job.parsed"
  | "job.parse_retried"
  | "job.criteria_confirmed"
  | "job.metadata_changed"
  | "job.status_changed"
  | "job.public_apply_changed"
  | "job.reviewers_changed";

export type ActivityEntry = {
  id: string;
  action: JobActivityAction;
  actor_type: ActorType;
  actor: ActivityActor | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
};

export type ActivityPage = {
  items: ActivityEntry[];
  next_cursor: string | null;
};

const METADATA_FIELD_KEYS = {
  title: "jobTitle",
  level: "level",
  work_mode: "workMode",
  department: "department",
  location: "location",
  apply_deadline: "deadline",
} as const;

/** Format the actor name or label for an Activity Timeline entry. */
export function formatActor(
  entry: Pick<ActivityEntry, "actor_type" | "actor">,
  t: Translator<"activity">,
): string {
  switch (entry.actor_type) {
    case "SYSTEM":
      return t("actor.SYSTEM");
    case "PUBLIC":
      return t("actor.PUBLIC");
    case "AGENT":
      return t("actor.AGENT", { name: entry.actor?.full_name ?? t("actor.unknown") });
    case "USER":
      return entry.actor?.full_name ?? t("actor.unknown");
  }
}

/** Distinct badge label for non-USER actors (`SYSTEM`, `PUBLIC`, `AGENT`), or null for `USER`. */
export function actorBadge(actorType: ActorType, t: Translator<"activity">): string | null {
  if (actorType === "USER") return null;
  return t(`badge.${actorType}`);
}

/** Pure formatter turning one Job Activity Timeline entry into a localized sentence. */
export function formatActivity(
  entry: ActivityEntry,
  t: Translator<"activity">,
  statusName: Translator<"lifecycle.status">,
  jobField: Translator<"job">,
): string {
  const actor = formatActor(entry, t);
  switch (entry.action) {
    case "job.created":
      return t("job.created", { actor });
    case "job.parsed": {
      if (entry.after?.parse_status === "SUCCEEDED") {
        return t("job.parsedSucceeded", { actor });
      }
      const error = String(entry.after?.parse_error ?? "PARSE_FAILED");
      return t("job.parsedFailed", { actor, error });
    }
    case "job.parse_retried":
      return t("job.parseRetried", { actor });
    case "job.criteria_confirmed": {
      const weights = (entry.after?.weights ?? {}) as Record<string, number>;
      return t("job.criteriaConfirmed", {
        actor,
        technical: weights.technical ?? 0,
        soft_skills: weights.soft_skills ?? 0,
        experience: weights.experience ?? 0,
      });
    }
    case "job.metadata_changed": {
      const fields = Object.keys(entry.after ?? {})
        .map((field) => {
          const key = METADATA_FIELD_KEYS[field as keyof typeof METADATA_FIELD_KEYS];
          return key ? jobField(key) : field;
        })
        .join(", ");
      return t("job.metadataChanged", { actor, fields });
    }
    case "job.status_changed": {
      const from = statusName((entry.before?.status ?? "DRAFT") as JobStatus);
      const to = statusName((entry.after?.status ?? "DRAFT") as JobStatus);
      return t("job.statusChanged", { actor, from, to });
    }
    case "job.public_apply_changed":
      return entry.after?.public_apply_enabled
        ? t("job.publicApplyEnabled", { actor })
        : t("job.publicApplyDisabled", { actor });
    case "job.reviewers_changed": {
      const ids = Array.isArray(entry.after?.user_ids) ? entry.after.user_ids : [];
      return t("job.reviewersChanged", { actor, count: ids.length });
    }
  }
}
