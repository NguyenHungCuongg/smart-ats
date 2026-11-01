"use client";

import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { applyError } from "./messages";

export type PublicJob = {
  job_id: string;
  title: string;
  status: string;
  public_apply_enabled: boolean;
  apply_deadline: string | null;
  location: string | null;
  work_mode: string | null;
  published_at?: string | null;
  criteria: {
    skills?: { name: string; must_have: boolean }[];
    min_years_experience?: number | null;
    education?: string | null;
    responsibilities?: string[];
  } | null;
  tenant_name: string;
  tenant_logo_url: string | null;
  tenant_privacy_notice_url: string | null;
  is_closed: boolean;
};

const MAX_CV_BYTES = 10 * 1024 * 1024; // 10 MB

export function ApplyForm({ slug, initialJob }: { slug: string; initialJob?: PublicJob | null }) {
  const t = useTranslations("apply");
  const locale = useLocale();

  const [job, setJob] = useState<PublicJob | null>(initialJob ?? null);
  const [loading, setLoading] = useState(!initialJob);
  const [notFound, setNotFound] = useState(false);
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState<number | null>(null);

  useEffect(() => {
    if (initialJob !== undefined && initialJob !== null) return;
    let active = true;
    apiFetch(`/api/apply/${slug}`).then(async (response) => {
      if (!active) return;
      if (response.status === 404) {
        setNotFound(true);
      } else if (response.ok) {
        setJob(await response.json());
      } else {
        setApiStatus(response.status);
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [slug, initialJob]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setClientError(null);
    setApiStatus(null);

    const form = new FormData(event.currentTarget);
    const file = form.get("file") as File | null;
    const consent = form.get("consent");

    if (!consent) {
      setClientError(t("consentRequired"));
      return;
    }

    if (!file || file.size === 0) {
      setClientError(t("unsupportedFile"));
      return;
    }

    if (file.size > MAX_CV_BYTES) {
      setClientError(t("fileTooLarge"));
      return;
    }

    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".pdf") && !lowerName.endsWith(".docx")) {
      setClientError(t("unsupportedFile"));
      return;
    }

    setPending(true);
    const response = await apiFetch(`/api/apply/${slug}`, {
      method: "POST",
      body: form,
    });
    setPending(false);

    if (response.ok) {
      setSubmitted(true);
    } else {
      setApiStatus(response.status);
    }
  }

  const errorMessage = clientError ?? (apiStatus === null ? null : applyError(t, apiStatus));

  if (loading) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-8">
        <div aria-busy="true" className="flex flex-col gap-4">
          <div className="h-8 w-1/3 animate-pulse rounded-md bg-hairline-cloud" />
          <div className="h-10 w-2/3 animate-pulse rounded-md bg-hairline-cloud" />
          <div className="h-64 animate-pulse rounded-md bg-hairline-cloud" />
        </div>
      </main>
    );
  }

  if (notFound || !job) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center px-4 py-12 text-center">
        <div className="flex flex-col gap-2">
          <h1 className="heading-display text-3xl font-bold">{t("notFoundTitle")}</h1>
          <p className="opacity-80">{t("notFoundMessage")}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-4 py-8">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          {job.tenant_logo_url && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={job.tenant_logo_url}
              alt={job.tenant_name}
              className="h-10 w-10 rounded-full border border-hairline-cloud object-cover"
            />
          )}
          <span className="text-lg font-semibold">{job.tenant_name}</span>
        </div>

        <h1 className="heading-display text-3xl font-bold">{job.title}</h1>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          {job.location && <Badge>{t("location", { location: job.location })}</Badge>}
          {job.work_mode && <Badge>{t("workMode", { mode: job.work_mode })}</Badge>}
          {job.apply_deadline && (
            <Badge>
              {t("deadline", {
                deadline: new Date(job.apply_deadline).toLocaleDateString(locale),
              })}
            </Badge>
          )}
        </div>
      </header>

      {job.criteria && (
        <section className="flex flex-col gap-4 rounded-md border border-hairline-cloud bg-surface-canvas-light p-6 shadow-sm">
          {job.criteria.responsibilities && job.criteria.responsibilities.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="heading-display text-lg font-semibold">{t("responsibilities")}</h2>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {job.criteria.responsibilities.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          {job.criteria.skills && job.criteria.skills.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="heading-display text-lg font-semibold">{t("skills")}</h2>
              <div className="flex flex-wrap gap-2">
                {job.criteria.skills.map((skill, i) => (
                  <span
                    key={i}
                    className={`rounded-xs px-2 py-1 text-xs font-medium ${
                      skill.must_have
                        ? "bg-accent-lime font-semibold text-ink-deep"
                        : "bg-surface-night/10 text-ink-deep"
                    }`}
                  >
                    {skill.name} {skill.must_have ? "*" : ""}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {job.is_closed ? (
        <div
          role="status"
          className="rounded-md border border-accent-pink bg-surface-canvas-light p-6 text-ink-deep shadow-sm"
        >
          <h2 className="heading-display text-xl font-semibold text-accent-pink">
            {t("closedTitle")}
          </h2>
          <p className="mt-2 text-sm opacity-80">{t("closedMessage")}</p>
        </div>
      ) : submitted ? (
        <div
          role="status"
          className="rounded-md border border-hairline-cloud bg-surface-canvas-light p-6 text-ink-deep shadow-sm"
        >
          <h2 className="heading-display text-xl font-semibold">{t("successTitle")}</h2>
          <p className="mt-2 text-sm opacity-80">{t("successMessage")}</p>
        </div>
      ) : (
        <form
          onSubmit={onSubmit}
          className="flex flex-col gap-4 rounded-md border border-hairline-cloud bg-surface-canvas-light p-6 shadow-sm"
        >
          <h2 className="heading-display text-xl font-semibold">
            {t("title", { jobTitle: job.title })}
          </h2>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{t("fullName")} *</span>
            <input
              name="full_name"
              required
              maxLength={200}
              placeholder={t("fullNamePlaceholder")}
              className="text-input"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{t("email")} *</span>
            <input
              name="email"
              type="email"
              required
              maxLength={255}
              placeholder={t("emailPlaceholder")}
              className="text-input"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{t("phone")}</span>
            <input
              name="phone"
              type="tel"
              maxLength={50}
              placeholder={t("phonePlaceholder")}
              className="text-input"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{t("cvFile")} *</span>
            <input
              name="file"
              type="file"
              required
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="cursor-pointer text-sm file:mr-3 file:rounded-md file:border-0 file:bg-surface-night file:px-3 file:py-2 file:text-xs file:font-semibold file:text-on-primary hover:file:opacity-90"
            />
          </label>

          <div className="flex items-start gap-2 pt-1">
            <input
              id="consent"
              name="consent"
              type="checkbox"
              required
              value="true"
              className="mt-1 h-4 w-4 cursor-pointer rounded-xs border-hairline-cool accent-primary"
            />
            <label htmlFor="consent" className="cursor-pointer text-sm select-none">
              {t("consent")}{" "}
              <a
                href={job.tenant_privacy_notice_url || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium underline hover:text-accent-violet"
              >
                {t("privacyNotice")}
              </a>
            </label>
          </div>

          {errorMessage && (
            <p
              role="alert"
              className="border-l-4 border-accent-pink pl-3 text-sm font-medium text-accent-pink"
            >
              {errorMessage}
            </p>
          )}

          <button type="submit" disabled={pending} className="mt-2 button-primary">
            {pending ? t("submitting") : t("submit")}
          </button>
        </form>
      )}
    </main>
  );
}
