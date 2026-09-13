FROM node:24-alpine AS builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json frontend/vite.config.ts ./
COPY frontend/public/ ./public/
COPY frontend/src/ ./src/

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM caddy:2.10-alpine

RUN apk add --no-cache su-exec \
    && addgroup -g 10001 -S app \
    && adduser -u 10001 -S -D -H -G app app

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --chmod=755 deploy/load-secrets.sh /usr/local/bin/load-secrets
COPY --from=builder --chown=app:app /build/frontend/dist/ /srv/

EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/load-secrets"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
