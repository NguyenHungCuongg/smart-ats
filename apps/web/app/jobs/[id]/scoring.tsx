"use client";

import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";
import type { Job } from "../criteria";
import {
  type Claim,
  type ScoreResult,
  type ScoringRun,
  type TimelineEntry,
  newestOnly,
  scoreBlocker,
} from "../scoring";

const START_ERRORS: Record<number, "budgetExceeded" | "notEligible" | "unpricedModel"> = {
  402: "budgetExceeded",
  409: "notEligible",
  503: "unpricedModel",
};

// The result errors the catalog words (scoring.resultError); any other reads as a failure.
const RESULT_ERRORS = [
  "NO_TEXT",
  "ENCRYPTED_PDF",
  "DOCX_TOO_LARGE",
  "UNREADABLE",
  "UNSUPPORTED_FORMAT",
  "READ_FAILED",
  "SCORING_FAILED",
  "STUCK",
  "LLM_UNAVAILABLE",
] as const;

/** Start a Scoring Run of the Job and show the Fit-Gap Report of each Application (FR-A1.3). */
export function Scoring({
  job,
  editable,
  applications,
}: {
  job: Job;
  /** Whether a run may start: not for a Reviewer, nor on an archived Job. */
  editable: boolean;
  applications: number;
}) {
  const t = useTranslations("scoring");
  const locale = useLocale();
  const [run, setRun] = useState<ScoringRun | null>(null);
  // The run shown: set by a start before its first load, so its events are not dropped.
  const [runId, setRunId] = useState<string | null>(null);
  const [retryingAppId, setRetryingAppId] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<number | null>(null);
  // Bumped to reload the run.
  const [version, setVersion] = useState(0);
  const [pending, setPending] = useState(false);
  // The refused status, worded at render in the language shown.
  const [refused, setRefused] = useState<number | null>(null);
  // A load answered after a newer one would bring back an older run, whose id then filters
  // out the events of the newer one.
  const [load] = useState(() =>
    newestOnly<ScoringRun | null>((latest) => {
      if (!latest) return; // 404: never scored
      setRun(latest);
      setRunId(latest.id);
    }),
  );

  useEffect(() => {
    load(apiFetch(`/api/jobs/${job.id}/scoring-runs/latest`).then((r) => (r.ok ? r.json() : null)));
  }, [job.id, version, load]);
  useProgressEvents(
    "scoring.result",
    (data) => {
      // Only this run's results: a stale task of an older run must not reload over it.
      if ((data as { run_id: string }).run_id === runId) setVersion((v) => v + 1);
    },
    () => setVersion((v) => v + 1),
  );
  // A new CV may replace a scored one.
  useProgressEvents("upload.item", (data) => {
    if ((data as { job_id: string }).job_id === job.id) setVersion((v) => v + 1);
  });

  async function onStart() {
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}/scoring-runs`, { method: "POST" });
    setPending(false);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      setRefused(null);
      setRunId((await response.json()).run_id);
    } else {
      setRefused(response.status);
    }
    setVersion((v) => v + 1);
  }

  async function onRetryResult(applicationId: string) {
    if (!run) return;
    setRetryingAppId(applicationId);
    const response = await apiFetch(
      `/api/jobs/${job.id}/scoring-runs/${run.id}/results/${applicationId}/retry`,
      { method: "POST" },
    );
    setRetryingAppId(null);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      setRetryError(null);
      setRunId(run.id);
      setVersion((v) => v + 1);
    } else {
      setRetryError(response.status);
    }
  }

  const blocker = scoreBlocker(t, job, applications, run);
  return (
    <section className="flex flex-col gap-4 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">{t("title")}</h2>
      {run && (
        <p className="text-sm">
          {t.rich("latestRun", {
            at: new Date(run.created_at).toLocaleString(locale),
            status: t(`runStatus.${run.status}`),
            model: run.model,
            ...run.weights,
            code: (chunks) => <code className="font-mono">{chunks}</code>,
          })}
        </p>
      )}
      {editable && (
        <>
          {blocker && (
            <p className="text-sm" role={run?.running ? "status" : undefined}>
              {blocker}
            </p>
          )}
          {refused !== null && <p role="alert">{t(START_ERRORS[refused] ?? "startFailed")}</p>}
          <button
            type="button"
            onClick={onStart}
            disabled={pending || blocker !== null}
            className="self-start button-outline"
          >
            {run ? t("rescore") : t("score")}
          </button>
        </>
      )}
      {!editable && !run && <p className="text-sm">{t("notScored")}</p>}
      {retryError !== null && (
        <p role="alert">{t(retryError === 402 ? "budgetExceeded" : "retryResultFailed")}</p>
      )}
      {run?.results.map((result) => (
        <Result
          key={result.application_id}
          result={result}
          retrying={retryingAppId === result.application_id}
          onRetry={editable ? () => onRetryResult(result.application_id) : undefined}
        />
      ))}
    </section>
  );
}

const REPORT_PARTS = [
  ["strengths", "Strengths"],
  ["gaps", "Gaps"],
  ["recommendations", "Recommendations"],
] as const;

export function Result({
  result,
  retrying = false,
  onRetry,
}: {
  result: ScoreResult;
  retrying?: boolean;
  onRetry?: () => void;
}) {
  const t = useTranslations("scoring");
  const locale = useLocale();
  const resultError = RESULT_ERRORS.find((code) => code === result.error_code);
  const rubric = result.rubric_grades;
  const report = result.fit_gap_report;
  const detail = result.must_have_detail;
  const timeline = result.experience_detail;
  return (
    <article className="flex flex-col gap-4 rounded-xl border border-hairline-cloud bg-surface-canvas-light p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h3 className="text-xl font-semibold">{result.full_name ?? t("candidate")}</h3>
        {result.cv_document_id !== result.current_cv_document_id && <Badge>{t("cvChanged")}</Badge>}
      </header>
      {result.status === "PENDING" && <p role="status">{t("scoringOne")}</p>}
      {result.status === "FAILED" && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert">{resultError ? t(`resultError.${resultError}`) : t("resultFailed")}</p>
          {onRetry && result.error_code === "LLM_UNAVAILABLE" && (
            <button
              type="button"
              disabled={retrying}
              onClick={onRetry}
              aria-label={t("retryResultCandidate", { name: result.full_name ?? t("candidate") })}
              className="ml-auto button-outline"
            >
              {t("retryResult")}
            </button>
          )}
        </div>
      )}
      {result.status === "SCORED" && rubric && report && (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <Score label="Total" value={result.total_score} />
            <Score label="Technical Fit" value={result.technical_score} />
            <Score label="Soft-Skill Claims" value={result.soft_skills_score}>
              <Badge>{t("verifyInInterview")}</Badge>
            </Score>
            <Score label="Experience Fit" value={result.experience_score} />
          </div>

          {detail && (
            <div className="flex flex-col gap-1 text-sm">
              <p className="font-medium">
                {t("coverage", {
                  percent: Math.round((result.must_have_coverage ?? 0) * 100),
                  matched: detail.matched.length,
                  all: detail.matched.length + detail.missing.length,
                })}
              </p>
              {detail.matches ? (
                <ul className="flex flex-col gap-1">
                  {detail.matches.map((match) => (
                    <li key={match.must_have}>
                      {t("match", {
                        mustHave: match.must_have,
                        cvSkill: match.cv_skill,
                        method: t(`matchMethod.${match.method}`, {
                          similarity:
                            match.similarity?.toLocaleString(locale, {
                              maximumFractionDigits: 2,
                            }) ?? "",
                        }),
                      })}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{t("matched", { skills: detail.matched.join(", ") || "—" })}</p>
              )}
              <p>{t("missing", { skills: detail.missing.join(", ") || "—" })}</p>
            </div>
          )}

          {timeline && (
            <div className="flex flex-col gap-1 text-sm">
              <p className="font-medium">
                {t("timeline", {
                  years: (timeline.total_months / 12).toLocaleString(locale, {
                    maximumFractionDigits: 1,
                  }),
                })}
              </p>
              <ul className="flex flex-col gap-1">
                {timeline.entries.map((entry, i) => (
                  <li key={i}>
                    {t("timelineEntry", { ...written(entry), months: entry.months ?? 0 })}
                  </li>
                ))}
                {timeline.unreadable.map((entry, i) => (
                  <li key={`unreadable-${i}`}>{t("timelineUnreadable", written(entry))}</li>
                ))}
              </ul>
            </div>
          )}

          <Part title={t("reasons")}>
            {(
              [
                ["technical", "Technical"],
                ["soft_skills", "Soft-Skill Claims"],
                ["experience", "Experience"],
              ] as const
            ).map(([axis, label]) => (
              <Item key={axis} claim={rubric[axis]}>
                {label} {rubric[axis].grade}/5: {rubric[axis].reason}
              </Item>
            ))}
          </Part>
          {REPORT_PARTS.map(([part, title]) => (
            <Part key={part} title={title}>
              {report[part].map((claim, i) => (
                <Item key={i} claim={claim}>
                  {claim.text}
                </Item>
              ))}
            </Part>
          ))}
        </>
      )}
    </article>
  );
}

/** A work history entry's words as the CV writes them, a dash for what it leaves out. */
function written(entry: TimelineEntry) {
  return {
    title: entry.title ?? "—",
    company: entry.company ?? "—",
    start: entry.start ?? "—",
    end: entry.end ?? "—",
  };
}

function Score({
  label,
  value,
  children,
}: {
  label: string;
  value: number | null;
  children?: ReactNode;
}) {
  const locale = useLocale();
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <span className="text-3xl font-semibold">
        {value === null ? "—" : value.toLocaleString(locale, { maximumFractionDigits: 2 })}
      </span>
      {children}
    </div>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h4 className="font-semibold">{title}</h4>
      <ul className="flex flex-col gap-2">{children}</ul>
    </div>
  );
}

/** A claim with the Evidence quoted for it, flagged when none was found in the source. */
function Item({ claim, children }: { claim: Claim; children: ReactNode }) {
  const t = useTranslations("scoring");
  return (
    <li className="flex flex-col gap-1 text-sm">
      <span className="flex flex-wrap items-center gap-2">
        {children}
        {!claim.grounded && <Badge>{t("noEvidence")}</Badge>}
      </span>
      {claim.evidence.map((quote, i) => (
        <q key={i} className="border-l-2 border-hairline-cloud pl-3 italic">
          {quote}
        </q>
      ))}
    </li>
  );
}
