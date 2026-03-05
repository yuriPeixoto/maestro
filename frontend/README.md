# Maestro Frontend

Observability Dashboard for Maestro, built with React, TypeScript, and Vite.

## Tech Stack

- **Framework**: [React](https://react.dev/) + [Vite](https://vitejs.dev/)
- **Styling**: [Tailwind CSS](https://tailwindcss.com/)
- **State Management**: [Zustand](https://docs.pmnd.rs/zustand)
- **Data Fetching**: [TanStack Query](https://tanstack.com/query)
- **Visualization**: [Apache ECharts](https://echarts.apache.org/)
- **Icons**: [Lucide React](https://lucide.dev/)

## Architecture

- `/src/components`: UI components (Dashboard, Widgets).
- `/src/hooks`: Custom React hooks for data fetching and logic.
- `/src/services`: API clients (Axios) and Query configurations.
- `/src/store`: Global state management.
- `/src/types`: TypeScript interfaces for the entire application.

## Getting Started

### Installation

```bash
cd frontend
npm install
```

### Development

```bash
npm run dev
```

### Build

```bash
npm run build
```

## Coding Guidelines

- Use TypeScript for all new components.
- Keep components small and focused.
- Prefer Tailwind utility classes for styling.
- Use `useQuery` for all data fetching.
