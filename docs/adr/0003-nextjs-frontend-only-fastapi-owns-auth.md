# Next.js is a pure frontend; FastAPI owns auth and all business logic

The Next.js app renders UI and calls the FastAPI REST API from the browser through TanStack Query. It does not use Server Actions or route handlers as a backend-for-frontend. One backend keeps RBAC, RLS context and audit in a single place, and two students cannot afford to maintain a second server layer.

## Consequences

- The access token (15 min) lives in memory. The refresh token (7 days, rotated, reuse detection by token family) is an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/auth/refresh` on the API's site. The refresh endpoint also requires a custom header against CSRF.
- Progress is pushed with Server-Sent Events. `EventSource` cannot send an `Authorization` header, so the client first obtains a single-use, 60-second SSE ticket and passes it as a query parameter.
