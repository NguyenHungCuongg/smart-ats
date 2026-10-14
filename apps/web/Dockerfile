# Development image for the web app. Build context: repo root.
FROM node:24.21.0-trixie-slim
# No git hooks to install in a container.
ENV HUSKY=0
RUN corepack enable

WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

WORKDIR /repo/apps/web
COPY apps/web/ ./
CMD ["pnpm", "dev"]
