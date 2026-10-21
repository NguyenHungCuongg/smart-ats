import Link from "next/link";
import { useTranslations } from "next-intl";

import { Session } from "./session";

export default function Home() {
  const t = useTranslations("home");
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4">
      <h1 className="text-3xl font-semibold">Smart ATS</h1>
      <Session />
      <Link href="/jobs" className="underline">
        {t("jobs")}
      </Link>
      <Link href="/jobs/new" className="underline">
        {t("newJob")}
      </Link>
      <Link href="/settings/members" className="underline">
        {t("members")}
      </Link>
    </main>
  );
}
