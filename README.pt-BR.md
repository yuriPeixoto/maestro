# 🎼 Maestro - Observability & Telemetry

[🇺🇸 English Version (Primary documentation)](./README.md)

Maestro é um ecossistema de observabilidade e telemetria distribuída de alto desempenho, projetado para infraestruturas on-premise e aplicações críticas. O sistema combina a eficiência de baixo nível do **Go** com a inteligência analítica do **Python**, utilizando o **ClickHouse** para consultas analíticas ultrarrápidas (OLAP).

---

## 🏗️ Arquitetura do Sistema

O Maestro foi desenhado seguindo princípios de desacoplamento e resiliência:

1.  **Maestro Agent (Go)**: Coletor de métricas e logs ultraleve. Utiliza Goroutines para concorrência massiva e eBPF para monitoramento de rede/kernel com overhead quase zero.
2.  **Ingestion API (FastAPI)**: Orquestrador em Python que recebe dados, valida contratos polimórficos (JSON) e gerencia o controle de acesso.
3.  **Redis Streams**: Buffer de mensagens de alto rendimento que garante a persistência dos dados mesmo em picos de tráfego ou oscilações no banco de dados.
4.  **ClickHouse Storage**: Banco de dados colunar otimizado para séries temporais e logs, utilizando compressão ZSTD(1) para reduzir ocupação em disco em até 80%.

---

## ✨ Diferenciais Técnicos

Baseado em nossas [Decisões Arquiteturais (ADRs)](/docs/adrs/):

-   **Performance de Elite**: Agent em Go com Worker Pool e Buffered Channels, reduzindo o overhead de conexão em até 90% via batching (envio em lotes).
-   **Inteligência Preditiva**: Uso de Pandas e Scikit-learn para identificar anomalias (Dynamic Thresholds) em vez de alertas estáticos baseados apenas em limiares fixos.
-   **Contrato de Dados Unificado**: Um único contrato JSON polimórfico para métricas e logs, facilitando a correlação de eventos (ex: erro no log correlacionado a um pico de CPU).
-   **Escalabilidade de Storage**: Tabelas MergeTree no ClickHouse com particionamento por data, permitindo consultas em milhões de registros em milissegundos.

---

## 🛠️ Tech Stack

| Componente | Tecnologia | Papel Principal |
| :--- | :--- | :--- |
| **Agent** | Go 1.21+ | Coleta, Compressão e eBPF |
| **API** | Python 3.10+ (FastAPI) | Controle, Ingestão e Alertas |
| **Frontend** | React + Vite + Tailwind | Dashboard & Syslogs Explorer |
| **Storage** | ClickHouse | Banco OLAP de Telemetria |
| **Queue** | Redis Streams | Desacoplamento e Resiliência |
| **Charts** | Apache ECharts | Visualização de métricas em tempo real |

---

## 🚀 Começando

### Pré-requisitos
- Go 1.21+
- Python 3.10+
- Node.js 18+ (para o Frontend)
- Instância de ClickHouse e Redis disponível

### 1. Configuração do Agent
```bash
cd agent
go mod download
go build ./cmd/agent
```

### 2. Configuração da API
```bash
cd api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configuração do Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## 📂 Estrutura do Projeto

- **/agent**: Código fonte do agente de coleta (Go).
- **/api**: Backend de ingestão e controle (Python).
- **/frontend**: Dashboard administrativo e visualizadores (React).
- **/docs/adrs**: Documentos de Decisão Arquitetural (ADR) com justificativas técnicas detalhadas.

---

## 🔔 Canais de Notificação
O Maestro suporta alertas em múltiplos níveis:
- **Operacional**: Webhooks para Discord/Slack.
- **Sênior**: Telegram Bot API oficial.
- **Infraestrutura**: SMTP/Email para falhas críticas de base.

---

## 🤝 Contribuindo

Contribuições são o que fazem a comunidade open source um lugar incrível para aprender, inspirar e criar. Qualquer contribuição que você fizer será **muito apreciada**.

1. Faça um Fork do projeto
2. Crie uma Branch para sua Feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a Branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## 🗺️ Roadmap

- [ ] Implementação de novos coletores eBPF para segurança.
- [ ] Suporte a exportação para Prometheus/Grafana.
- [ ] Interface mobile-responsive completa.
- [ ] Módulo de Machine Learning para detecção de anomalias em tempo real (Beta).

## 📄 Licença

Distribuído sob a licença MIT. Veja `LICENSE` para mais informações.
