# Build context is the frontend/ dir. Multi-stage: Vite build -> nginx static serve.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Bundle only (esbuild). `npm run build` also runs `tsc -b`, which needs the
# OpenAPI-generated src/api/*.d.ts — gitignored, regenerated via `gen:api` against
# live servers, and absent in a hermetic build. Those types are imported `import
# type`-only, so esbuild elides them and the bundle is unaffected; typechecking
# stays a dev/CI gate (`npm run build`). The browser reaches the planning/scheduler
# services at their host-published ports via VITE_PLANNING_URL / VITE_SCHEDULER_URL.
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
