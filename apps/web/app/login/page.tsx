"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { login } from "../auth";
import { loginError } from "./messages";

export default function LoginPage() {
  const t = useTranslations("login");
  const router = useRouter();
  // The status, not its message: switching language rewords an error already shown.
  const [failed, setFailed] = useState<number | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    const status = await login(String(form.get("email")), String(form.get("password")));
    setPending(false);
    if (status === 200) router.replace("/");
    else setFailed(status);
  }

  const error = failed === null ? null : loginError(t, failed);
  return (
    <main className="flex flex-1 items-center justify-center px-4">
      <form onSubmit={onSubmit} className="flex w-full max-w-80 flex-col gap-4">
        <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("email")}</span>
          <input name="email" type="email" autoComplete="email" required className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">{t("password")}</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
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
