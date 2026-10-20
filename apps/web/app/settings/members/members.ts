// The Members API (FR-C1.2) as /settings/members shows it.

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

export const EMAIL_STATUS_NAMES: Record<EmailStatus, string> = {
  QUEUED: "Đang gửi",
  SENT: "Đã gửi",
  // A failed email's token is gone: only a new invitation sends a working link.
  FAILED: "Gửi lỗi, hãy mời lại",
};

/** Why POST /api/invitations failed. */
export function inviteError(status: number): string {
  switch (status) {
    case 409:
      return "Email này đã là thành viên của Workspace.";
    case 422:
      return "Email không hợp lệ.";
    default:
      return "Không gửi được lời mời. Vui lòng thử lại.";
  }
}

/** Why changing or revoking a Member failed. */
export function changeError(status: number): string {
  switch (status) {
    case 409:
      return "Workspace cần ít nhất một Company Admin, và bạn không thể tự thu hồi chính mình.";
    case 404:
      return "Không tìm thấy thành viên hoặc lời mời này.";
    default:
      return "Không lưu được thay đổi. Vui lòng thử lại.";
  }
}
