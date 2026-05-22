# 🎼 Maestro - Observability & Telemetry

[🇧🇷 Versão em Português (pt-BR)](./README.pt-BR.md)

Maestro is a high-performance distributed observability and telemetry ecosystem, designed for on-premise infrastructures and critical applications. The system combines the low-level efficiency of **Go** with the analytical intelligence of **Python**, utilizing **ClickHouse** for ultra-fast analytical queries (OLAP).

---

## 🏗️ System Architecture

Maestro was designed following principles of decoupling and resilience:

1.  **Maestro Agent (Go)**: Ultra-lightweight metric and log collector. Uses Goroutines for massive concurrency and eBPF for network/kernel monitoring with near-zero overhead.
2.  **Ingestion API (FastAPI)**: Python orchestrator that receives data, validates polymorphic contracts (JSON), and manages access control.
3.  **Redis Streams**: High-throughput message buffer that ensures data persistence even during traffic spikes or database oscillations.
4.  **ClickHouse Storage**: Columnar database optimized for time series and logs, using ZSTD(1) compression to reduce disk occupancy by up to 80%.

---

## ✨ Technical Highlights

Based on our [Architectural Decision Records (ADRs)](/docs/adrs/):

-   **Elite Performance**: Agent in Go with Worker Pool and Buffered Channels, reducing connection overhead by up to 90% via batching.
-   **Predictive Intelligence**: Use of Pandas and Scikit-learn to identify anomalies (Dynamic Thresholds) instead of static alerts based only on fixed thresholds.
-   **Unified Data Contract**: A single polymorphic JSON contract for metrics and logs, facilitating event correlation (e.g., error in the log correlated to a CPU spike).
-   **Storage Scalability**: MergeTree tables in ClickHouse with partitioning by date, allowing queries on millions of records in milliseconds.

---

## 🛠️ Tech Stack

| Component | Technology | Primary Role |
| :--- | :--- | :--- |
| **Agent** | Go 1.21+ | Collection, Compression & eBPF |
| **API** | Python 3.10+ (FastAPI) | Control, Ingestion & Alerts |
| **Frontend** | React + Vite + Tailwind | Dashboard & Syslogs Explorer |
| **Storage** | ClickHouse | Telemetry OLAP Database |
| **Queue** | Redis Streams | Decoupling & Resilience |
| **Charts** | Apache ECharts | Real-time metrics visualization |

---

## 🚀 Getting Started (local development)

> **Note:** This section is for contributors and developers running Maestro locally.
> Production deployment runs on bare metal via systemd — see [docs/deployment.md](docs/deployment.md).

### Option A — Docker Compose (recommended for contributors)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine + Compose v2.

```bash
# Clone the repo
git clone https://github.com/yuriPeixoto/maestro.git
cd maestro

# Start the full stack (Redis, ClickHouse, API, Frontend)
docker compose up
```

Services will be available at:
| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| ClickHouse (HTTP) | http://localhost:8123 |
| Redis | localhost:6379 |

ClickHouse migrations run automatically on first startup.

To seed demo data:
```bash
docker compose --profile demo up
```

> **First build takes ~5-10 minutes** due to Python ML dependencies (Prophet, scipy).
> Subsequent starts use the cached image and are fast.

### Option B — Manual setup

**Prerequisites:** Go 1.26+, Python 3.11+, Node.js 20+, ClickHouse, Redis

```bash
# Agent
cd agent && go build -o maestro-agent ./cmd/agent

# API
cd api && python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # adjust values
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# ClickHouse migrations (run once)
for f in migrations/*.sql; do
  clickhouse-client --multiquery < "$f"
done
```

---

## 📂 Project Structure

- **/agent**: Collection agent source code (Go).
- **/api**: Ingestion and control backend (Python).
- **/frontend**: Administrative dashboard and viewers (React).
- **/docs/adrs**: Architectural Decision Records (ADR) with detailed technical justifications.

---

## 🔔 Notification Channels
Maestro supports alerts at multiple levels:
- **Operational**: Webhooks for Discord/Slack.
- **Senior**: Official Telegram Bot API.
- **Infrastructure**: SMTP/Email for critical base failures.

---

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 🗺️ Roadmap

- [ ] Implementation of new eBPF collectors for security.
- [ ] Support for export to Prometheus/Grafana.
- [ ] Complete mobile-responsive interface.
- [ ] Machine Learning module for real-time anomaly detection (Beta).

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
