# Stage 1: Build the React Application
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies first for layer caching
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and build
COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from Stage 1
COPY --from=build /app/dist /usr/share/nginx/html

# Create non-root user and set permissions
RUN adduser -D -H -u 1000 -s /bin/sh nginxuser && \
    mkdir -p /var/cache/nginx /var/run /var/log/nginx && \
    chown -R nginxuser:nginxuser /usr/share/nginx/html /etc/nginx/conf.d /var/cache/nginx /var/run /var/log/nginx

USER nginxuser

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
