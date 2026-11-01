import { cache } from "react";

import type { PublicJob } from "./form";

export const fetchPublicJob = cache(async (slug: string): Promise<PublicJob | null> => {
  const baseUrl = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL;
  try {
    const res = await fetch(`${baseUrl}/api/apply/${slug}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.error(`Failed to fetch public job for slug '${slug}':`, err);
    return null;
  }
});

export function getPublicApplyUrl(slug: string): string {
  const base = process.env.WEB_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "https://localhost";
  return `${base.replace(/\/api\/?$/, "")}/apply/${slug}`;
}
