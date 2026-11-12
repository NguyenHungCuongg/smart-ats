"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { featureLabel, formatPercent, formatUsd, type UsageSummary } from "./usage";

type UsageViewProps = {
  month: string;
  onMonthChange: (month: string) => void;
  data: UsageSummary | null;
  loading: boolean;
  error: string | null;
};

export function BudgetWarningAlert({
  summary,
  detailsHref,
}: {
  summary: UsageSummary;
  detailsHref?: string;
}) {
  const t = useTranslations("usage");
  const locale = useLocale();
  if (!summary.budget_warning) return null;

  return (
    <div role="alert" className="border-l-4 border-accent-pink bg-surface-canvas-light p-4">
      <p className="text-sm font-semibold text-ink-deep">{t("warningTitle")}</p>
      <p className="mt-1 text-sm text-ink-deep">
        {t("warningBody", {
          percent: formatPercent(locale, summary.usage_ratio),
          budget: formatUsd(locale, summary.budget_usd),
          spent: formatUsd(locale, summary.total_cost_usd),
        })}
      </p>
      {detailsHref && (
        <Link href={detailsHref} className="mt-2 inline-block text-sm font-medium underline">
          {t("viewDetails")}
        </Link>
      )}
    </div>
  );
}

export function UsageView({ month, onMonthChange, data, loading, error }: UsageViewProps) {
  const t = useTranslations("usage");
  const locale = useLocale();
  const fillPercent = data ? Math.min(100, Math.round(data.usage_ratio * 100)) : 0;

  const metrics = data
    ? [
        { label: t("spentLabel"), value: formatUsd(locale, data.total_cost_usd) },
        { label: t("budgetLabel"), value: formatUsd(locale, data.budget_usd) },
        { label: t("usageRateLabel"), value: formatPercent(locale, data.usage_ratio) },
        { label: t("callsLabel"), value: data.total_calls.toLocaleString(locale) },
      ]
    : [];

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
          {data && (
            <p className="text-sm text-accent-violet-mid">
              {data.scope === "TENANT" ? t("scopeTenant") : t("scopeUser")}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-ink-deep">
            <span className="font-medium">{t("month")}</span>
            <input
              type="month"
              value={month}
              onChange={(event) => onMonthChange(event.target.value)}
              className="w-fit text-input"
            />
          </label>
          <Link href="/" className="text-sm underline">
            {t("back")}
          </Link>
        </div>
      </div>

      {data && <BudgetWarningAlert summary={data} />}

      {error && (
        <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm text-ink-deep">
          {error}
        </p>
      )}

      {loading && (
        <div className="flex flex-col gap-2" aria-label={t("loading")}>
          <div className="h-20 rounded-xl bg-hairline-cloud" />
          <div className="h-32 rounded-xl bg-hairline-cloud" />
        </div>
      )}

      {!loading && data && (
        <>
          <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {metrics.map((metric) => (
              <div
                key={metric.label}
                className="rounded-xl border border-hairline-cloud bg-surface-canvas-light p-4"
              >
                <p className="text-xs font-medium tracking-[0.2px] text-accent-violet-mid uppercase">
                  {metric.label}
                </p>
                <p className="mt-1 font-mono text-2xl font-semibold text-ink-deep tabular-nums">
                  {metric.value}
                </p>
              </div>
            ))}
          </section>

          <div className="h-2 w-full overflow-hidden rounded-full bg-hairline-cloud">
            <div
              className={`h-full rounded-full ${
                data.usage_ratio >= 0.8 ? "bg-accent-pink" : "bg-primary"
              }`}
              style={{ width: `${fillPercent}%` }}
            />
          </div>

          {data.features.length === 0 ? (
            <p className="text-sm text-accent-violet-mid">{t("empty")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-hairline-cloud text-ink-deep">
                    <th className="py-2 font-medium">{t("feature")}</th>
                    <th className="py-2 text-right font-medium">{t("calls")}</th>
                    <th className="py-2 text-right font-medium">{t("cost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.features.map((row) => (
                    <tr key={row.feature} className="border-b border-hairline-cloud">
                      <td className="py-2">
                        <span className="font-medium text-ink-deep">
                          {featureLabel(t, row.feature)}
                        </span>{" "}
                        <span className="font-mono text-xs text-accent-violet-mid">
                          {row.feature}
                        </span>
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {row.calls.toLocaleString(locale)}
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {formatUsd(locale, row.cost_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
