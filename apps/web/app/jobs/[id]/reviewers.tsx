"use client";

import { type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";

type Reviewer = { id: string; full_name: string; email: string; assigned: boolean };

/** Choose which of the Workspace's Reviewers see the Job (Reviewer Assignment). */
export function Reviewers({ jobId }: { jobId: string }) {
  const [reviewers, setReviewers] = useState<Reviewer[] | null>(null);
  // The ids checked now; saved replaces the Job's whole list.
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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
      setMessage("Đã lưu danh sách Reviewer.");
    } else {
      // 422: a Reviewer was revoked or re-roled meanwhile.
      setMessage("Không lưu được. Tải lại trang để xem danh sách Reviewer mới nhất.");
    }
  }

  return (
    <section className="flex flex-col gap-3 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">Reviewer</h2>
      {!reviewers ? (
        <div aria-busy="true" className="h-16 animate-pulse rounded-md bg-hairline-cloud" />
      ) : reviewers.length === 0 ? (
        <p className="text-sm">
          Workspace chưa có Reviewer nào. Company Admin mời Reviewer ở trang Thành viên.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm">Reviewer được gán chỉ xem Job này, không sửa.</legend>
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
          {message && <p role="status">{message}</p>}
          <button type="submit" disabled={pending} className="self-start button-outline">
            Lưu Reviewer
          </button>
        </form>
      )}
    </section>
  );
}
