import type { ReactNode } from "react";
import { DegradedBanner } from "./degraded-banner";

export default function JobsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <DegradedBanner />
      {children}
    </>
  );
}
