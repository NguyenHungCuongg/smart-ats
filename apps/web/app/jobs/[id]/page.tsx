"use client";

import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, type ReactNode, use, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";
import { useRole } from "../../session";
import {
  type Form,
  type Job,
  LEVELS,
  WORK_MODES,
  formFromJob,
  toConfirmation,
  weightTotal,
} from "../criteria";
import { canEdit } from "../lifecycle";
import { MetadataForm, StatusActions } from "./lifecycle";
import { Pipeline } from "./pipeline";
import { Reviewers } from "./reviewers";
import { Scoring } from "./scoring";
import { Uploads } from "./uploads";

// The parse errors the catalog words (job.parseError); any other reads as a failed parse.
const PARSE_ERRORS = [
  "NO_TEXT",
  "ENCRYPTED_PDF",
  "DOCX_TOO_LARGE",
  "UNREADABLE",
  "UNSUPPORTED_FORMAT",
  "UNPRICED_MODEL",
  "STUCK",
] as const;

// Secondary actions read as link-on-light: one filled button per page (DESIGN.md).
const LINK_BUTTON = "font-medium underline";

/** Follows the parse of a Job's JD, then lets the Recruiter edit and confirm the criteria and
 * move the Job through its lifecycle; a Reviewer, or anyone on an archived Job, only reads. */
export default function JobPage({ params }: PageProps<"/jobs/[id]">) {
  const { id } = use(params);
  const t = useTranslations("job");
  const statusName = useTranslations("lifecycle.status");
  const role = useRole();
  const [job, setJob] = useState<Job | null>(null);
  const [missing, setMissing] = useState(false);
  // Bumped to reload the Job.
  const [version, setVersion] = useState(0);
  const [applications, setApplications] = useState(0);

  useEffect(() => {
    apiFetch(`/api/jobs/${id}`).then(async (response) => {
      if (response.status === 401) window.location.replace("/login");
      else if (response.ok) setJob(await response.json());
      else setMissing(true);
    });
  }, [id, version]);
  // Reloaded whenever the stream opens: a parse may finish before it does, or while it is down.
  useProgressEvents(
    "job.parsed",
    (data) => {
      if ((data as { job_id: string }).job_id === id) setVersion((v) => v + 1);
    },
    () => setVersion((v) => v + 1),
  );

  const editable = job !== null && role !== null && canEdit(role, job.status);
  return (
    <main className="flex-1">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        {missing ? (
          <p>{t("notFound")}</p>
        ) : !job || !role ? (
          <div aria-busy="true" aria-label={t("loading")} className="flex flex-col gap-4">
            <div className="h-9 w-2/3 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : (
          <>
            <header className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="heading-display text-3xl font-semibold">{job.title}</h1>
                <Badge>{statusName(job.status)}</Badge>
              </div>
              {role === "REVIEWER" ? (
                <p className="text-sm">{t("reviewerReadOnly")}</p>
              ) : job.status === "ARCHIVED" ? (
                <p className="text-sm">{t("archivedReadOnly")}</p>
              ) : (
                <>
                  <StatusActions job={job} onChanged={setJob} />
                  <MetadataForm key={job.apply_deadline} job={job} onSaved={setJob} />
                </>
              )}
            </header>
            {job.parse_status === "PENDING" ? (
              <p role="status">{t("parsing")}</p>
            ) : editable ? (
              // Remount on every saved or parsed version, so the form starts from it.
              <CriteriaForm
                key={`${job.parse_status}-${job.criteria_confirmed_at}`}
                job={job}
                onSaved={setJob}
              />
            ) : (
              <CriteriaView job={job} />
            )}
            {editable && <Reviewers jobId={id} />}
            {/* CVs go into any Job; only scoring needs confirmed criteria. */}
            {editable && <Uploads jobId={id} />}
            <Pipeline jobId={id} editable={editable} onApplications={setApplications} />
            <Scoring job={job} editable={editable} applications={applications} />
          </>
        )}
      </div>
    </main>
  );
}

