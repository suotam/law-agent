# Law Agent React

Frontend for the Law Agent application, built with React, TypeScript, and Vite.

## Requirements

- Node.js 22 (`.nvmrc`) — the app itself runs on newer versions too, but the
  test suite's multipart upload tests hang under Node 24: the msw/jsdom
  `XMLHttpRequest` interception never delivers the response for a `FormData`
  body there. Use `nvm use` (or `npx -p node@22 -- npm test`) until msw catches up.
- npm

## Setup

Install dependencies:

```bash
npm install
```

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

## Running

Start the development server with hot module reloading:

```bash
npm run dev
```

## Production

Build and run the app in a container (served via nginx):

```bash
docker compose up --build -d
```

The app will be available at `http://localhost`.

## Test

```bash
npm run test
```

Run tests in watch mode:

```bash
npm run test:watch
```

## Typecheck

```bash
npm run typecheck
```

## Lint

```bash
npm run lint
```

Fix auto-fixable issues:

```bash
npm run lint:fix
```

Formatting is handled separately with Prettier:

```bash
npm run format:check
npm run format
```
