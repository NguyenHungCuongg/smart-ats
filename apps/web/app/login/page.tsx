"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { login } from "../auth";
import { loginError } from "./messages";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    const status = await login(String(form.get("email")), String(form.get("password")));
    setPending(false);
    if (status === 200) router.replace("/");
    else setError(loginError(status));
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={onSubmit} className="flex w-full max-w-80 flex-col gap-4">
        <h1 className="heading-display text-3xl font-semibold">Đăng nhập</h1>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Email</span>
          <input name="email" type="email" autoComplete="email" required className="text-input" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Mật khẩu</span>
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
          Đăng nhập
        </button>
      </form>
    </main>
  );
}
