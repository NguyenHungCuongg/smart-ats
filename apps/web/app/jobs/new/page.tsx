"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { apiFetch } from "../../auth";

const ERRORS: Record<number, string> = {
  403: "Chỉ Recruiter được tạo Job.",
  413: "File JD vượt quá 10 MB.",
  415: "JD phải là file PDF, DOCX hoặc văn bản thuần.",
  422: "Chọn một file JD hoặc dán nội dung JD, không cả hai.",
};

/** Upload a JD Document or paste its text (FR-A1.1); the Job page then follows the parse. */
export default function NewJobPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
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
    setError(ERRORS[response.status] ?? "Không tạo được Job. Vui lòng thử lại.");
  }

  return (
    <main className="min-h-screen">
      <form onSubmit={onSubmit} className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
        <h1 className="heading-display text-3xl font-semibold">Tạo Job từ JD</h1>
        <label className="flex flex-col gap-1">
          <span className="font-medium">File JD (PDF, DOCX, TXT, tối đa 10 MB)</span>
          <input name="file" type="file" accept=".pdf,.docx,.txt" className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Hoặc dán nội dung JD</span>
          <textarea name="text" rows={12} className="text-input" />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={pending} className="self-start button-primary">
          Tạo Job
        </button>
      </form>
    </main>
  );
}
