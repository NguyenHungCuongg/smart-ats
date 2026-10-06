import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import Home from "./page";

test("home page shows the product name", () => {
  expect(renderToStaticMarkup(<Home />)).toContain("Smart ATS");
});
