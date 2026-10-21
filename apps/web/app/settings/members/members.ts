// The Members API (FR-C1.2) as /settings/members shows it.

import type { Translator } from "../../../i18n/messages";

export const ROLES = ["COMPANY_ADMIN", "RECRUITER", "REVIEWER"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_NAMES: Record<Role, string> = {
  COMPANY_ADMIN: "Company Admin",
  RECRUITER: "Recruiter",
  REVIEWER: "Reviewer",
};

export type Member = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
};

export type EmailStatus = "QUEUED" | "SENT" | "FAILED";

export type Invitation = {
  id: string;
  email: string;
  role: Role;
  created_at: string;
  expires_at: string;
  email_status: EmailStatus;
};

export type Members = { members: Member[]; invitations: Invitation[] };

/** Why POST /api/invitations failed. */
export function inviteError(t: Translator<"members">, status: number): string {
  switch (status) {
    case 409:
      return t("alreadyMember");
    case 422:
      return t("invalidEmail");
    default:
      return t("inviteFailed");
  }
}

/** Why changing or revoking a Member failed. */
export function changeError(t: Translator<"members">, status: number): string {
  switch (status) {
    case 409:
      return t("keepAdmin");
    case 404:
      return t("notFound");
    default:
      return t("changeFailed");
  }
}
