FROM node:22-bullseye AS build

WORKDIR /app

ENV npm_config_progress=false \
    npm_config_fund=false \
    npm_config_audit=false

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web ./
RUN npm run build

FROM nginx:1.27-alpine

COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
