"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { apiFetch } from "../auth";

const REFRESH_MS = 30_000;

/** Top banner on Job routes when the LLM circuit breaker is open (FR-C2.3). */
export function DegradedBanner() {
  const [degraded, setDegraded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const response = await apiFetch("/api/ai/status");
        if (!cancelled && response.ok) {
          const data = (await response.json()) as { degraded?: boolean };
          setDegraded(Boolean(data.degraded));
        }
      } catch {
        // Network failures leave the current indicator unchanged.
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return <DegradedAlert degraded={degraded} />;
}

export function DegradedAlert({ degraded }: { degraded: boolean }) {
  const t = useTranslations("ai");
  if (!degraded) return null;

  return (
    <div
      role="alert"
      className="border-b border-l-4 border-accent-pink bg-surface-canvas-light px-6 py-4 text-ink-deep"
    >
      <p className="font-semibold">{t("degradedTitle")}</p>
      <p className="mt-1 text-sm">{t("degradedBody")}</p>
    </div>
  );
}
