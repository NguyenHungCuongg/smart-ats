import type { Translator } from "../../i18n/messages";

/** What /login says for the status login() returned; null on success. */
export function loginError(t: Translator<"login">, status: number): string | null {
  switch (status) {
    case 200:
      return null;
    case 401:
      return t("wrongPassword");
    case 429:
      return t("locked");
    case 0:
      return t("offline");
    default:
      return t("failed");
  }
}
