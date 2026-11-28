"use client";

import {
  Briefcase,
  ChartBar,
  type Icon,
  List,
  Megaphone,
  SignOut,
  SquaresFour,
  Users,
  X,
} from "@phosphor-icons/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { logout } from "./auth";
import { Badge } from "./badge";
import { BudgetBanner } from "./budget-banner";
import { DegradedBanner } from "./jobs/degraded-banner";
import { LocaleSwitch } from "./locale-switch";
import { SessionProvider, type SessionState, useSession } from "./session";
import { ROLE_NAMES, type Role } from "./settings/members/members";

export type NavItemId = "overview" | "jobs" | "usage" | "members" | "channels";

type NavItemDef = {
  id: NavItemId;
  href: string;
  icon: Icon;
  active: (pathname: string) => boolean;
  allowed: (role: Role | null) => boolean;
};

const NAV_ITEMS: readonly NavItemDef[] = [
  {
    id: "overview",
    href: "/",
    icon: SquaresFour,
    active: (pathname) => pathname === "/",
    allowed: () => true,
  },
  {
    id: "jobs",
    href: "/jobs",
    icon: Briefcase,
    active: (pathname) => pathname === "/jobs" || pathname.startsWith("/jobs/"),
    allowed: () => true,
  },
  {
    id: "usage",
    href: "/settings/usage",
    icon: ChartBar,
    active: (pathname) => pathname === "/settings/usage" || pathname.startsWith("/settings/usage/"),
    allowed: (role) => role === "COMPANY_ADMIN" || role === "RECRUITER",
  },
  {
    id: "members",
    href: "/settings/members",
    icon: Users,
    active: (pathname) =>
      pathname === "/settings/members" || pathname.startsWith("/settings/members/"),
    allowed: (role) => role === "COMPANY_ADMIN",
  },
  {
    id: "channels",
    href: "/settings/channels",
    icon: Megaphone,
    active: (pathname) =>
      pathname === "/settings/channels" || pathname.startsWith("/settings/channels/"),
    allowed: (role) => role === "COMPANY_ADMIN",
  },
];

/** Public and auth routes render without the Workspace sidebar or /api/auth/me calls. */
export function isPublicRoute(pathname: string | null): boolean {
  if (!pathname) return false;
  return (
    pathname === "/login" ||
    pathname === "/apply" ||
    pathname.startsWith("/apply/") ||
    pathname === "/invitations" ||
    pathname.startsWith("/invitations/")
  );
}

export function visibleNavItems(role: Role | null): readonly NavItemDef[] {
  return NAV_ITEMS.filter((item) => item.allowed(role));
}

function sectionKeyForPath(pathname: string): NavItemId {
  const match = NAV_ITEMS.find((item) => item.id !== "overview" && item.active(pathname));
  return match ? match.id : "overview";
}

