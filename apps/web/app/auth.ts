// Browser-side session (ADR-0003): the access token lives only in this module's memory;
// the refresh token is an HttpOnly cookie the browser sends to /api/auth/refresh by itself.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
// The cookie endpoints reject requests without it, which cross-site forms cannot send.
const CSRF_HEADER = { "X-Requested-With": "fetch" };

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;

/** Returns the HTTP status: 200 on success, 401 bad credentials, 429 temporarily locked. */
export async function login(email: string, password: string): Promise<number> {
  const response = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (response.ok) accessToken = (await response.json()).access_token;
  return response.status;
}

/** Revokes the refresh token family on the server and forgets the access token. */
export async function logout(): Promise<void> {
  await fetch(`${API_URL}/api/auth/refresh`, { method: "DELETE", headers: CSRF_HEADER });
  accessToken = null;
}

/** fetch() against the API as the signed-in user; on 401, refreshes once and retries. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = () => {
    const headers = new Headers(init.headers);
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    return fetch(`${API_URL}${path}`, { ...init, headers });
  };
  const response = await send();
  return response.status === 401 && (await refresh()) ? send() : response;
}

// Each refresh rotates the cookie, and the API treats a replayed old one as theft and revokes
// the whole family. So one refresh at a time: shared within this tab, and the Web Lock makes
// other tabs wait until the browser holds the new cookie.
function refresh(): Promise<boolean> {
  refreshing ??= navigator.locks
    .request("smart-ats-refresh", async () => {
      const response = await fetch(`${API_URL}/api/auth/refresh`, {
        method: "POST",
        headers: CSRF_HEADER,
      });
      accessToken = response.ok ? (await response.json()).access_token : null;
      return response.ok;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}
