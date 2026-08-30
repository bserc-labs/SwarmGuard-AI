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

COPY nginx.conf /etc/nginx/conf.d/default.conf
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
             /var/log/nginx && \
    touch /run/nginx.pid && \
    chown -R nginxuser:nginxuser \
             /usr/share/nginx/html \
             /etc/nginx/conf.d \
             /var/cache/nginx \
             /var/log/nginx \
             /run/nginx.pid && \
    # The main config's `user` directive is meaningless for a non-root master
    # and emits a warning on every start.
    sed -i '/^user /d' /etc/nginx/nginx.conf

USER nginxuser

# Binding 80 as non-root works because Docker sets
# net.ipv4.ip_unprivileged_port_start=0 by default. On a host that overrides
# that, publish a high port and map it instead.
EXPOSE 80

# 127.0.0.1 rather than localhost: the latter resolves to [::1] first inside the
# container, which fails unless nginx is also listening on IPv6.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
