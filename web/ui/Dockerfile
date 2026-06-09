# Next.js frontend — multi-stage, standalone output for a small runtime image.
FROM node:20-slim AS builder
WORKDIR /app
RUN corepack enable

# Install deps against the lockfile (cached unless the lockfile changes).
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# BACKEND_URL is baked into the rewrite at build time; also set at runtime
# (server components read it). Compose passes both.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
RUN pnpm build

FROM node:20-slim AS runner
WORKDIR /app
# No fixed PORT: the platform injects $PORT (Render/Railway); Next's standalone
# server.js falls back to 3000 when unset (compose). Bind all interfaces.
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0
# Standalone server + static assets only — no node_modules bloat.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
