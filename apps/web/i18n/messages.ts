import type { useTranslations } from "next-intl";

import en from "../messages/en.json";
import vi from "../messages/vi.json";
import type { Locale } from "./locale";

export const CATALOGS: Record<Locale, typeof vi> = { vi, en };

type Namespace = NonNullable<Parameters<typeof useTranslations>[0]>;

/** What useTranslations(namespace) returns: message functions take one, so tests can pass
 * createTranslator's for either language. */
export type Translator<N extends Namespace> = ReturnType<typeof useTranslations<N>>;
