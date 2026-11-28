"use client";

import {
  ArrowClockwise,
  ArrowRight,
  Briefcase,
  ChartBar,
  CheckCircle,
  FileArrowUp,
  FileText,
  Plus,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "./auth";
import { Badge } from "./badge";
import type { DashboardSummary } from "./dashboard";
import { actorBadge, formatActivity } from "./jobs/activity";
import { STAGES } from "./jobs/pipeline";
import { useRole } from "./session";
import type { Role } from "./settings/members/members";
import { formatPercent, formatUsd, type UsageSummary } from "./settings/usage/usage";

export type DashboardViewProps = {
  role: Role | null;
  data: DashboardSummary | null;
  usage: UsageSummary | null;
  usageLoading?: boolean;
  loading: boolean;
  error: boolean;
  onRetry?: () => void;
};

function DashboardSkeleton({ label }: { label: string }) {
  return (
    <div aria-busy="true" aria-label={label} className="flex flex-col gap-8">
      <div className="grid grid-cols-1 gap-6 border-y border-hairline-cloud py-6 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex flex-col gap-2 sm:border-r sm:border-hairline-cloud sm:pr-6">
            <div className="h-4 w-28 animate-pulse rounded-xs bg-hairline-cloud motion-reduce:animate-none" />
            <div className="h-9 w-16 animate-pulse rounded-xs bg-hairline-cloud motion-reduce:animate-none" />
            <div className="h-3 w-36 animate-pulse rounded-xs bg-hairline-cloud motion-reduce:animate-none" />
          </div>
        ))}
        <div className="h-32 animate-pulse rounded-xl border border-hairline-violet bg-surface-night motion-reduce:animate-none" />
      </div>
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
        <div className="h-64 animate-pulse rounded-md bg-hairline-cloud motion-reduce:animate-none lg:col-span-7" />
        <div className="h-64 animate-pulse rounded-md bg-hairline-cloud motion-reduce:animate-none lg:col-span-5" />
      </div>
    </div>
  );
}

