"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "../auth";
import { Badge } from "../badge";
import { useRole } from "../session";
import type { Level } from "./criteria";
import { JOB_STATUSES, type JobStatus, STATUS_NAMES } from "./lifecycle";

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
    <main className="min-h-screen">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 className="heading-display text-3xl font-semibold">Job</h1>
          {role && role !== "REVIEWER" && (
            <Link href="/jobs/new" className="button-primary">
              Tạo Job
            </Link>
          )}
        </div>
        <label className="flex flex-col gap-1 self-start">
          <span className="font-medium">Trạng thái</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as JobStatus | "")}
            className="text-input"
          >
            <option value="">Tất cả</option>
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_NAMES[s]}
              </option>
            ))}
          </select>
        </label>
        {!jobs ? (
          <div aria-busy="true" aria-label="Đang tải Job" className="flex flex-col gap-3">
            <div className="h-8 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : jobs.length === 0 ? (
          <p>
            {role === "REVIEWER"
              ? "Bạn chưa được gán Job nào."
              : status
                ? "Không có Job nào ở trạng thái này."
                : "Chưa có Job nào."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-hairline-cloud">
                  <th className="py-2 font-medium">Chức danh</th>
                  <th className="py-2 font-medium">Phòng ban</th>
                  <th className="py-2 font-medium">Địa điểm</th>
                  <th className="py-2 font-medium">Trạng thái</th>
                  <th className="py-2 font-medium">Application</th>
                  <th className="py-2 font-medium">Tạo lúc</th>
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
                      <Badge>{STATUS_NAMES[job.status]}</Badge>
                    </td>
                    <td className="py-2">{job.application_count}</td>
                    <td className="py-2">{new Date(job.created_at).toLocaleString("vi-VN")}</td>
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
