"use client";

import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { type Members, ROLE_NAMES, ROLES, type Role, changeError, inviteError } from "./members";

// Secondary actions read as link-on-light: one filled button per page (DESIGN.md).
const LINK_BUTTON = "font-medium underline";

/** Company Admins invite, re-role and revoke the Members of their Workspace (FR-C1.2). */
export default function MembersPage() {
  const t = useTranslations("members");
  const locale = useLocale();
  const [data, setData] = useState<Members | null>(null);
  const [forbidden, setForbidden] = useState(false);
  // The status of the last refused change, worded at render in the language shown.
  const [refused, setRefused] = useState<number | null>(null);
  // Bumped to reload the list.
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);
  const dateTime = (iso: string) => new Date(iso).toLocaleString(locale);

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
    setRefused(response.ok ? null : response.status);
    reload();
  }

  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <p role="alert">{t("forbidden")}</p>
      </main>
    );
  }

  return (
    <main className="flex-1">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
        <InviteForm onInvited={reload} />
        {refused !== null && (
          <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
            {changeError(t, refused)}
          </p>
        )}
        {!data ? (
          <div aria-busy="true" aria-label={t("loading")} className="flex flex-col gap-3">
            <div className="h-8 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="text-xl font-semibold">
                {t("pending", { count: data.invitations.length })}
              </h2>
              {data.invitations.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-hairline-cloud">
                        <th className="py-2 font-medium">{t("email")}</th>
                        <th className="py-2 font-medium">{t("role")}</th>
                        <th className="py-2 font-medium">{t("invitationEmail")}</th>
                        <th className="py-2 font-medium">{t("expires")}</th>
                        <th className="py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {data.invitations.map((i) => (
                        <tr key={i.id} className="border-b border-hairline-cloud">
                          <td className="py-2 pr-3">{i.email}</td>
                          <td className="py-2 pr-3">{ROLE_NAMES[i.role]}</td>
                          <td className="py-2 pr-3">
                            {/* A failed email's token is gone: only a new invitation sends a
                                working link. */}
                            <Badge>{t(`emailStatus.${i.email_status}`)}</Badge>
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
                              {t("cancelInvitation")}
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
              <h2 className="text-xl font-semibold">
                {t("membersCount", { count: data.members.length })}
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-hairline-cloud">
                      <th className="py-2 font-medium">{t("fullName")}</th>
                      <th className="py-2 font-medium">{t("email")}</th>
                      <th className="py-2 font-medium">{t("role")}</th>
                      <th className="py-2 font-medium">{t("status")}</th>
                      <th className="py-2 font-medium">{t("lastLogin")}</th>
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
                            aria-label={t("roleOf", { name: m.full_name })}
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
                          <Badge>{m.is_active ? t("active") : t("revoked")}</Badge>
                        </td>
                        <td className="py-2 pr-3">
                          {m.last_login_at ? dateTime(m.last_login_at) : t("neverLoggedIn")}
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
                                  t("confirmRevoke", { name: m.full_name }),
                                )
                              }
                            >
                              {t("revoke")}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-sm">{t("note")}</p>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function InviteForm({ onInvited }: { onInvited: () => void }) {
  const t = useTranslations("members");
  const [role, setRole] = useState<Role>("RECRUITER");
  const [refused, setRefused] = useState<number | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    // The API writes the email in the language of this request's NEXT_LOCALE cookie.
    const response = await apiFetch("/api/invitations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: new FormData(form).get("email"), role }),
    });
    setPending(false);
    setRefused(response.ok ? null : response.status);
    if (response.ok) {
      form.reset();
      onInvited();
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold">{t("inviteTitle")}</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-60 flex-1 flex-col gap-1">
          <span className="font-medium">{t("email")}</span>
          <input name="email" type="email" required maxLength={254} className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("role")}</span>
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
          {t("send")}
        </button>
      </div>
      <p className="text-sm">{t("inviteNote")}</p>
      {refused !== null && (
        <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
          {inviteError(t, refused)}
        </p>
      )}
    </form>
  );
}
