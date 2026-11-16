# syntax=docker/dockerfile:1
# Gateway image: nginx routing /api and /mcp to the backend and everything else to the frontend.
# Builds from the repo root, like all our images:
#   docker build -f services/gateway/Dockerfile .
# Base images are pinned to exact versions in the FROM lines, where Dependabot updates them.

FROM nginx:1.31.7-alpine
# nginx renders /etc/nginx/templates/*.template into conf.d/ at startup.
COPY services/gateway/nginx.conf.template /etc/nginx/templates/default.conf.template
# Where to route; defaults match the dev servers (uvicorn on 8000, Vite on 5173).
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    DEMO_TOKEN="" \
    BACKEND_HOST=backend \
    BACKEND_PORT=8000 \
    FRONTEND_HOST=frontend \
    FRONTEND_PORT=5173
