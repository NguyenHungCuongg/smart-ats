"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

type SettingsTab = "members" | "channels";

/** Shared tab bar for Company Admin settings pages (DESIGN.md). */
export function SettingsNav({ active }: { active: SettingsTab }) {
  const tMembers = useTranslations("members");
  const tChannels = useTranslations("channels");
  const tabs: { id: SettingsTab; href: string; label: string }[] = [
    { id: "members", href: "/settings/members", label: tMembers("title") },
    { id: "channels", href: "/settings/channels", label: tChannels("title") },
  ];

  return (
    <nav className="flex gap-4 border-b border-hairline-cloud pb-2 text-sm">
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
