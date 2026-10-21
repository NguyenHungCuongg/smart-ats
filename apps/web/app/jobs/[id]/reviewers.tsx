"use client";

import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";

type Reviewer = { id: string; full_name: string; email: string; assigned: boolean };

/** Choose which of the Workspace's Reviewers see the Job (Reviewer Assignment). */
export function Reviewers({ jobId }: { jobId: string }) {
  const t = useTranslations("reviewers");
  const [reviewers, setReviewers] = useState<Reviewer[] | null>(null);
  // The ids checked now; saved replaces the Job's whole list.
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  // Whether the last save went through, worded at render in the language shown.
  const [saved, setSaved] = useState<boolean | null>(null);

  function show(list: Reviewer[]) {
    setReviewers(list);
    setChosen(new Set(list.filter((r) => r.assigned).map((r) => r.id)));
  }

  useEffect(() => {
    apiFetch(`/api/jobs/${jobId}/reviewers`).then(async (r) => r.ok && show(await r.json()));
  }, [jobId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    const response = await apiFetch(`/api/jobs/${jobId}/reviewers`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_ids: [...chosen] }),
    });
    setPending(false);
    if (response.ok) {
      show(await response.json());
      setSaved(true);
    } else {
      // 422: a Reviewer was revoked or re-roled meanwhile.
      setSaved(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">{t("title")}</h2>
      {!reviewers ? (
        <div aria-busy="true" className="h-16 animate-pulse rounded-md bg-hairline-cloud" />
      ) : reviewers.length === 0 ? (
        <p className="text-sm">{t("none")}</p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm">{t("note")}</legend>
            {reviewers.map((r) => (
              <label key={r.id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={chosen.has(r.id)}
                  onChange={(e) => {
                    const next = new Set(chosen);
                    if (e.target.checked) next.add(r.id);
                    else next.delete(r.id);
                    setChosen(next);
                  }}
                />
                {r.full_name} <span className="text-sm">({r.email})</span>
              </label>
            ))}
          </fieldset>
          {saved !== null && <p role="status">{saved ? t("saved") : t("failed")}</p>}
          <button type="submit" disabled={pending} className="self-start button-outline">
            {t("save")}
          </button>
        </form>
      )}
    </section>
  );
}
