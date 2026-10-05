FROM node:24-bookworm-slim AS dependencies
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM dependencies AS build
COPY web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN groupadd --system --gid 1001 research && useradd --system --uid 1001 --gid 1001 research
COPY --from=build --chown=1001:1001 /app/.next/standalone ./
COPY --from=build --chown=1001:1001 /app/.next/static ./.next/static
USER 1001:1001
EXPOSE 3000
CMD ["node", "server.js"]
