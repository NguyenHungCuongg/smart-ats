"use client";

import { useEffect, useState } from "react";

export function useCopied(timeout = 2000) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => setCopied(false), timeout);
      return () => clearTimeout(timer);
    }
  }, [copied, timeout]);

  const copy = async (text: string): Promise<boolean> => {
    if (!text) return false;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      return true;
    } catch {
      return false;
    }
  };

  return { copied, copy };
}

export function clientPublicApplyUrl(slug: string | null | undefined): string {
  if (!slug || typeof window === "undefined") return "";
  return `${window.location.origin}/apply/${slug}`;
}
