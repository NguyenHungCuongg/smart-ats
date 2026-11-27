// Activity Timeline formatting for Jobs and Applications (FR-A3.3, NFR-USE-03).

import type { Translator } from "../../i18n/messages";
import { ROLE_NAMES, type Role } from "../settings/members/members";
import type { JobStatus } from "./lifecycle";
import { SOURCES, STAGES, type Source, type Stage } from "./pipeline";

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
  | "job.reviewers_changed"
  | "job.cvs_uploaded"
  | "job.cv_parse_retried"
  | "job.scoring_run_started";

export type ApplicationActivityAction =
  | "application.created"
  | "application.stage_changed"
  | "application.score_retried"
  | "application.scored"
  | "application.email_sent"
  | "application.email_failed";

const APPLICATION_EMAIL_KINDS = [
  "APPLY_RECEIPT",
  "INVITE_INTERVIEW",
  "RESULT",
  "FOLLOW_UP",
] as const;

type ApplicationEmailKind = (typeof APPLICATION_EMAIL_KINDS)[number];

export type WorkspaceActivityAction =
  | "invitation.created"
  | "invitation.revoked"
  | "invitation.accepted"
  | "invitation.email_sent"
  | "invitation.email_failed"
  | "member.role_changed"
  | "member.revoked";

export type ActivityAction =
  JobActivityAction | ApplicationActivityAction | WorkspaceActivityAction;

export type ActivityEntry = {
  id: string;
  action: ActivityAction;
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

function formatRole(value: unknown): string {
  const role = String(value ?? "");
  return role in ROLE_NAMES ? ROLE_NAMES[role as Role] : role;
}

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

export type ActivityTranslators = {
  t: Translator<"activity">;
  statusName: Translator<"lifecycle.status">;
  jobField: Translator<"job">;
  stageName: Translator<"pipeline.stage">;
  sourceName: Translator<"pipeline.source">;
  locale: string;
};

/** Pure formatter turning one Activity Timeline entry into a localized sentence. */
export function formatActivity(
  entry: ActivityEntry,
  { t, statusName, jobField, stageName, sourceName, locale }: ActivityTranslators,
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
    case "job.cvs_uploaded": {
      const count = Number(entry.after?.file_count ?? 0);
      return t("job.cvsUploaded", { actor, count });
    }
    case "job.cv_parse_retried":
      return t("job.cvParseRetried", { actor });
    case "job.scoring_run_started": {
      const count = Number(entry.after?.application_count ?? 0);
      return t("job.scoringRunStarted", { actor, count });
    }
    case "application.created": {
      const sourceKey = String(entry.after?.source ?? "UPLOAD") as Source;
      const stageKey = String(entry.after?.stage ?? "APPLIED") as Stage;
      return t("application.created", {
        actor,
        source: SOURCES.includes(sourceKey) ? sourceName(sourceKey) : sourceKey,
        stage: STAGES.includes(stageKey) ? stageName(stageKey) : stageKey,
      });
    }
    case "application.stage_changed": {
      const fromKey = String(entry.before?.stage ?? "APPLIED") as Stage;
      const toKey = String(entry.after?.stage ?? "APPLIED") as Stage;
      return t("application.stageChanged", {
        actor,
        from: STAGES.includes(fromKey) ? stageName(fromKey) : fromKey,
        to: STAGES.includes(toKey) ? stageName(toKey) : toKey,
      });
    }
    case "application.score_retried":
      return t("application.scoreRetried", { actor });
    case "application.scored": {
      if (entry.after?.status === "SCORED") {
        const rawScore = Number(entry.after?.total_score ?? 0);
        const score = rawScore.toLocaleString(locale, { maximumFractionDigits: 2 });
        return t("application.scoredSucceeded", { actor, score });
      }
      const error = String(entry.after?.error_code ?? "SCORING_FAILED");
      return t("application.scoredFailed", { actor, error });
    }
    case "application.email_sent":
    case "application.email_failed": {
      const rawKind = String(entry.after?.kind ?? "");
      const kind = APPLICATION_EMAIL_KINDS.includes(rawKind as ApplicationEmailKind)
        ? t(`emailKind.${rawKind as ApplicationEmailKind}`)
        : rawKind;
      return entry.action === "application.email_sent"
        ? t("application.emailSent", { actor, kind })
        : t("application.emailFailed", { actor, kind });
    }
    case "invitation.created":
      return t("invitation.created", { actor, role: formatRole(entry.after?.role) });
    case "invitation.revoked":
      return t("invitation.revoked", { actor });
    case "invitation.accepted":
      return t("invitation.accepted", { actor, role: formatRole(entry.after?.role) });
    case "invitation.email_sent":
      return t("invitation.emailSent", { actor });
    case "invitation.email_failed":
      return t("invitation.emailFailed", { actor });
    case "member.role_changed":
      return t("member.roleChanged", {
        actor,
        from: formatRole(entry.before?.role),
        to: formatRole(entry.after?.role),
      });
    case "member.revoked":
      return t("member.revoked", { actor });
  }
}