/** Presentational Workspace console Dashboard with high-density hairline hierarchy (DESIGN.md). */
export function DashboardView({
  role,
  data,
  usage,
  usageLoading = false,
  loading,
  error,
  onRetry,
}: DashboardViewProps) {
  const t = useTranslations("dashboard");
  const tActivity = useTranslations("activity");
  const statusName = useTranslations("lifecycle.status");
  const jobField = useTranslations("job");
  const stageName = useTranslations("pipeline.stage");
  const sourceName = useTranslations("pipeline.source");
  const locale = useLocale();

  const canManageJobs = role === "COMPANY_ADMIN" || role === "RECRUITER";
  const hasJobs = !loading && !error && data !== null && data.total_jobs > 0;
  // Never show two Create Job CTAs on one screen: hide header CTA during Empty Onboarding.
  const showHeaderCreateCta = canManageJobs && hasJobs;
  const translators = { t: tActivity, statusName, jobField, stageName, sourceName, locale };

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-6 sm:px-6 lg:py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="heading-display text-[30px]/[1.2] font-semibold text-ink-deep">
          {t("title")}
        </h1>
        {showHeaderCreateCta && (
          <Link
            href="/jobs/new"
            className="inline-flex min-h-11 button-primary items-center gap-2 whitespace-nowrap"
          >
            <Plus size={16} weight="regular" aria-hidden="true" />
            <span>{t("createJob")}</span>
          </Link>
        )}
      </header>

      {loading ? (
        <DashboardSkeleton label={t("loading")} />
      ) : error || !data ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-4 border-l-4 border-accent-pink bg-surface-canvas-light p-4"
        >
          <div className="flex items-center gap-2.5 text-sm font-medium text-ink-deep">
            <WarningCircle size={20} weight="regular" aria-hidden="true" className="shrink-0" />
            <span>{t("loadFailed")}</span>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex min-h-11 button-outline items-center gap-2 whitespace-nowrap"
            >
              <ArrowClockwise size={16} weight="regular" aria-hidden="true" />
              <span>{t("retry")}</span>
            </button>
          )}
        </div>
      ) : data.total_jobs === 0 ? (
        canManageJobs ? (
          <section className="flex flex-col gap-6 rounded-xl border border-hairline-cloud bg-surface-canvas-light p-6 sm:p-8">
            <div className="flex flex-col gap-2">
              <h2 className="heading-display text-2xl font-semibold text-ink-deep">
                {t("onboarding.title")}
              </h2>
              <p className="max-w-[65ch] text-sm text-accent-violet-mid">
                {t("onboarding.subtitle")}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-6 border-t border-hairline-cloud pt-6 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 font-semibold text-ink-deep">
                  <FileArrowUp size={20} weight="regular" aria-hidden="true" />
                  <span>{t("onboarding.uploadJdTitle")}</span>
                </div>
                <p className="text-sm text-accent-violet-mid">{t("onboarding.uploadJdDesc")}</p>
              </div>
              <div className="flex flex-col gap-2 md:border-l md:border-hairline-cloud md:pl-6">
                <div className="flex items-center gap-2 font-semibold text-ink-deep">
                  <UsersThree size={20} weight="regular" aria-hidden="true" />
                  <span>{t("onboarding.addCvsTitle")}</span>
                </div>
                <p className="text-sm text-accent-violet-mid">{t("onboarding.addCvsDesc")}</p>
              </div>
              <div className="flex flex-col gap-2 md:border-l md:border-hairline-cloud md:pl-6">
                <div className="flex items-center gap-2 font-semibold text-ink-deep">
                  <ChartBar size={20} weight="regular" aria-hidden="true" />
                  <span>{t("onboarding.scoreTitle")}</span>
                </div>
                <p className="text-sm text-accent-violet-mid">{t("onboarding.scoreDesc")}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 pt-1">
              <Link
                href="/jobs/new"
                className="inline-flex min-h-11 button-primary items-center gap-2 whitespace-nowrap"
              >
                <Plus size={16} weight="regular" aria-hidden="true" />
                <span>{t("createJob")}</span>
              </Link>
              <Link href="/jobs" className="inline-flex min-h-11 items-center text-sm underline">
                {t("recentJobs.viewAll")}
              </Link>
            </div>
          </section>
        ) : (
          <section className="flex flex-col gap-2 rounded-xl border border-hairline-cloud bg-surface-canvas-light p-6 sm:p-8">
            <div className="flex items-center gap-2.5 text-ink-deep">
              <Briefcase size={22} weight="regular" aria-hidden="true" />
              <h2 className="heading-display text-xl font-semibold">{t("reviewerEmptyTitle")}</h2>
            </div>
            <p className="max-w-[65ch] text-sm text-accent-violet-mid">{t("reviewerEmptyDesc")}</p>
          </section>
        )
      ) : (
        <>
          {/* 3 hairline-divided metrics on light surface + 1 permanently dark Featured Card */}
          <section
            aria-label={t("metricsAria")}
            className="grid grid-cols-1 gap-6 border-y border-hairline-cloud py-6 sm:grid-cols-2 lg:grid-cols-4"
          >
            <div className="flex flex-col justify-between gap-2 border-b border-hairline-cloud pb-4 sm:border-r sm:border-b-0 sm:pr-6 sm:pb-0">
              <p className="text-sm font-medium text-accent-violet-mid">
                {t("metrics.publishedJobs")}
              </p>
              <p className="font-mono text-3xl font-semibold text-ink-deep tabular-nums">
                {data.jobs_by_status.PUBLISHED.toLocaleString(locale)}
              </p>
              <p className="font-mono text-xs text-accent-violet-mid tabular-nums">
                {t("metrics.publishedJobsSub", {
                  draft: data.jobs_by_status.DRAFT.toLocaleString(locale),
                  total: data.total_jobs.toLocaleString(locale),
                })}
              </p>
            </div>

            <div className="flex flex-col justify-between gap-2 border-b border-hairline-cloud pb-4 sm:border-b-0 sm:pb-0 lg:border-r lg:border-hairline-cloud lg:pr-6">
              <p className="text-sm font-medium text-accent-violet-mid">
                {t("metrics.totalApplications")}
              </p>
              <p className="font-mono text-3xl font-semibold text-ink-deep tabular-nums">
                {data.total_applications.toLocaleString(locale)}
              </p>
              <p className="font-mono text-xs text-accent-violet-mid tabular-nums">
                {t("metrics.totalApplicationsSub", {
                  applied: data.pipeline_by_stage.APPLIED.toLocaleString(locale),
                })}
              </p>
            </div>

            <div className="flex flex-col justify-between gap-2 border-b border-hairline-cloud pb-4 sm:border-r sm:border-b-0 sm:pr-6 sm:pb-0">
              <p className="text-sm font-medium text-accent-violet-mid">
                {t("metrics.interviewAndOffer")}
              </p>
              <p className="font-mono text-3xl font-semibold text-ink-deep tabular-nums">
                {(data.pipeline_by_stage.INTERVIEW + data.pipeline_by_stage.OFFER).toLocaleString(
                  locale,
                )}
              </p>
              <p className="font-mono text-xs text-accent-violet-mid tabular-nums">
                {t("metrics.interviewAndOfferSub", {
                  hired: data.pipeline_by_stage.HIRED.toLocaleString(locale),
                })}
              </p>
            </div>

            {/* Single Featured Dark Card (card-feature-dark invariance: permanently surface-night) */}
            <div className="flex flex-col justify-between gap-4 rounded-xl border border-hairline-violet bg-surface-night p-5 text-on-primary">
              {canManageJobs ? (
                <>
                  <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold tracking-[0.2px] text-on-dark-muted uppercase">
                      {t("featured.aiSpendEyebrow")}
                    </p>
                    {usage ? (
                      <>
                        <p className="font-mono text-xl font-semibold text-on-primary tabular-nums">
                          {formatUsd(locale, usage.total_cost_usd)}{" "}
                          <span className="text-sm font-normal text-on-dark-muted">
                            / {formatUsd(locale, usage.budget_usd)}
                          </span>
                        </p>
                        <p
                          className={`font-mono text-xs tabular-nums ${
                            usage.usage_ratio >= 0.8 ? "text-accent-pink" : "text-on-dark-muted"
                          }`}
                        >
                          {t("featured.aiSpendRatio", {
                            percent: formatPercent(locale, usage.usage_ratio),
                          })}
                        </p>
                      </>
                    ) : usageLoading ? (
                      <div
                        aria-busy="true"
                        className="mt-1 h-10 w-36 animate-pulse rounded-xs bg-on-dark-faint motion-reduce:animate-none"
                      />
                    ) : (
                      <p className="text-sm text-on-dark-muted">
                        {t("featured.aiSpendUnavailable")}
                      </p>
                    )}
                  </div>
                  <Link
                    href="/settings/usage"
                    className="inline-flex min-h-11 w-fit button-inverted items-center gap-1.5 whitespace-nowrap text-ink-deep"
                  >
                    <span>{t("featured.viewUsage")}</span>
                    <ArrowRight size={15} weight="regular" aria-hidden="true" />
                  </Link>
                </>
              ) : (
                <>
                  <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold tracking-[0.2px] text-on-dark-muted uppercase">
                      {t("featured.assignedJobsEyebrow")}
                    </p>
                    <p className="font-mono text-3xl font-semibold text-on-primary tabular-nums">
                      {data.total_jobs.toLocaleString(locale)}
                    </p>
                    <p className="text-xs text-on-dark-muted">{t("featured.assignedJobsSub")}</p>
                  </div>
                  <Link
                    href="/jobs"
                    className="inline-flex min-h-11 w-fit button-inverted items-center gap-1.5 whitespace-nowrap text-ink-deep"
                  >
                    <span>{t("featured.openJobs")}</span>
                    <ArrowRight size={15} weight="regular" aria-hidden="true" />
                  </Link>
                </>
              )}
            </div>
          </section>

          {/* Primary Operational Area: 7/5 asymmetric console split */}
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
            {/* Left: 7-Stage Pipeline distribution with monochrome bg-primary bar */}
            <section className="flex flex-col gap-4 lg:col-span-7">
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="heading-display text-xl font-semibold text-ink-deep">
                  {t("pipeline.title")}
                </h2>
                <span className="font-mono text-xs text-accent-violet-mid tabular-nums">
                  {t("pipeline.total", {
                    count: data.total_applications.toLocaleString(locale),
                  })}
                </span>
              </div>
              <div className="flex flex-col">
                {STAGES.map((stage) => {
                  const count = data.pipeline_by_stage[stage] ?? 0;
                  const ratio = data.total_applications > 0 ? count / data.total_applications : 0;
                  const widthPercent = count === 0 ? 0 : Math.max(3, Math.round(ratio * 100));
                  return (
                    <div
                      key={stage}
                      className="grid grid-cols-[7.5rem_1fr_auto] items-center gap-3 border-b border-hairline-cloud py-2.5 text-sm last:border-b-0 sm:grid-cols-[9rem_1fr_auto]"
                    >
                      <span className="truncate font-medium text-ink-deep">{stageName(stage)}</span>
                      <div className="flex items-center">
                        {widthPercent > 0 ? (
                          <div
                            className="h-2 rounded-xs bg-primary"
                            style={{ width: `${widthPercent}%` }}
                          />
                        ) : (
                          <div className="h-2 w-0.5 rounded-xs bg-hairline-cloud" />
                        )}
                      </div>
                      <div className="flex items-baseline justify-end gap-2 font-mono text-xs tabular-nums">
                        <span className="font-semibold text-ink-deep">
                          {count.toLocaleString(locale)}
                        </span>
                        <span className="w-12 text-right text-accent-violet-mid">
                          {formatPercent(locale, ratio)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Right: Action Queue */}
            <section className="flex flex-col gap-4 lg:col-span-5">
              <h2 className="heading-display text-xl font-semibold text-ink-deep">
                {t("actions.title")}
              </h2>
              <ActionQueueList data={data} canManageJobs={canManageJobs} locale={locale} />
            </section>
          </div>

          {/* Lists & Logs Area: 7/5 asymmetric console split */}
          <div className="grid grid-cols-1 gap-8 border-t border-hairline-cloud pt-8 lg:grid-cols-12">
            {/* Left: Recent Jobs */}
            <section className="flex flex-col gap-4 lg:col-span-7">
              <div className="flex items-baseline justify-between gap-4">
                <h2 className="heading-display text-xl font-semibold text-ink-deep">
                  {t("recentJobs.title")}
                </h2>
                <Link href="/jobs" className="text-sm font-medium text-ink-deep underline">
                  {t("recentJobs.viewAll")}
                </Link>
              </div>
              <ul className="flex flex-col">
                {data.recent_jobs.map((job) => (
                  <li
                    key={job.id}
                    className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline-cloud py-3 last:border-b-0"
                  >
                    <div className="flex min-w-0 flex-wrap items-baseline gap-2">
                      <Link
                        href={`/jobs/${job.id}`}
                        className="font-medium text-ink-deep underline"
                      >
                        {job.title}
                      </Link>
                      <span className="font-mono text-xs text-accent-violet-mid">{job.level}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge>{statusName(job.status)}</Badge>
                      <span className="font-mono text-xs text-ink-deep tabular-nums">
                        {t("recentJobs.applicationsCount", {
                          count: job.application_count.toLocaleString(locale),
                        })}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            {/* Right: Recent Activity */}
            <section className="flex flex-col gap-4 lg:col-span-5">
              <h2 className="heading-display text-xl font-semibold text-ink-deep">
                {t("recentActivity.title")}
              </h2>
              {data.recent_activity.length === 0 ? (
                <p className="py-2 text-sm text-accent-violet-mid">{tActivity("empty")}</p>
              ) : (
                <ol className="flex flex-col">
                  {data.recent_activity.map((entry) => {
                    const badge = actorBadge(entry.actor_type, tActivity);
                    return (
                      <li
                        key={entry.id}
                        className="flex flex-col gap-1 border-b border-hairline-cloud py-2.5 text-sm last:border-b-0"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          {badge && <Badge>{badge}</Badge>}
                          <span className="text-ink-deep">
                            {formatActivity(entry, translators)}
                          </span>
                        </div>
                        <time
                          dateTime={entry.created_at}
                          className="font-mono text-xs text-accent-violet-mid tabular-nums"
                        >
                          {new Date(entry.created_at).toLocaleString(locale)}
                        </time>
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  );
}

function ActionQueueList({
  data,
  canManageJobs,
  locale,
}: {
  data: DashboardSummary;
  canManageJobs: boolean;
  locale: string;
}) {
  const t = useTranslations("dashboard");
  const { pending_criteria_jobs, failed_parse_jobs, unscored_jobs, new_applications_count } =
    data.action_items;

  const hasManagerActions =
    canManageJobs &&
    (failed_parse_jobs.count > 0 ||
      pending_criteria_jobs.count > 0 ||
      unscored_jobs.count > 0 ||
      new_applications_count > 0);
  const hasReviewerActions = !canManageJobs && new_applications_count > 0;

  if (!hasManagerActions && !hasReviewerActions) {
    return (
      <div className="flex items-center gap-2.5 py-2 text-sm text-accent-violet-mid">
        <CheckCircle size={18} weight="regular" aria-hidden="true" className="shrink-0" />
        <span>{t("actions.empty")}</span>
      </div>
    );
  }

  return (
    <ul className="flex flex-col">
      {canManageJobs &&
        failed_parse_jobs.items.map((job) => (
          <li
            key={`failed-${job.id}`}
            className="flex items-start gap-2.5 border-b border-l-2 border-b-hairline-cloud border-l-accent-pink py-2.5 pl-3 text-sm last:border-b-0"
          >
            <WarningCircle
              size={18}
              weight="regular"
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-accent-pink"
            />
            <div className="flex min-w-0 flex-col gap-0.5">
              <Link href={`/jobs/${job.id}`} className="font-medium text-ink-deep underline">
                {job.title}
              </Link>
              <span className="text-xs text-accent-violet-mid">{t("actions.failedParse")}</span>
            </div>
          </li>
        ))}

      {canManageJobs &&
        pending_criteria_jobs.items.map((job) => (
          <li
            key={`criteria-${job.id}`}
            className="flex items-start gap-2.5 border-b border-hairline-cloud py-2.5 text-sm last:border-b-0"
          >
            <FileText size={18} weight="regular" aria-hidden="true" className="mt-0.5 shrink-0" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <Link href={`/jobs/${job.id}`} className="font-medium text-ink-deep underline">
                {job.title}
              </Link>
              <span className="text-xs text-accent-violet-mid">{t("actions.pendingCriteria")}</span>
            </div>
          </li>
        ))}

      {canManageJobs &&
        unscored_jobs.items.map((job) => (
          <li
            key={`unscored-${job.id}`}
            className="flex items-start gap-2.5 border-b border-hairline-cloud py-2.5 text-sm last:border-b-0"
          >
            <ChartBar size={18} weight="regular" aria-hidden="true" className="mt-0.5 shrink-0" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <Link href={`/jobs/${job.id}`} className="font-medium text-ink-deep underline">
                {job.title}
              </Link>
              <span className="text-xs text-accent-violet-mid">
                {t("actions.unscored", {
                  count: job.application_count.toLocaleString(locale),
                })}
              </span>
            </div>
          </li>
        ))}

      {new_applications_count > 0 && (
        <li className="flex items-start gap-2.5 border-b border-hairline-cloud py-2.5 text-sm last:border-b-0">
          <UsersThree size={18} weight="regular" aria-hidden="true" className="mt-0.5 shrink-0" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <Link href="/jobs" className="font-medium text-ink-deep underline">
              {canManageJobs
                ? t("actions.newApplications", {
                    count: new_applications_count.toLocaleString(locale),
                  })
                : t("actions.reviewerApplications", {
                    count: new_applications_count.toLocaleString(locale),
                  })}
            </Link>
          </div>
        </li>
      )}
    </ul>
  );
}

type FetchState = {
  version: number;
  data: DashboardSummary | null;
  error: boolean;
};

type UsageFetchState = {
  version: number;
  role: Role;
  summary: UsageSummary | null;
};

/** Workspace Overview Dashboard page (`/`). */
export default function DashboardPage() {
  const role = useRole();
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<FetchState | null>(null);
  const [usageState, setUsageState] = useState<UsageFetchState | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/dashboard")
      .then(async (response) => {
        if (cancelled) return;
        if (response.status === 401) {
          window.location.replace("/login");
          return;
        }
        if (!response.ok) {
          setState({ version, data: null, error: true });
          return;
        }
        const summary = (await response.json()) as DashboardSummary;
        if (!cancelled) setState({ version, data: summary, error: false });
      })
      .catch(() => {
        if (!cancelled) setState({ version, data: null, error: true });
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  useEffect(() => {
    if (role !== "COMPANY_ADMIN" && role !== "RECRUITER") return;
    let cancelled = false;
    apiFetch("/api/usage")
      .then(async (response) => {
        if (cancelled) return;
        const summary = response.ok ? ((await response.json()) as UsageSummary) : null;
        if (!cancelled) setUsageState({ version, role, summary });
      })
      .catch(() => {
        if (!cancelled) setUsageState({ version, role, summary: null });
      });
    return () => {
      cancelled = true;
    };
  }, [role, version]);

  const loading = state === null || state.version !== version || role === null;
  const canReadUsage = role === "COMPANY_ADMIN" || role === "RECRUITER";
  const usageReady =
    usageState !== null && usageState.version === version && usageState.role === role;

  return (
    <DashboardView
      role={role}
      data={loading ? null : state.data}
      usage={canReadUsage && usageReady ? usageState.summary : null}
      usageLoading={canReadUsage && !usageReady}
      loading={loading}
      error={loading ? false : state.error}
      onRetry={() => setVersion((v) => v + 1)}
    />
  );
}