function SidebarNavContent({
  pathname,
  role,
  onNavigate,
  onClose,
  closeLabel,
}: {
  pathname: string;
  role: Role | null;
  onNavigate?: () => void;
  onClose?: () => void;
  closeLabel?: string;
}) {
  const t = useTranslations("nav");
  const items = visibleNavItems(role);

  return (
    <>
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-hairline-violet px-4">
        <Link
          href="/"
          onClick={onNavigate}
          className="heading-display text-lg font-bold tracking-[0.2px] text-on-primary"
        >
          Smart ATS
        </Link>
        {onClose && closeLabel && (
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-on-dark-muted hover:bg-on-dark-faint hover:text-on-primary active:scale-[0.98] motion-reduce:active:scale-100"
          >
            <X size={20} weight="regular" aria-hidden="true" />
          </button>
        )}
      </div>
      <nav aria-label={t("ariaLabel")} className="flex flex-1 flex-col gap-1 p-3">
        {items.map((item) => {
          const active = item.active(pathname);
          const ItemIcon = item.icon;
          return (
            <Link
              key={item.id}
              href={item.href}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
              className={`flex min-h-11 items-center gap-3 rounded-md px-3 text-sm transition-colors motion-reduce:transition-none ${
                active
                  ? "bg-on-dark-faint font-semibold text-on-primary"
                  : "font-medium text-on-dark-muted hover:bg-on-dark-faint hover:text-on-primary"
              }`}
            >
              <ItemIcon size={18} weight="regular" aria-hidden="true" className="shrink-0" />
              <span className="truncate">{t(item.id)}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

export type AppShellViewProps = {
  pathname: string;
  session: SessionState;
  drawerOpen: boolean;
  onOpenDrawer: () => void;
  onCloseDrawer: () => void;
  onLogout: () => void;
  banners?: ReactNode;
  children: ReactNode;
};

/** Presentational App Shell supporting both public minimal header and Workspace console chrome. */
export function AppShellView({
  pathname,
  session,
  drawerOpen,
  onOpenDrawer,
  onCloseDrawer,
  onLogout,
  banners,
  children,
}: AppShellViewProps) {
  const tNav = useTranslations("nav");
  const tSession = useTranslations("session");

  if (isPublicRoute(pathname)) {
    return (
      <div className="flex min-h-[100dvh] flex-1 flex-col bg-surface-canvas-light text-ink-deep">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-hairline-cloud bg-surface-canvas-light px-4 sm:px-6">
          <span className="heading-display text-lg font-bold tracking-[0.2px] text-ink-deep">
            Smart ATS
          </span>
          <LocaleSwitch />
        </header>
        {children}
      </div>
    );
  }

  const sectionTitle = tNav(sectionKeyForPath(pathname));
  const role = session.user?.role ?? null;

  return (
    <div className="flex min-h-[100dvh] flex-1 bg-surface-canvas-light text-ink-deep">
      {/* Desktop fixed left sidebar (>= 992px per DESIGN.md Laptop breakpoint) */}
      <aside className="hidden border-r border-hairline-violet bg-surface-night text-on-primary min-[992px]:sticky min-[992px]:top-0 min-[992px]:flex min-[992px]:h-[100dvh] min-[992px]:w-60 min-[992px]:shrink-0 min-[992px]:flex-col">
        <SidebarNavContent pathname={pathname} role={role} />
      </aside>

      {/* Mobile & Tablet off-canvas drawer (< 992px): z-40 backdrop, z-50 panel */}
      {drawerOpen && (
        <div
          aria-hidden="true"
          onClick={onCloseDrawer}
          className="fixed inset-0 z-40 bg-primary/60 transition-opacity duration-200 motion-reduce:transition-none min-[992px]:hidden"
        />
      )}
      <aside
        id="workspace-drawer"
        aria-label={tNav("ariaLabel")}
        aria-hidden={!drawerOpen}
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-hairline-violet bg-surface-night text-on-primary transition-transform duration-200 ease-out motion-reduce:transition-none min-[992px]:hidden ${
          drawerOpen ? "translate-x-0" : "pointer-events-none -translate-x-full"
        }`}
      >
        <SidebarNavContent
          pathname={pathname}
          role={role}
          onNavigate={onCloseDrawer}
          onClose={onCloseDrawer}
          closeLabel={tNav("closeMenu")}
        />
      </aside>

      {/* Main Workspace column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-hairline-cloud bg-surface-canvas-light px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={onOpenDrawer}
              aria-label={tNav("openMenu")}
              aria-expanded={drawerOpen}
              aria-controls="workspace-drawer"
              className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md text-ink-deep active:scale-[0.98] active:bg-surface-press-light motion-reduce:active:scale-100 min-[992px]:hidden"
            >
              <List size={20} weight="regular" aria-hidden="true" />
            </button>
            <span className="truncate text-sm font-semibold text-ink-deep">{sectionTitle}</span>
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <LocaleSwitch />
            {session.loading ? (
              <div
                aria-busy="true"
                className="h-7 w-28 animate-pulse rounded-xs bg-hairline-cloud motion-reduce:animate-none"
              />
            ) : (
              session.user && (
                <>
                  <div className="flex items-center gap-2 border-l border-hairline-cloud pl-3">
                    <span className="hidden max-w-40 truncate text-sm font-medium text-ink-deep sm:inline">
                      {session.user.full_name}
                    </span>
                    <Badge>{ROLE_NAMES[session.user.role]}</Badge>
                  </div>
                  <button
                    type="button"
                    onClick={onLogout}
                    aria-label={tSession("logout")}
                    className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md px-2.5 text-sm/[1.29] font-medium tracking-[0.2px] whitespace-nowrap text-ink-deep uppercase transition-transform duration-100 active:scale-[0.98] active:bg-surface-press-light motion-reduce:transition-none motion-reduce:active:scale-100"
                  >
                    <SignOut size={18} weight="regular" aria-hidden="true" />
                    <span className="hidden md:inline">{tSession("logout")}</span>
                  </button>
                </>
              )
            )}
          </div>
        </header>

        {session.offline && (
          <div
            role="alert"
            className="border-b border-l-4 border-b-hairline-cloud border-l-accent-pink bg-surface-canvas-light px-6 py-3 text-sm text-ink-deep"
          >
            {tSession("offline")}
          </div>
        )}
        {banners}
        {children}
      </div>
    </div>
  );
}

function WorkspaceChrome({ pathname, children }: { pathname: string; children: ReactNode }) {
  const session = useSession();
  // Store the pathname on which the drawer was opened so route changes close it automatically.
  const [openedAtPath, setOpenedAtPath] = useState<string | null>(null);
  const drawerOpen = openedAtPath !== null && openedAtPath === pathname;

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenedAtPath(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [drawerOpen]);

  async function handleLogout() {
    await logout();
    window.location.replace("/login");
  }

  return (
    <AppShellView
      pathname={pathname}
      session={session}
      drawerOpen={drawerOpen}
      onOpenDrawer={() => setOpenedAtPath(pathname)}
      onCloseDrawer={() => setOpenedAtPath(null)}
      onLogout={handleLogout}
      banners={
        <>
          <DegradedBanner />
          <BudgetBanner />
        </>
      }
    >
      {children}
    </AppShellView>
  );
}

/** Root application shell: minimal header on public routes, shared session + console on Workspace. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";

  if (isPublicRoute(pathname)) {
    return (
      <AppShellView
        pathname={pathname}
        session={{ user: null, loading: false, offline: false }}
        drawerOpen={false}
        onOpenDrawer={() => {}}
        onCloseDrawer={() => {}}
        onLogout={() => {}}
      >
        {children}
      </AppShellView>
    );
  }

  return (
    <SessionProvider>
      <WorkspaceChrome pathname={pathname}>{children}</WorkspaceChrome>
    </SessionProvider>
  );
}
