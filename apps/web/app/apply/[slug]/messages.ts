import type { Translator } from "../../../i18n/messages";

/** What the apply page says for the HTTP status submitApplication returned; null on success. */
export function applyError(t: Translator<"apply">, status: number): string | null {
  switch (status) {
    case 200:
    case 201:
      return null;
    case 400:
      return t("failed");
    case 404:
      return t("notFoundMessage");
    case 409:
      return t("closedMessage");
    case 429:
      return t("rateLimited");
    default:
      return t("failed");
  }
}
