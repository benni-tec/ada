# syntax=docker/dockerfile:1
# Frontend image: nginx serving the built single-page app. The gateway sits in front of it.
# Builds from the repo root, like all our images:
#   docker build -f services/frontend/Dockerfile .
# Base images are pinned to exact versions in the FROM lines, where Dependabot updates them.
# Keep Node and pnpm in line with mise.toml.

FROM node:26.13.1-slim AS build
RUN npm install --global pnpm@12.11.2
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY services/frontend/package.json services/frontend/
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter frontend
COPY services/frontend services/frontend
RUN pnpm --filter frontend build

FROM nginx:1.31.8-alpine
# nginx renders /etc/nginx/templates/*.template into conf.d/ at startup.
COPY services/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
# Same port as the Vite dev server.
ENV PORT=5173
EXPOSE 5173
COPY --from=build /repo/services/frontend/dist /usr/share/nginx/html
