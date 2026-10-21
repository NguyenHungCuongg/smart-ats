import type vi from "../messages/vi.json";
import type { Locale } from "./locale";

// Message keys and locales are typed: a key missing from the catalog fails typecheck.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof vi;
  }
}
