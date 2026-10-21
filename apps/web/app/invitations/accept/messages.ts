import type { Translator } from "../../../i18n/messages";

/** What the accept page says for the status acceptInvitation() returned; null on success. */
export function acceptError(t: Translator<"accept">, status: number): string | null {
  switch (status) {
    case 200:
      return null;
    case 400:
      return t("invalid");
    case 422:
      return t("checkFields");
    case 0:
      return t("offline");
    default:
      return t("failed");
  }
}
