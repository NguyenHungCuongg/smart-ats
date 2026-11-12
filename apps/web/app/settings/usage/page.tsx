"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { currentMonthUtc, usageError, type UsageSummary } from "./usage";
import { UsageView } from "./view";

type FetchResult = {
  month: string;
  data: UsageSummary | null;
  errorStatus: number | null;
};

export default function UsagePage() {
  const t = useTranslations("usage");
  const [month, setMonth] = useState(() => currentMonthUtc());
  const [result, setResult] = useState<FetchResult | null>(null);

  useEffect(() => {
    let cancelled = false;

    apiFetch(`/api/usage?month=${encodeURIComponent(month)}`)
      .then(async (response) => {
        if (cancelled) return;
        if (response.status === 401) {
          window.location.replace("/login");
          return;
        }
        if (!response.ok) {
          setResult({ month, data: null, errorStatus: response.status });
          return;
        }
        const summary: UsageSummary = await response.json();
        if (!cancelled) setResult({ month, data: summary, errorStatus: null });
      })
      .catch(() => {
        if (!cancelled) setResult({ month, data: null, errorStatus: 500 });
      });

    return () => {
      cancelled = true;
    };
  }, [month]);

  const loading = result === null || result.month !== month;
  const data = loading ? null : result.data;
  const errorStatus = loading ? null : result.errorStatus;

  return (
    <UsageView
      month={month}
      onMonthChange={setMonth}
      data={data}
      loading={loading}
      error={errorStatus === null ? null : usageError(t, errorStatus)}
    />
  );
}
