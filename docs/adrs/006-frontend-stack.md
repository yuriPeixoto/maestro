# ADR-006: Frontend Stack

**Status**: Accepted
**Date**: 2026-03-08
**Deciders**: Yuri Peixoto

---

## Context

Maestro needs a frontend for the observability dashboard — displaying real-time metric charts, server status, alert state, and (later) capacity forecasts. The frontend must:

- Display live-updating charts with sub-10s latency
- Work as an authenticated single-page application (no public-facing pages)
- Support a future upgrade from polling to WebSocket streaming without a rewrite
- Be maintainable by a small team with strong TypeScript/React familiarity

---

## Decision

### Build Tool: Vite

**Vite** over Next.js and Create React App (deprecated):

- Maestro's frontend is an authenticated dashboard — there are no public-facing pages, no SEO requirements, and no need for server-side rendering
- Next.js adds SSR/RSC complexity, a Node.js server process, and routing conventions that are unnecessary overhead for a dashboard
- Vite provides near-instant HMR, native ES modules, and a minimal configuration surface
- The build output is a static SPA served by the FastAPI backend or any static file server

### React + TypeScript

React 18 with strict TypeScript throughout the codebase:

- Component model maps well to metric cards, chart panels, and server list items
- TypeScript enforces API response shape contracts — critical for a dashboard where a wrong type causes silent rendering errors
- Large ecosystem of compatible charting and state management libraries

### Tailwind CSS

Tailwind for all styling:

- Utility-first approach eliminates CSS specificity conflicts in a component-heavy dashboard
- Dark mode support is built-in (essential for operations dashboards)
- No runtime CSS-in-JS overhead

### TanStack Query (React Query)

TanStack Query manages all server state (API data fetching, caching, background refresh):

**Phase 2 — Polling**:
```typescript
useQuery({
  queryKey: ['metrics', serverId, metricName],
  queryFn: () => fetchMetrics(serverId, metricName),
  refetchInterval: 5000,  // 5-second polling
})
```

**Phase 3 — WebSocket upgrade**:
TanStack Query's `setQueryData` can be called from a WebSocket message handler to update cached data without a polling round-trip. FastAPI natively supports WebSocket endpoints. The upgrade requires no changes to component code — only the data-fetching layer changes.

Alternatives rejected:
- `useEffect + fetch`: no caching, no deduplication, no background refresh
- SWR: less feature-rich than TanStack Query; smaller community

### Zustand

Zustand for global client state:

- Selected server (drives all metric charts on the dashboard)
- Active time range filter (last 15m / 1h / 24h)
- Alert panel open/closed state

Zustand is lightweight (~1kB), boilerplate-free, and TypeScript-native. It replaces the need for React Context for shared state that changes frequently.

**Anti-pattern avoided**: Redux — overkill for the state surface in this application. Redux's action/reducer/selector ceremony is appropriate for complex multi-domain state; Maestro's client state is simple.

### Recharts

Recharts for all time-series and capacity charts:

- React-native: chart components are actual React components with props, not imperative canvas commands
- Composable: `<LineChart>`, `<Line>`, `<XAxis>`, `<Tooltip>` compose naturally — easy to add reference lines for alert thresholds, anomaly markers, and forecast confidence bands
- Adequate performance for dashboards refreshing every 5s with ~200 data points per chart

**Alternative rejected — Chart.js**: Chart.js uses a canvas imperative API that requires refs and manual lifecycle management in React. It is less composable and harder to extend with custom React components.

---

## Phase 2 → Phase 3 Migration Path

| Concern | Phase 2 | Phase 3 |
|---------|---------|---------|
| Data delivery | HTTP polling every 5s | WebSocket streaming from FastAPI |
| TanStack Query | `refetchInterval: 5000` | `setQueryData` from WebSocket handler |
| Alert state | Polled from REST endpoint | Pushed via WebSocket |
| Component code | No change required | No change required |

The polling-first approach in Phase 2 means the frontend is functional with zero WebSocket infrastructure. Phase 3 is a data-layer upgrade, not a UI rewrite.

---

## Alternatives Considered

| Tool | Verdict | Reason |
|------|---------|--------|
| Next.js | Rejected | SSR/RSC complexity unnecessary for an authenticated dashboard |
| Create React App | Rejected | Deprecated; slow HMR |
| Chart.js | Rejected | Imperative canvas API; poor React composability |
| Redux | Rejected | Overkill for Maestro's client state surface |
| Vue / Svelte | Rejected | Team familiarity is with React + TypeScript |

---

## Consequences

**Positive**:
- Vite's HMR makes development fast and iteration quick
- TanStack Query's caching prevents redundant API calls when multiple components need the same metric
- The polling → WebSocket migration requires no component-level changes
- Recharts' composability makes it straightforward to add anomaly markers and forecast bands in later phases

**Negative**:
- Vite produces a SPA — deep linking requires the backend to serve `index.html` for all routes (trivial FastAPI configuration, but it must be done)
- Recharts re-renders the full chart on each data update — at very high update frequencies (sub-second) this would be a bottleneck, but 5s polling is well within budget
