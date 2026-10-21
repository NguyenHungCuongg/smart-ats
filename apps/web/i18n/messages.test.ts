import { expect, test } from "vitest";

import en from "../messages/en.json";
import vi from "../messages/vi.json";

type Catalog = { [key: string]: string | Catalog };

const keys = (catalog: Catalog, prefix = ""): string[] =>
  Object.entries(catalog).flatMap(([key, value]) =>
    typeof value === "string" ? [prefix + key] : keys(value, `${prefix}${key}.`),
  );

test("vi and en have the same keys, so no page shows a missing translation", () => {
  expect(keys(en).sort()).toEqual(keys(vi).sort());
});
