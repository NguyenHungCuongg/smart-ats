"use client";

import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import {
  EMAIL_STATUS_NAMES,
  type Members,
  ROLE_NAMES,
  ROLES,
  type Role,
  changeError,
  inviteError,
} from "./members";

// Secondary actions read as link-on-light: one filled button per page (DESIGN.md).
const LINK_BUTTON = "font-medium underline";

const dateTime = (iso: string) => new Date(iso).toLocaleString("vi-VN");

/** Company Admins invite, re-role and revoke the Members of their Workspace (FR-C1.2). */
export default function MembersPage() {
  const [data, setData] = useState<Members | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Bumped to reload the list.
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);

  useEffect(() => {
    apiFetch("/api/members").then(async (response) => {
      if (response.status === 401) window.location.replace("/login");
      else if (response.status === 403) setForbidden(true);
      else if (response.ok) setData(await response.json());
    });
  }, [version]);

  async function change(path: string, init: RequestInit, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    const response = await apiFetch(path, init);
    setMessage(response.ok ? null : changeError(response.status));
    reload();
  }

  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <p role="alert">Chỉ Company Admin quản lý thành viên của Workspace.</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <h1 className="heading-display text-3xl font-semibold">Thành viên</h1>
        <InviteForm onInvited={reload} />
        {message && (
          <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
            {message}
          </p>
        )}
        {!data ? (
          <div aria-busy="true" aria-label="Đang tải thành viên" className="flex flex-col gap-3">
            <div className="h-8 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">
                Lời mời đang chờ ({data.invitations.length})
              </h2>
              {data.invitations.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-hairline-cloud">
                        <th className="py-2 font-medium">Email</th>
                        <th className="py-2 font-medium">Vai trò</th>
                        <th className="py-2 font-medium">Email mời</th>
                        <th className="py-2 font-medium">Hết hạn</th>
                        <th className="py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {data.invitations.map((i) => (
                        <tr key={i.id} className="border-b border-hairline-cloud">
                          <td className="py-2 pr-3">{i.email}</td>
                          <td className="py-2 pr-3">{ROLE_NAMES[i.role]}</td>
                          <td className="py-2 pr-3">
                            <Badge>{EMAIL_STATUS_NAMES[i.email_status]}</Badge>
                          </td>
                          <td className="py-2 pr-3">{dateTime(i.expires_at)}</td>
                          <td className="py-2 text-right">
                            <button
                              type="button"
                              className={LINK_BUTTON}
                              onClick={() =>
                                change(`/api/invitations/${i.id}`, { method: "DELETE" })
                              }
                            >
                              Hủy lời mời
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">Thành viên ({data.members.length})</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-hairline-cloud">
                      <th className="py-2 font-medium">Họ tên</th>
                      <th className="py-2 font-medium">Email</th>
                      <th className="py-2 font-medium">Vai trò</th>
                      <th className="py-2 font-medium">Trạng thái</th>
                      <th className="py-2 font-medium">Đăng nhập cuối</th>
                      <th className="py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {data.members.map((m) => (
                      <tr key={m.id} className="border-b border-hairline-cloud">
                        <td className="py-2 pr-3">{m.full_name}</td>
                        <td className="py-2 pr-3">{m.email}</td>
                        <td className="py-2 pr-3">
                          <select
                            aria-label={`Vai trò của ${m.full_name}`}
                            value={m.role}
                            disabled={!m.is_active}
                            onChange={(e) =>
                              change(`/api/members/${m.id}`, {
                                method: "PATCH",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ role: e.target.value }),
                              })
                            }
                            className="text-input"
                          >
                            {ROLES.map((role) => (
                              <option key={role} value={role}>
                                {ROLE_NAMES[role]}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2 pr-3">
                          <Badge>{m.is_active ? "Đang hoạt động" : "Đã thu hồi"}</Badge>
                        </td>
                        <td className="py-2 pr-3">
                          {m.last_login_at ? dateTime(m.last_login_at) : "Chưa đăng nhập"}
                        </td>
                        <td className="py-2 text-right">
                          {m.is_active && (
                            <button
                              type="button"
                              className={LINK_BUTTON}
                              onClick={() =>
                                change(
                                  `/api/members/${m.id}`,
                                  { method: "DELETE" },
                                  `Thu hồi quyền truy cập của ${m.full_name}?`,
                                )
                              }
                            >
                              Thu hồi
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-sm">
                Đổi vai trò có hiệu lực khi thành viên làm mới phiên. Thu hồi đăng xuất họ khỏi mọi
                thiết bị khi phiên hiện tại hết hạn.
              </p>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function InviteForm({ onInvited }: { onInvited: () => void }) {
  const [role, setRole] = useState<Role>("RECRUITER");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    const response = await apiFetch("/api/invitations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: new FormData(form).get("email"), role }),
    });
    setPending(false);
    setError(response.ok ? null : inviteError(response.status));
    if (response.ok) {
      form.reset();
      onInvited();
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">Mời thành viên</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-60 flex-1 flex-col gap-1">
          <span className="font-medium">Email</span>
          <input name="email" type="email" required maxLength={254} className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Vai trò</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="text-input"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_NAMES[r]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={pending} className="button-primary">
          Gửi lời mời
        </button>
      </div>
      <p className="text-sm">
        Lời mời gửi qua email, dùng một lần. Mời lại cùng email sẽ hủy lời mời cũ.
      </p>
      {error && (
        <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
          {error}
        </p>
      )}
    </form>
  );
}
