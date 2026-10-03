# syntax=docker/dockerfile:1
# --- build ---
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Leave empty to call the API on the same origin through nginx (recommended).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- serve ---
FROM nginxinc/nginx-unprivileged:1.27-alpine
# Address of the Newsforge API inside your network.
ENV API_UPSTREAM=http://api:8000 \
    CSP_CONNECT_SRC="'self'"
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
