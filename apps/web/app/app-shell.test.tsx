import { NextIntlClientProvider } from "next-intl";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test, vi } from "vitest";

import type { Locale } from "../i18n/locale";
import { CATALOGS } from "../i18n/messages";
import { AppShellView, isPublicRoute, visibleNavItems } from "./app-shell";
import { SessionProvider, useRole, useSession } from "./session";
import type { Role } from "./settings/members/members";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: () => {} }),
  usePathname: () => "/",
}));

function renderShell(
  locale: Locale,
  pathname: string,
  role: Role | null,
  options?: { drawerOpen?: boolean; offline?: boolean; loading?: boolean },
) {
  const session = options?.loading
    ? { user: null, loading: true, offline: false }
    : options?.offline
      ? { user: null, loading: false, offline: true }
      : role
        ? {
            user: {
              id: "u-1",
              email: "user@example.com",
              full_name: "Trần Minh Quân",
              role,
            },
            loading: false,
            offline: false,
          }
        : { user: null, loading: false, offline: false };

  return renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={CATALOGS[locale]}>
      <AppShellView
        pathname={pathname}
        session={session}
        drawerOpen={options?.drawerOpen ?? false}
        onOpenDrawer={() => {}}
        onCloseDrawer={() => {}}
        onLogout={() => {}}
      >
        <div>Page Content</div>
      </AppShellView>
    </NextIntlClientProvider>,
  );
}

test("classifies public and auth routes vs Workspace routes", () => {
  expect(isPublicRoute("/login")).toBe(true);
  expect(isPublicRoute("/apply/senior-backend-123")).toBe(true);
  expect(isPublicRoute("/invitations/accept")).toBe(true);

  expect(isPublicRoute("/")).toBe(false);
  expect(isPublicRoute("/jobs")).toBe(false);
  expect(isPublicRoute("/jobs/new")).toBe(false);
  expect(isPublicRoute("/settings/members")).toBe(false);
  expect(isPublicRoute("/settings/usage")).toBe(false);
  expect(isPublicRoute("/settings/channels")).toBe(false);
});

test("hides Workspace sidebar and user chrome on public routes", () => {
  for (const route of ["/login", "/apply/backend-slug", "/invitations/accept"]) {
    const html = renderShell("vi", route, "COMPANY_ADMIN");
    expect(html).toContain("Smart ATS");
    expect(html).toContain("Page Content");
    expect(html).not.toContain('id="workspace-drawer"');
    expect(html).not.toContain('href="/settings/members"');
    expect(html).not.toContain("Trần Minh Quân");
  }
});

test("shows role-gated navigation destinations for COMPANY_ADMIN, RECRUITER, and REVIEWER", () => {
  expect(visibleNavItems("COMPANY_ADMIN").map((i) => i.href)).toEqual([
    "/",
    "/jobs",
    "/settings/usage",
    "/settings/members",
    "/settings/channels",
  ]);
  expect(visibleNavItems("RECRUITER").map((i) => i.href)).toEqual([
    "/",
    "/jobs",
    "/settings/usage",
  ]);
  expect(visibleNavItems("REVIEWER").map((i) => i.href)).toEqual(["/", "/jobs"]);

  const adminVi = renderShell("vi", "/settings/members", "COMPANY_ADMIN");
  expect(adminVi).toContain("Trần Minh Quân");
  expect(adminVi).toContain("Company Admin");
  expect(adminVi).toContain('href="/settings/usage"');
  expect(adminVi).toContain('href="/settings/members"');
  expect(adminVi).toContain('href="/settings/channels"');
  expect(adminVi).toContain('aria-current="page"');
  // Sidebar contains noun destinations only, never a duplicate Create Job CTA
  expect(adminVi).not.toContain('href="/jobs/new"');

  const recruiterEn = renderShell("en", "/jobs", "RECRUITER");
  expect(recruiterEn).toContain("Recruiter");
  expect(recruiterEn).toContain('href="/settings/usage"');
  expect(recruiterEn).not.toContain('href="/settings/members"');
  expect(recruiterEn).not.toContain('href="/settings/channels"');

  const reviewerVi = renderShell("vi", "/", "REVIEWER");
  expect(reviewerVi).toContain("Reviewer");
  expect(reviewerVi).toContain('href="/"');
  expect(reviewerVi).toContain('href="/jobs"');
  expect(reviewerVi).not.toContain('href="/settings/usage"');
  expect(reviewerVi).not.toContain('href="/settings/members"');
  expect(reviewerVi).not.toContain('href="/settings/channels"');
});

test("renders mobile drawer backdrop at z-40 and panel at z-50 when open", () => {
  const closedHtml = renderShell("en", "/", "RECRUITER", { drawerOpen: false });
  expect(closedHtml).not.toContain("z-40");
  expect(closedHtml).toContain("-translate-x-full");

  const openHtml = renderShell("en", "/", "RECRUITER", { drawerOpen: true });
  expect(openHtml).toContain("z-40");
  expect(openHtml).toContain("z-50");
  expect(openHtml).toContain("translate-x-0");
});

test("shares session context across consumers without duplicate /api/auth/me calls", () => {
  function ConsumerPair() {
    const session = useSession();
    const role = useRole();
    return (
      <div>
        <span>{session.user?.full_name}</span>
        <span>{role}</span>
      </div>
    );
  }

  const html = renderToStaticMarkup(
    <SessionProvider
      initialState={{
        user: {
          id: "u-9",
          email: "recruiter@example.com",
          full_name: "Phạm Thu Hà",
          role: "RECRUITER",
        },
        loading: false,
        offline: false,
      }}
    >
      <ConsumerPair />
    </SessionProvider>,
  );

  expect(html).toContain("Phạm Thu Hà");
  expect(html).toContain("RECRUITER");
});
