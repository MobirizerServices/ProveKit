# AgentMan frontend image (Next.js standalone). The browser calls the backend directly
# at NEXT_PUBLIC_API_BASE (baked at build; default the compose-published localhost:8100).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_BASE=http://localhost:8100
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3001 NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3001
CMD ["node", "server.js"]
