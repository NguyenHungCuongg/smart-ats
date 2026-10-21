"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch, logout } from "./auth";
import type { Role } from "./settings/members/members";

type Me = { email: string; full_name: string; role: string };

/** The signed-in user's role once known, for pages that show each role what it may do. */
export function useRole(): Role | null {
  const [role, setRole] = useState<Role | null>(null);
  useEffect(() => {
    apiFetch("/api/auth/me").then(async (response) => {
      if (response.ok) setRole((await response.json()).role);
      else window.location.replace("/login");
    });
  }, []);
  return role;
}

/** The signed-in user with a logout button; sends anyone signed out to /login. */
export function Session() {
  const t = useTranslations("session");
  const [me, setMe] = useState<Me | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    apiFetch("/api/auth/me").then(
      async (response) => {
        if (response.ok) setMe(await response.json());
        else window.location.replace("/login");
      },
      () => setOffline(true),
    );
  }, []);

  if (offline) return <p role="alert">{t("offline")}</p>;
  if (!me) {
    return (
      <div aria-busy="true" className="h-11 w-72 animate-pulse rounded-md bg-hairline-cloud" />
    );
  }
  return (
    <div className="flex items-center gap-3">
      <span>
        {me.full_name} ({me.email})
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          window.location.replace("/login");
        }}
        className="button-outline"
      >
        {t("logout")}
      </button>
    </div>
  );
}
