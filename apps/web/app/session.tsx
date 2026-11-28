"use client";

import { type ReactNode, createContext, useContext, useEffect, useState } from "react";

import { apiFetch } from "./auth";
import { ROLES, type Role } from "./settings/members/members";

export type Me = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
};

export type SessionState = {
  user: Me | null;
  loading: boolean;
  offline: boolean;
};

const SessionContext = createContext<SessionState | null>(null);

function isRole(value: string): value is Role {
  return ROLES.includes(value as Role);
}

/** Shared Workspace session provider: fetches /api/auth/me once for AppShell, banners, and pages. */
export function SessionProvider({
  children,
  initialState,
}: {
  children: ReactNode;
  initialState?: SessionState;
}) {
  const [fetched, setFetched] = useState<SessionState>(
    () => initialState ?? { user: null, loading: true, offline: false },
  );
  const state = initialState ?? fetched;

  useEffect(() => {
    if (initialState) return;
    let cancelled = false;
    apiFetch("/api/auth/me").then(
      async (response) => {
        if (cancelled) return;
        if (!response.ok) {
          window.location.replace("/login");
          return;
        }
        const data = (await response.json()) as {
          id: string;
          email: string;
          full_name: string;
          role: string;
        };
        if (cancelled) return;
        if (!isRole(data.role)) {
          window.location.replace("/login");
          return;
        }
        setFetched({
          user: {
            id: data.id,
            email: data.email,
            full_name: data.full_name,
            role: data.role,
          },
          loading: false,
          offline: false,
        });
      },
      () => {
        if (!cancelled) setFetched({ user: null, loading: false, offline: true });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [initialState]);

  return <SessionContext.Provider value={state}>{children}</SessionContext.Provider>;
}

/** Read the shared Workspace session state inside AppShell or a Workspace page. */
export function useSession(): SessionState {
  return useContext(SessionContext) ?? { user: null, loading: true, offline: false };
}

/** The signed-in user's role once known, shared via SessionProvider without duplicate /me calls. */
export function useRole(): Role | null {
  const ctx = useContext(SessionContext);
  const [standaloneRole, setStandaloneRole] = useState<Role | null>(null);

  useEffect(() => {
    if (ctx !== null) return;
    let cancelled = false;
    apiFetch("/api/auth/me").then(
      async (response) => {
        if (cancelled) return;
        if (response.ok) {
          const data = (await response.json()) as { role: string };
          if (!cancelled && isRole(data.role)) setStandaloneRole(data.role);
        } else {
          window.location.replace("/login");
        }
      },
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [ctx]);

  return ctx !== null ? (ctx.user?.role ?? null) : standaloneRole;
}