/** The criteria as confirmed or parsed, for those who may not edit them. */
function CriteriaView({ job }: { job: Job }) {
  const t = useTranslations("job");
  const locale = useLocale();
  const criteria = job.criteria;
  const facts: [string, string | null][] = [
    [t("level"), job.level],
    [t("workMode"), job.work_mode],
    [t("department"), job.department],
    [t("location"), job.location],
    [t("deadline"), job.apply_deadline && new Date(job.apply_deadline).toLocaleDateString(locale)],
    [t("minYears"), criteria?.min_years_experience?.toLocaleString(locale) ?? null],
    [t("education"), criteria?.education ?? null],
    [t("salary"), criteria?.salary_range ?? null],
    [t("weights"), t("weightsValue", job.weights)],
  ];
  return (
    <section className="flex flex-col gap-4">
      <h2 className="heading-display text-2xl font-semibold">{t("criteria")}</h2>
      {!job.criteria_confirmed_at && <p className="text-sm">{t("notConfirmed")}</p>}
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="font-medium">{label}</dt>
            <dd>{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {criteria && (
        <>
          <div className="flex flex-col gap-2">
            <h3 className="font-semibold">{t("skills")}</h3>
            <ul className="flex flex-wrap gap-2">
              {criteria.skills.map((skill) => (
                <li key={skill.name} className="flex items-center gap-1">
                  {skill.name}
                  {skill.must_have && <Badge>{t("mustHave")}</Badge>}
                </li>
              ))}
            </ul>
          </div>
          {criteria.responsibilities.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="font-semibold">{t("responsibilities")}</h3>
              <ul className="list-disc pl-5">
                {criteria.responsibilities.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function CriteriaForm({ job, onSaved }: { job: Job; onSaved: (job: Job) => void }) {
  const t = useTranslations("job");
  const locale = useLocale();
  const [form, setForm] = useState<Form>(() => formFromJob(job));
  // The refused status, worded at render in the language shown.
  const [refused, setRefused] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const total = weightTotal(form.weights);
  const parseError = PARSE_ERRORS.find((code) => code === job.parse_error);
  const review = (field: string) => job.verification?.[field] === "NEEDS_REVIEW";
  const set = (changes: Partial<Form>) => setForm({ ...form, ...changes });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}/criteria`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toConfirmation(form)),
    });
    setPending(false);
    if (response.ok) return onSaved(await response.json());
    setRefused(response.status);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <h2 className="heading-display text-2xl font-semibold">{t("confirmTitle")}</h2>
      {job.parse_status === "FAILED" && (
        <p role="alert">
          {parseError ? t(`parseError.${parseError}`) : t("parseFailed")} {t("enterByHand")}
        </p>
      )}
      {job.criteria_confirmed_at && (
        <p role="status">
          {t("confirmedAt", { at: new Date(job.criteria_confirmed_at).toLocaleString(locale) })}
        </p>
      )}
      {job.verification && <p className="text-sm">{t("needsReviewNote")}</p>}

      <Field label={t("jobTitle")} review={review("title")}>
        <input
          required
          maxLength={200}
          value={form.title}
          onChange={(e) => set({ title: e.target.value })}
          className="text-input"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("level")} review={review("level")}>
          <select
            value={form.level}
            onChange={(e) => set({ level: e.target.value as Form["level"] })}
            className="text-input"
          >
            {LEVELS.map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </Field>
        <Field label={t("workMode")} review={review("work_mode")}>
          <select
            value={form.work_mode}
            onChange={(e) => set({ work_mode: e.target.value as Form["work_mode"] })}
            className="text-input"
          >
            <option value="">{t("notStated")}</option>
            {WORK_MODES.map((mode) => (
              <option key={mode}>{mode}</option>
            ))}
          </select>
        </Field>
        <Field label={t("department")} review={review("department")}>
          <input
            maxLength={200}
            value={form.department}
            onChange={(e) => set({ department: e.target.value })}
            className="text-input"
          />
        </Field>
        <Field label={t("location")} review={review("location")}>
          <input
            maxLength={200}
            value={form.location}
            onChange={(e) => set({ location: e.target.value })}
            className="text-input"
          />
        </Field>
      </div>

      <Group label={t("skills")} review={review("skills")}>
        {form.skills.map((skill, i) => (
          <div key={i} className="flex items-center gap-3">
            <input
              aria-label={t("skillName")}
              maxLength={200}
              value={skill.name}
              onChange={(e) =>
                set({ skills: form.skills.with(i, { ...skill, name: e.target.value }) })
              }
              className="flex-1 text-input"
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={skill.must_have}
                onChange={(e) =>
                  set({ skills: form.skills.with(i, { ...skill, must_have: e.target.checked }) })
                }
              />
              {t("mustHave")}
            </label>
            <button
              type="button"
              onClick={() => set({ skills: form.skills.toSpliced(i, 1) })}
              className={LINK_BUTTON}
            >
              {t("remove")}
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => set({ skills: [...form.skills, { name: "", must_have: false }] })}
          className={`${LINK_BUTTON} self-start`}
        >
          {t("addSkill")}
        </button>
      </Group>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("minYears")} review={review("min_years_experience")}>
          <input
            type="number"
            min={0}
            max={60}
            step="any"
            value={form.min_years_experience}
            onChange={(e) => set({ min_years_experience: e.target.value })}
            className="text-input"
          />
        </Field>
        <Field label={t("salary")} review={review("salary_range")}>
          <input
            maxLength={200}
            value={form.salary_range}
            onChange={(e) => set({ salary_range: e.target.value })}
            className="text-input"
          />
        </Field>
      </div>
      <Field label={t("education")} review={review("education")}>
        <input
          maxLength={2000}
          value={form.education}
          onChange={(e) => set({ education: e.target.value })}
          className="text-input"
        />
      </Field>
      <Field label={t("responsibilitiesInput")} review={review("responsibilities")}>
        <textarea
          rows={5}
          value={form.responsibilities}
          onChange={(e) => set({ responsibilities: e.target.value })}
          className="text-input"
        />
      </Field>

      <Group label={t("weightsPercent")}>
        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["technical", "Technical Fit"],
              ["soft_skills", "Soft Skills"],
              ["experience", "Experience"],
            ] as const
          ).map(([axis, label]) => (
            <Field key={axis} label={label}>
              <input
                type="number"
                min={0}
                max={100}
                required
                value={form.weights[axis]}
                onChange={(e) =>
                  set({ weights: { ...form.weights, [axis]: Math.round(Number(e.target.value)) } })
                }
                className="text-input"
              />
            </Field>
          ))}
        </div>
        <p aria-live="polite" className={total === 100 ? "text-sm" : "text-sm font-semibold"}>
          {total === 100 ? t("total", { total }) : t("totalInvalid", { total })}
        </p>
      </Group>

      {refused !== null && (
        <p role="alert">{refused === 409 ? t("stillParsing") : t("saveFailed")}</p>
      )}
      <button
        type="submit"
        disabled={pending || total !== 100}
        className="self-start button-primary"
      >
        {t("submit")}
      </button>
    </form>
  );
}

const reviewed = (review?: boolean) => (review ? "border-l-4 border-accent-pink pl-3" : "");

/** One labelled input; a Needs review field is highlighted (FR-A1.1). */
function Field({
  label,
  review,
  children,
}: {
  label: string;
  review?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("job");
  return (
    <label className={`flex flex-col gap-1 ${reviewed(review)}`}>
      <span className="flex items-center gap-2 font-medium">
        {label}
        {review && <Badge>{t("needsReview")}</Badge>}
      </span>
      {children}
    </label>
  );
}

/** Several inputs under one caption. */
function Group({
  label,
  review,
  children,
}: {
  label: string;
  review?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("job");
  return (
    <fieldset className={`flex flex-col gap-2 ${reviewed(review)}`}>
      <legend className="flex items-center gap-2 font-medium">
        {label}
        {review && <Badge>{t("needsReview")}</Badge>}
      </legend>
      {children}
    </fieldset>
  );
}
