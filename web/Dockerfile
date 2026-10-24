# Builds the static Next.js export and serves it with a tiny static server.
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser talks to the API at this origin (same-origin when the API serves /out itself).
ARG NEXT_PUBLIC_API_BASE=http://localhost:8100
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

FROM node:22-alpine
WORKDIR /web
RUN npm install -g serve@14.2.4
COPY --from=build /web/out ./out
EXPOSE 3100
CMD ["serve", "-s", "out", "-l", "3100"]
