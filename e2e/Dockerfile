# syntax=docker/dockerfile:1
# Official image: Chromium/Firefox/WebKit + system deps, version-matched to @playwright/test.
FROM mcr.microsoft.com/playwright:v1.64.0-noble
WORKDIR /e2e
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
CMD ["sh", "-c", "npx tsc --noEmit && npx playwright test"]
