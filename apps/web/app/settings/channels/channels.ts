import type { Translator } from "../../../i18n/messages";

export type FacebookConnection = {
  id: string;
  channel: "FACEBOOK_PAGE";
  external_id: string;
  name: string;
  connected_by: string;
  connected_by_name: string;
  connected_at: string;
};

export type FacebookCandidatePage = {
  id: string;
  name: string;
};

export type ChannelErrorCode =
  "cancelled" | "no_role" | "no_pages" | "oauth_failed" | "invalid_selection";

/**
 * Maps callback error codes to user-friendly translated error messages (SAD §5.6).
 */
export function getChannelErrorMessage(
  t: Translator<"channels">,
  errorCode: string | null,
): string | null {
  if (!errorCode) return null;
  switch (errorCode) {
    case "cancelled":
      return t("cancelled");
    case "no_role":
      return t("noRole");
    case "no_pages":
      return t("noPages");
    case "invalid_selection":
      return t("invalidSelection");
    case "oauth_failed":
    default:
      return t("oauthFailed");
  }
}
