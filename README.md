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

## 🚀 Getting Started

### Prerequisites
- Go 1.21+
- Python 3.10+
- Node.js 18+ (for Frontend)
- ClickHouse and Redis instances available

### 1. Agent Configuration
```bash
cd agent
go mod download
go build ./cmd/agent
```

### 2. API Configuration
```bash
cd api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Frontend Configuration
```bash
cd frontend
npm install
npm run dev
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
