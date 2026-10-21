import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ApplyForm } from "./form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("apply");
  return {
    title: t("metaTitle"),
  };
}

export default async function PublicApplyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <ApplyForm slug={slug} />;
}
