import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AcceptForm } from "./form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("accept");
  return {
    title: t("metaTitle"),
    // The URL carries the invitation token: no Referer header may take it anywhere.
    referrer: "no-referrer",
  };
}

export default function AcceptInvitationPage() {
  return <AcceptForm />;
}
