import Link from "next/link";

import { Session } from "./session";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4">
      <h1 className="text-3xl font-semibold">Smart ATS</h1>
      <Session />
      <Link href="/jobs/new" className="underline">
        Tạo Job từ JD
      </Link>
      <Link href="/settings/members" className="underline">
        Thành viên Workspace
      </Link>
    </main>
  );
}
