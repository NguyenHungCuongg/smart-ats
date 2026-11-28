"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useRole } from "../session";

export type SettingsTab = "usage" | "members" | "channels";

/** Shared tab bar for Workspace settings pages, including AI Usage for Company Admins. */
export function SettingsNav({ active }: { active: SettingsTab }) {
  const role = useRole();
  const tUsage = useTranslations("usage");
  const tMembers = useTranslations("members");
  const tChannels = useTranslations("channels");

  // Only Company Admins have multiple settings pages; Recruiters only access /settings/usage.
  if (active === "usage" && role !== "COMPANY_ADMIN") {
    return null;
  }

  const tabs: { id: SettingsTab; href: string; label: string }[] = [
    { id: "usage", href: "/settings/usage", label: tUsage("title") },
    { id: "members", href: "/settings/members", label: tMembers("title") },
    { id: "channels", href: "/settings/channels", label: tChannels("title") },
  ];

  return (
    <nav className="flex flex-wrap gap-4 border-b border-hairline-cloud pb-2 text-sm">
      {tabs.map((tab) =>
        tab.id === active ? (
          <span
            key={tab.id}
            aria-current="page"
            className="-mb-2 border-b-2 border-primary pb-2 font-semibold text-ink-deep"
          >
            {tab.label}
          </span>
        ) : (
          <Link key={tab.id} href={tab.href} className="text-accent-violet-mid hover:text-ink-deep">
            {tab.label}
          </Link>
        ),
      )}
    </nav>
  );
}
