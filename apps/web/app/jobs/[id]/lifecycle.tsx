"use client";

import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { apiFetch } from "../../auth";
import type { Job } from "../criteria";
import { type Action, actionsFor, transitionError } from "../lifecycle";

/** The lifecycle actions valid from the Job's status (FR-A3.1). */
export function StatusActions({ job, onChanged }: { job: Job; onChanged: (job: Job) => void }) {
  const t = useTranslations("lifecycle");
  const [pending, setPending] = useState(false);
  // The refused status, worded at render in the language shown.
  const [refused, setRefused] = useState<number | null>(null);
  const actions = actionsFor(job.status);
  if (actions.length === 0) return null;

  async function run(action: Action) {
    if (action === "archive" && !window.confirm(t("confirmArchive"))) {
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
      setRefused(null);
      return onChanged(await response.json());
    }
    setRefused(response.status);
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
            {t(`action.${action}`)}
          </button>
        ))}
      </div>
      {refused !== null && <p role="alert">{transitionError(t, refused)}</p>}
    </div>
  );
}

/** The Job's apply deadline; department and location are edited with the criteria. */
export function MetadataForm({ job, onSaved }: { job: Job; onSaved: (job: Job) => void }) {
  const t = useTranslations("lifecycle");
  const [deadline, setDeadline] = useState(job.apply_deadline ?? "");
  const [pending, setPending] = useState(false);
  const [refused, setRefused] = useState<number | null>(null);

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
      setRefused(null);
      return onSaved(await response.json());
    }
    setRefused(response.status);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1">
        <span className="font-medium">{t("deadline")}</span>
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
        {t("saveDeadline")}
      </button>
      {refused !== null && (
        <p role="alert" className="w-full">
          {refused === 409 ? t("deadlineConflict") : t("deadlineFailed")}
        </p>
      )}
    </form>
  );
}
