"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../auth";
import { Badge } from "../badge";
import { useRole } from "../session";
import type { Level } from "./criteria";
import { JOB_STATUSES, type JobStatus } from "./lifecycle";

type JobSummary = {
  id: string;
  title: string;
  level: Level;
  department: string | null;
  location: string | null;
  status: JobStatus;
  application_count: number;
  created_at: string;
};

/** The Jobs the user may see: all of the Workspace's, or a Reviewer's assigned ones. */
export default function JobsPage() {
  const t = useTranslations("jobs");
  const statusName = useTranslations("lifecycle.status");
  const locale = useLocale();
  const role = useRole();
  const [status, setStatus] = useState<JobStatus | "">("");
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);

  useEffect(() => {
    const query = status ? `?status=${status}` : "";
    apiFetch(`/api/jobs${query}`).then(async (response) => {
      if (response.status === 401) window.location.replace("/login");
      else if (response.ok) setJobs(await response.json());
    });
  }, [status]);

  return (
    <main className="flex-1">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
          {role && role !== "REVIEWER" && (
            <Link href="/jobs/new" className="button-primary">
              {t("create")}
            </Link>
          )}
        </div>
        <label className="flex flex-col gap-1 self-start">
          <span className="font-medium">{t("status")}</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as JobStatus | "")}
            className="text-input"
          >
            <option value="">{t("all")}</option>
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusName(s)}
              </option>
            ))}
          </select>
        </label>
        {!jobs ? (
          <div aria-busy="true" aria-label={t("loading")} className="flex flex-col gap-3">
            <div className="h-8 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : jobs.length === 0 ? (
          <p>{role === "REVIEWER" ? t("noneAssigned") : status ? t("noneInStatus") : t("none")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-hairline-cloud">
                  <th className="py-2 font-medium">{t("jobTitle")}</th>
                  <th className="py-2 font-medium">{t("department")}</th>
                  <th className="py-2 font-medium">{t("location")}</th>
                  <th className="py-2 font-medium">{t("status")}</th>
                  <th className="py-2 font-medium">{t("applications")}</th>
                  <th className="py-2 font-medium">{t("created")}</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className="border-b border-hairline-cloud">
                    <td className="py-2">
                      <Link href={`/jobs/${job.id}`} className="font-medium underline">
                        {job.title}
                      </Link>{" "}
                      <span className="font-mono">{job.level}</span>
                    </td>
                    <td className="py-2">{job.department ?? "—"}</td>
                    <td className="py-2">{job.location ?? "—"}</td>
                    <td className="py-2">
                      <Badge>{statusName(job.status)}</Badge>
                    </td>
                    <td className="py-2">{job.application_count.toLocaleString(locale)}</td>
                    <td className="py-2">{new Date(job.created_at).toLocaleString(locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
