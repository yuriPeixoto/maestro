# Maestro - Observability & Telemetry

Maestro is a distributed observability and telemetry system designed for on-premise servers. It consists of a high-performance collection agent and a centralized control and ingestion API.

## Project Structure

- **/agent**: Metrics collection and delivery agent (Go).
- **/api**: Ingestion and control backend (Python/FastAPI).
- **/docs**: Architecture documentation and ADRs.

## Tech Stack

### Agent
- **Language**: Go
- **Features**: Batching, compression, low-resource footprint.

### API
- **Language**: Python
- **Framework**: FastAPI
- **Features**: Async ingestion, control plane functionality.

## Getting Started

### Prerequisites
- Go 1.21+
- Python 3.10+

### Agent Setup
```bash
cd agent
go mod download
go build ./cmd/agent
```

### API Setup
```bash
cd api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
