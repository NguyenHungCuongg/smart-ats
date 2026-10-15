---
description: Enforce Smart ATS UI Design System (DESIGN.md) for all frontend and UI work.
always_on: true
---

# UI Design System Enforcement

When creating, editing, or reviewing any frontend, web, UI, or styling code in `apps/web`:

1. **Mandatory Reference:** You MUST read [`DESIGN.md`](../../DESIGN.md) at the repository root before creating or modifying any components, layouts, or stylesheets.
2. **Color Tokens:** Use only colors from the Smart ATS palette defined in `DESIGN.md`:
   - Primary Surface / Buttons: Midnight Violet (`#150f23` / `{colors.primary}`)
   - Dark Canvas / Body Ink on light: Ink Violet (`#1f1633` / `{colors.ink-deep}`)
   - Signature Highlight: Electric Lime (`#c2ef4e` / `{colors.accent-lime}`)
   - Secondary Punctuation: Hot Pink (`#fa7faa` / `{colors.accent-pink}`)
   - Accents & Hairlines: Deep Violet (`#422082`), Mid Violet (`#79628c`), Hairline Violet (`#362d59`), Hairline Cloud (`#e5e7eb`)
3. **Typography Architecture:**
   - Display / Headlines: **Archivo** (Semi-Condensed, bold/black weights 600–900).
   - UI / Body / Buttons / Form labels: **Rubik** (Google Fonts).
   - Code blocks / Monospace / Token chips: **JetBrains Mono**.
   - Buttons and eyebrows must run uppercase with `tracking-[0.2px]`.
4. **Dark Mode & Contrast Invariance (CRITICAL):**
   - Text inside `{colors.accent-lime}` highlight chips MUST ALWAYS be dark (`#1f1633` / `{colors.ink-deep}`) across both Light and Dark modes. Never inherit white text.
   - Text inside white-filled buttons (`button-inverted`) MUST ALWAYS be dark (`#1f1633` / `{colors.ink-deep}`) across both Light and Dark modes. Never inherit white text.
   - Feature cards (`card-feature-dark`, `card-spotlight-violet`) are permanently dark surfaces; never invert them into solid white boxes in Dark Mode.
   - Standard pricing cards (`card-pricing`) in Dark Mode use `{colors.surface-night}` with a 1px `{colors.hairline-violet}` border and contrasting button boundaries.
5. **Banned Patterns (Anti-Patterns):**
   - No generic system fonts (Inter, Arial, Times New Roman, Roboto).
   - No ad-hoc neon colors or purple glowing drop shadows.
   - No arbitrary Tailwind utility colors outside the token palette.
   - No circular spinners for loading (use skeletal loaders matching layout dimensions).
