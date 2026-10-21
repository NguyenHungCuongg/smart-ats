import { expect, test } from "vitest";

import { decideLocale } from "./locale";

test("a valid cookie wins, on any page", () => {
  expect(decideLocale("en", "vi", false)).toBe("en");
  expect(decideLocale("vi", "en-US,en;q=0.9", true)).toBe("vi");
});

test("without a cookie a public page follows the browser's languages in order", () => {
  expect(decideLocale(undefined, "en-US,en;q=0.9,vi;q=0.8", true)).toBe("en");
  expect(decideLocale(undefined, "fr;q=0.9,vi;q=0.5,en;q=0.3", true)).toBe("vi");
  expect(decideLocale(undefined, "vi;q=0.2,EN-gb;q=0.7", true)).toBe("en");
  expect(decideLocale(undefined, "fr, de", true)).toBe("vi");
  // q=0 means "not this one"; a malformed weight counts for nothing.
  expect(decideLocale(undefined, "en;q=0, vi;q=0.1", true)).toBe("vi");
  expect(decideLocale(undefined, "en;q=abc, vi;q=0.1", true)).toBe("vi");
  expect(decideLocale(undefined, null, true)).toBe("vi");
});

test("a page that is not public ignores Accept-Language", () => {
  expect(decideLocale(undefined, "en-US,en;q=0.9", false)).toBe("vi");
});

test("an unsupported cookie falls through to the same rules", () => {
  expect(decideLocale("fr", "en", true)).toBe("en");
  expect(decideLocale("fr", "en", false)).toBe("vi");
});
