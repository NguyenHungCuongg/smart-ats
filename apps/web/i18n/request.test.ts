import { expect, test, vi } from "vitest";

import requestConfig from "./request";

vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
  headers: async () => ({ get: () => "en-US,en;q=0.9" }),
}));
vi.mock("next-intl/server", () => ({ getRequestConfig: <T>(create: T) => create }));

test("pages other than Public Apply stay Vietnamese whatever the browser asks", async () => {
  const config = await requestConfig({ requestLocale: Promise.resolve(undefined) });
  expect(config.locale).toBe("vi");
});
