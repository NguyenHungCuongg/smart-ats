"use client";

import { useEffect, useState } from "react";

import { apiFetch, logout } from "./auth";

type Me = { email: string; full_name: string; role: string };

/** The signed-in user with a logout button; sends anyone signed out to /login. */
export function Session() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    apiFetch("/api/auth/me").then(async (response) => {
      if (response.ok) setMe(await response.json());
      else window.location.replace("/login");
    });
  }, []);

  if (!me) return null;
  return (
    <div className="flex items-center gap-3">
      <span>
        {me.full_name} ({me.email})
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          window.location.replace("/login");
        }}
        className="border px-2 py-1"
      >
        Đăng xuất
      </button>
    </div>
  );
}
