# ============================================================================
# ElderLife AI — frontend image
#
# Build:  docker build -t elderlife-frontend ./frontend
# Run:    docker run --rm -p 5173:80 elderlife-frontend
#
# Two stages:
#   1. `build`  — Node compiles the TypeScript/React app into static files.
#   2. `runtime` — nginx serves those files. Node and node_modules are NOT in
#      the final image, which keeps it small and removes a large attack surface.
#
# Why nginx and not `npm run dev`: the Vite dev server is a development tool.
# It should not be what serves the application to a user.
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — build the static assets
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Install dependencies first so this layer is cached while source changes.
# `npm ci` is used rather than `npm install` because it installs exactly the
# versions in package-lock.json — a reproducible build.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the frontend and build.
COPY . .

# The API URL is compiled into the JavaScript bundle at build time — Vite
# variables are not read at runtime. This default matches the browser's view of
# the world: it talks to the backend published on the host's port 8000.
# Override with:  docker build --build-arg VITE_API_BASE_URL=... ./frontend
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — serve the static files
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Our server configuration replaces the default nginx one.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Security headers live in their own file because nginx does not merge
# `add_header` across levels; the server config `include`s this from every
# location block. It must sit next to default.conf, which is where the
# `include` directive looks for it.
COPY security-headers.conf /etc/nginx/conf.d/security-headers.conf

# The compiled application from stage 1. Nothing from stage 1's node_modules
# or source tree is carried over.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# `wget` ships with the alpine image, so no extra package is needed here.
# 127.0.0.1 is used rather than `localhost`: inside this container `localhost`
# resolves to IPv6 ::1 first, while nginx listens on IPv4, and the resulting
# "connection refused" would hold the container permanently unhealthy.
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
