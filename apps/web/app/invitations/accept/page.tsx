import type { Metadata } from "next";

import { AcceptForm } from "./form";

export const metadata: Metadata = {
  title: "Nhận lời mời · Smart ATS",
  // The URL carries the invitation token: no Referer header may take it anywhere.
  referrer: "no-referrer",
};

export default function AcceptInvitationPage() {
  return <AcceptForm />;
}
