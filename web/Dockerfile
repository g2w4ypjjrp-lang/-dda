# Match Intelligence AI — web imajı (Next.js standalone, root olmayan kullanıcı).
#   docker build --build-arg MI_API_URL=http://api:8080 -t mi-web web
FROM node:22-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG MI_API_URL=http://api:8080
ENV MI_API_URL=${MI_API_URL}
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN useradd --system --uid 10001 --home /app mi
COPY --from=build --chown=mi:mi /app/.next/standalone ./
COPY --from=build --chown=mi:mi /app/.next/static ./.next/static
COPY --from=build --chown=mi:mi /app/public ./public
USER mi
EXPOSE 3000
CMD ["node", "server.js"]
