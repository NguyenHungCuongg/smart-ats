"use client";

import { type FormEvent, useState } from "react";

import { apiFetch } from "../../auth";
import type { Job } from "../criteria";
import { ACTION_NAMES, type Action, actionsFor, transitionError } from "../lifecycle";

/** The lifecycle actions valid from the Job's status (FR-A3.1). */
export function StatusActions({ job, onChanged }: { job: Job; onChanged: (job: Job) => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const actions = actionsFor(job.status);
  if (actions.length === 0) return null;

  async function run(action: Action) {
    if (action === "archive" && !window.confirm("Job lưu trữ sẽ chỉ đọc vĩnh viễn. Lưu trữ?")) {
      return;
    }
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}/transitions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    setPending(false);
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) {
      setError(null);
      return onChanged(await response.json());
    }
    setError(transitionError(response.status));
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-3">
        {actions.map((action) => (
          <button
            key={action}
            type="button"
            disabled={pending}
            onClick={() => run(action)}
            className="button-outline"
          >
            {ACTION_NAMES[action]}
          </button>
        ))}
      </div>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

/** The Job's apply deadline; department and location are edited with the criteria. */
export function MetadataForm({ job, onSaved }: { job: Job; onSaved: (job: Job) => void }) {
  const [deadline, setDeadline] = useState(job.apply_deadline ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    const response = await apiFetch(`/api/jobs/${job.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apply_deadline: deadline || null }),
    });
    setPending(false);
    if (response.ok) {
      setError(null);
      return onSaved(await response.json());
    }
    setError(
      response.status === 409
        ? "JD vẫn đang được phân tích hoặc Job đã lưu trữ."
        : "Không lưu được hạn nộp.",
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1">
        <span className="font-medium">Hạn nộp hồ sơ</span>
        <input
          type="date"
          value={deadline}
          onChange={(e) => setDeadline(e.target.value)}
          className="text-input"
        />
      </label>
      <button
        type="submit"
        disabled={pending || deadline === (job.apply_deadline ?? "")}
        className="button-outline"
      >
        Lưu hạn nộp
      </button>
      {error && (
        <p role="alert" className="w-full">
          {error}
        </p>
      )}
    </form>
  );
}
