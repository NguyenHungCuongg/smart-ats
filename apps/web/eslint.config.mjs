import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import prettier from "eslint-config-prettier/flat";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  // eslint-plugin-react 7.x cannot auto-detect the version under ESLint 10 (no context.getFilename).
  // Keep in sync with the react version in package.json.
  { settings: { react: { version: "19.3" } } },
  // Last, so it turns off every rule that would fight Prettier.
  prettier,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
