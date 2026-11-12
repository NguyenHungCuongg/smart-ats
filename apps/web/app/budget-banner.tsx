"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch } from "./auth";
import { useRole } from "./session";
import type { UsageSummary } from "./settings/usage/usage";
import { BudgetWarningAlert } from "./settings/usage/view";

function isPublicOrUsageRoute(pathname: string | null): boolean {
  if (!pathname) return true;
  return (
    pathname === "/login" ||
    pathname.startsWith("/apply") ||
    pathname.startsWith("/invitations") ||
    pathname === "/settings/usage"
  );
}

function AdminBudgetMonitor() {
  const role = useRole();
  const [summary, setSummary] = useState<UsageSummary | null>(null);

  useEffect(() => {
    if (role !== "COMPANY_ADMIN") return;
    let cancelled = false;
    apiFetch("/api/usage")
      .then(async (response) => {
        if (!response.ok || cancelled) return;
        const data: UsageSummary = await response.json();
        if (!cancelled) setSummary(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [role]);

  if (!summary?.budget_warning) return null;
  return (
    <div className="mx-auto w-full max-w-4xl px-6 pt-2">
      <BudgetWarningAlert summary={summary} detailsHref="/settings/usage" />
    </div>
  );
}

/** Shows the 80% monthly AI budget warning to Company Admins across workspace pages. */
export function BudgetBanner() {
  const pathname = usePathname();
  if (isPublicOrUsageRoute(pathname)) return null;
  return <AdminBudgetMonitor />;
}
