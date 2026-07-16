# AgentMan frontend image (Next.js standalone). Same-origin by default: the browser calls
# /api and /v1 on this origin and Next.js rewrites them to API_PROXY_TARGET at runtime, so
# ONE image works in every environment (no baked-in backend URL).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3001 NEXT_TELEMETRY_DISABLED=1
# Where the standalone server forwards /api and /v1 (the backend service).
ENV API_PROXY_TARGET=http://backend:8100
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3001
CMD ["node", "server.js"]
