import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

// Every color and corner comes from the DESIGN.md tokens in globals.css.
const sources = readdirSync(import.meta.dirname, { recursive: true, encoding: "utf8" })
  .filter((path) => /\.tsx?$/.test(path) && !/\.test\.tsx?$/.test(path))
  .map((path) => [path, readFileSync(join(import.meta.dirname, path), "utf8")] as const);

test("no page writes a color of its own", () => {
  const tailwind =
    "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|" +
    "blue|indigo|violet|purple|fuchsia|pink|rose";
  const adHoc = new RegExp(
    `#[0-9a-f]{3,8}\\b|rgba?\\(|-(?:black|white)\\b|-(?:${tailwind})-\\d{2,3}\\b`,
    "i",
  );
  expect(sources.filter(([, code]) => adHoc.test(code)).map(([path]) => path)).toEqual([]);
});
