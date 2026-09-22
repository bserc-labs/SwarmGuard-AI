# Stage 1: Build the React application
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first for layer caching
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build. `npm run build` runs tsc --noEmit first, so a type
# error fails the image rather than shipping a broken bundle.
COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# openssl is here for one job: 40-tls.sh generates a self-signed certificate
# when none is mounted, so a laptop still gets HTTPS. nginx itself links
# libssl and does not need the command-line tool.
RUN apk add --no-cache openssl

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
# The base image's entrypoint runs every executable in this directory, in name
# order, before starting nginx.
COPY --chmod=0755 nginx/40-tls.sh /docker-entrypoint.d/40-tls.sh
COPY --from=build /app/dist /usr/share/nginx/html

# Run as an unprivileged user.
#
# The pid file and every temp path nginx writes must be owned by that user.
# `chown -R /var/run` does not work here: /var/run is a symlink to /run and
# chown -R does not follow symlinks, so /run stayed root-owned and nginx died
# with `open() "/run/nginx.pid" failed (13: Permission denied)`. The pid file is
# created and chowned explicitly instead.
#
# proxy_temp matters too — without it the /api and /ws reverse proxies fail on
# any response large enough to buffer to disk.
RUN adduser -D -H -u 1000 -s /bin/sh nginxuser && \
    mkdir -p /var/cache/nginx/client_temp \
             /var/cache/nginx/proxy_temp \
             /var/cache/nginx/fastcgi_temp \
             /var/cache/nginx/uwsgi_temp \
             /var/cache/nginx/scgi_temp \
             /var/log/nginx \
             /etc/nginx/tls \
             /var/www/acme && \
    touch /run/nginx.pid && \
    chown -R nginxuser:nginxuser \
             /usr/share/nginx/html \
             /etc/nginx/conf.d \
             /etc/nginx/tls \
             /var/cache/nginx \
             /var/log/nginx \
             /run/nginx.pid && \
    # The main config's `user` directive is meaningless for a non-root master
    # and emits a warning on every start.
    sed -i '/^user /d' /etc/nginx/nginx.conf

USER nginxuser

# Binding 80 and 443 as non-root works because Docker sets
# net.ipv4.ip_unprivileged_port_start=0 by default. On a host that overrides
# that, publish high ports and map them instead.
EXPOSE 80 443

# /healthz is answered on port 80 without a redirect. Probing / would now get a
# 301 to https, and following it means trusting a possibly self-signed
# certificate from inside the container.
#
# 127.0.0.1 rather than localhost: the latter resolves to [::1] first inside the
# container, which fails unless nginx is also listening on IPv6.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
