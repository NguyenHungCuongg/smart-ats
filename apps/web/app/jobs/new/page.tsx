"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { apiFetch } from "../../auth";

const ERRORS: Record<number, "forbidden" | "tooLarge" | "unsupported" | "fileOrText"> = {
  403: "forbidden",
  413: "tooLarge",
  415: "unsupported",
  422: "fileOrText",
};

/** Upload a JD Document or paste its text (FR-A1.1); the Job page then follows the parse. */
export default function NewJobPage() {
  const t = useTranslations("newJob");
  const router = useRouter();
  // The refused status, worded at render in the language shown.
  const [refused, setRefused] = useState<number | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = new FormData();
    const file = form.get("file");
    if (file instanceof File && file.size > 0) body.set("file", file);
    const text = String(form.get("text") ?? "");
    if (text.trim()) body.set("text", text);

    setPending(true);
    const response = await apiFetch("/api/jobs", { method: "POST", body });
    if (response.status === 401) return window.location.replace("/login");
    if (response.ok) return router.push(`/jobs/${(await response.json()).id}`);
    setPending(false);
    setRefused(response.status);
  }

  return (
    <main className="flex-1">
      <form onSubmit={onSubmit} className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
        <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("file")}</span>
          <input name="file" type="file" accept=".pdf,.docx,.txt" className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("text")}</span>
          <textarea name="text" rows={12} className="text-input" />
        </label>
        {refused !== null && <p role="alert">{t(ERRORS[refused] ?? "failed")}</p>}
        <button type="submit" disabled={pending} className="self-start button-primary">
          {t("submit")}
        </button>
      </form>
    </main>
  );
}
