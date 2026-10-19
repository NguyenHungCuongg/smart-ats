import { beforeEach, expect, test, vi } from "vitest";

type Auth = typeof import("./auth");

/** A stand-in for the API: login and refresh hand out numbered tokens; /me accepts the latest. */
function fakeApi() {
  let issued = 0;
  const calls: string[] = [];
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    calls.push(route);
    const token = () => Response.json({ access_token: `token-${++issued}` });
    switch (route) {
      case "POST /api/auth/login":
        return token();
      case "POST /api/auth/refresh":
        return new Headers(init.headers).has("X-Requested-With")
          ? token()
          : new Response(null, { status: 403 });
      case "GET /api/auth/me":
        return new Headers(init.headers).get("Authorization") === `Bearer token-${issued}`
          ? Response.json({ email: "a@b.c" })
          : new Response(null, { status: 401 });
    }
    return new Response(null, { status: 404 });
  });
  return { fetch, calls, expire: () => issued++ };
}

let api: ReturnType<typeof fakeApi>;
let auth: Auth;

beforeEach(async () => {
  api = fakeApi();
  vi.stubGlobal("fetch", api.fetch);
  // The access token lives in module state: start each test from a fresh module.
  vi.resetModules();
  auth = await import("./auth");
});

test("requests carry the access token from login", async () => {
  expect(await auth.login("a@b.c", "pw")).toBe(200);

  expect((await auth.apiFetch("/api/auth/me")).status).toBe(200);
  expect(api.calls).toEqual(["POST /api/auth/login", "GET /api/auth/me"]);
});

test("an expired access token is refreshed once, then the request retried", async () => {
  await auth.login("a@b.c", "pw");
  api.expire();

  expect((await auth.apiFetch("/api/auth/me")).status).toBe(200);
  expect(api.calls.slice(1)).toEqual([
    "GET /api/auth/me",
    "POST /api/auth/refresh",
    "GET /api/auth/me",
  ]);
});

test("after a page load, the refresh cookie restores the session", async () => {
  expect((await auth.apiFetch("/api/auth/me")).status).toBe(200);
});

test("concurrent requests share one refresh: a second would replay a rotated token", async () => {
  const responses = await Promise.all([
    auth.apiFetch("/api/auth/me"),
    auth.apiFetch("/api/auth/me"),
  ]);

  expect(responses.map((r) => r.status)).toEqual([200, 200]);
  expect(api.calls.filter((c) => c === "POST /api/auth/refresh")).toHaveLength(1);
});

test("login reports an unreachable API as status 0", async () => {
  api.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

  expect(await auth.login("a@b.c", "pw")).toBe(0);
});

test("logout waits for a refresh in flight, so the cookie it revokes is the newest", async () => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  const route = api.fetch.getMockImplementation()!;
  api.fetch.mockImplementation(async (url: string, init: RequestInit = {}) => {
    const response = route(url, init);
    if (`${init.method} ${url}` === "POST /api/auth/refresh") await held;
    return response;
  });
  const request = auth.apiFetch("/api/auth/me");
  await vi.waitFor(() => expect(api.calls).toContain("POST /api/auth/refresh"));

  const loggedOut = auth.logout();
  await new Promise((resolve) => setTimeout(resolve, 10));
  expect(api.calls).not.toContain("DELETE /api/auth/refresh");
  release();
  await Promise.all([request, loggedOut]);

  expect(api.calls).toContain("DELETE /api/auth/refresh");
});

test("when refresh fails, the caller gets the 401", async () => {
  api.fetch.mockImplementation(async () => new Response(null, { status: 401 }));

  expect((await auth.apiFetch("/api/auth/me")).status).toBe(401);
});
