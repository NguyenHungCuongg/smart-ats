"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { login } from "../auth";

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
    else if (status === 429) setError("Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau.");
    else setError("Email hoặc mật khẩu không đúng.");
  }

  return (
    <main className="flex min-h-screen items-center justify-center">
      <form onSubmit={onSubmit} className="flex w-80 flex-col gap-3">
        <h1 className="text-2xl font-semibold">Đăng nhập</h1>
        <input name="email" type="email" placeholder="Email" required className="border p-2" />
        <input
          name="password"
          type="password"
          placeholder="Mật khẩu"
          required
          className="border p-2"
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button type="submit" disabled={pending} className="bg-black p-2 text-white">
          Đăng nhập
        </button>
      </form>
    </main>
  );
}
