# Build the React app, then serve it with nginx. nginx also proxies /api to the
# API service so the browser talks to a single origin (needed for SameSite cookies).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY proxy_api.inc /etc/nginx/conf.d/proxy_api.inc
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
