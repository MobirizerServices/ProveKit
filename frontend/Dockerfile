# AgentMan frontend image (Next.js standalone). Same-origin: the browser calls /api and
# /v1 on this origin and the Next server rewrites them to the backend. With output:
# "standalone" the rewrite destination is fixed at build time, so the proxy target is a
# build ARG (default = the compose service name). Override with
# --build-arg API_PROXY_TARGET=... when the backend lives elsewhere.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG API_PROXY_TARGET=http://backend:8100
ENV API_PROXY_TARGET=$API_PROXY_TARGET
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3001 NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3001
CMD ["node", "server.js"]
