import type { ReactNode } from "react";

/** pill-neutral-dark in micro-cap type (DESIGN.md): a status or category label. */
export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="w-fit rounded-xs bg-surface-night px-2 py-1 text-[10px]/[1.8] font-semibold tracking-[0.25px] whitespace-nowrap text-on-primary uppercase">
      {children}
    </span>
  );
}
