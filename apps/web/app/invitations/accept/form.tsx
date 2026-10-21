"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { acceptInvitation } from "../../auth";
import { acceptError } from "./messages";

/** Name and password for the invited Member's account; the token stays in the URL until sent. */
export function AcceptForm() {
  const t = useTranslations("accept");
  const router = useRouter();
  // The status, not its message: switching language rewords an error already shown.
  const [failed, setFailed] = useState<number | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    // Read here rather than rendered: the token never enters the page's state or markup.
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    setPending(true);
    const status = await acceptInvitation(
      token,
      String(form.get("full_name")),
      String(form.get("password")),
    );
    setPending(false);
    if (status === 200) router.replace("/");
    else setFailed(status);
  }

  const error = failed === null ? null : acceptError(t, failed);
  return (
    <main className="flex flex-1 items-center justify-center px-4">
      <form onSubmit={onSubmit} className="flex w-full max-w-80 flex-col gap-4">
        <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
        <p>{t("intro")}</p>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("fullName")}</span>
          <input
            name="full_name"
            autoComplete="name"
            required
            maxLength={200}
            className="text-input"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("password")}</span>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
            maxLength={256}
            className="text-input"
          />
        </label>
        {error && (
          <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
            {error}
          </p>
        )}
        <button type="submit" disabled={pending} className="button-primary">
          {t("submit")}
        </button>
      </form>
    </main>
  );
}
