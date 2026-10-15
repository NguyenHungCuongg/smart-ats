<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# Web App Guidelines

## Design System Enforcement

All UI implementation in `apps/web` must strictly adhere to [`DESIGN.md`](../../DESIGN.md) at the repository root.

- **Tokens & Colors**: Use only colors from the Smart ATS palette defined in `DESIGN.md`:
  - Canvas / Surface: Midnight Violet (`#150f23` / `{colors.primary}`, `{colors.surface-night}`), Ink Violet (`#1f1633` / `{colors.ink-deep}`), Light Canvas (`#ffffff` / `{colors.surface-canvas-light}`).
  - Signature Accent: Electric Lime (`#c2ef4e` / `{colors.accent-lime}`).
  - Secondary: Hot Pink (`#fa7faa` / `{colors.accent-pink}`), Deep Violet (`#422082`), Hairline Violet (`#362d59`), Hairline Cloud (`#e5e7eb`).
- **Typography Architecture**:
  - Display / Headlines: **Archivo** (Semi-Condensed, bold/black weights 600–900).
  - UI / Body / Buttons / Form labels: **Rubik** (Google Fonts).
  - Code blocks / Monospace / Token chips: **JetBrains Mono**.
  - All button labels and eyebrows run in uppercase with `tracking-[0.2px]`.
- **Dark Mode & Contrast Invariance (CRITICAL)**:
  - Text inside `{colors.accent-lime}` highlight chips MUST ALWAYS be dark (`#1f1633` / `{colors.ink-deep}`) across both Light and Dark modes. Never inherit white text.
  - Text inside white-filled buttons (`button-inverted`) MUST ALWAYS be dark (`#1f1633` / `{colors.ink-deep}`) across both Light and Dark modes. Never inherit white text.
  - Feature cards (`card-feature-dark`, `card-spotlight-violet`) are permanently dark surfaces; never invert them into solid white boxes in Dark Mode.
  - Standard pricing cards (`card-pricing`) in Dark Mode use `{colors.surface-night}` with a 1px `{colors.hairline-violet}` border and contrasting button boundaries.
- **Mandatory Agent Check**: Before writing, generating, or modifying any UI component or page, the agent MUST inspect `DESIGN.md`. Ad-hoc styling, unapproved colors, and banned anti-patterns in `DESIGN.md` are strictly prohibited.
