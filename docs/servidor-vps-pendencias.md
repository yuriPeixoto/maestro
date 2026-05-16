# Servidor VPS — Pendências e Configuração

## Acesso

| Campo    | Valor                   |
|----------|-------------------------|
| IP       | 153.75.226.75           |
| Porta    | 22                      |
| Usuário  | `kaladin`               |
| Auth     | Chave SSH (`~/.ssh/id_ed25519`) |

> ⚠️ **NÃO usar mais `root` diretamente.** Usar `kaladin` + `sudo`.

---

> ## ✅ SEGURANÇA SSH — CONCLUÍDA (15/05/2026)
>
> - `PasswordAuthentication no` ✅
> - `PermitRootLogin no` ✅
> - Chave ed25519 configurada em ambos os PCs ✅
> - Acesso verificado via chave após restart do SSH ✅
>
> **PC do trabalho:** ✅ chave configurada
> **PC de casa:** ✅ chave configurada (`~/.ssh/id_ed25519`, label `yuri-casa`)

---

## Acesso ao ClickHouse via DataGrip (SSH Tunnel)

> A porta 8123 não está exposta no firewall — conectar sempre via túnel SSH.

**New Connection → ClickHouse**

**Aba General:**

| Campo    | Valor         |
|----------|---------------|
| Host     | `localhost`   |
| Port     | `8123`        |
| User     | `default`     |
| Password | *(ver cofre)* |
| Database | `maestro`     |

**Aba SSH/SSL → Use SSH tunnel → ✓**

| Campo      | Valor                    |
|------------|--------------------------|
| Proxy host | `153.75.226.75`          |
| Port       | `22`                     |
| Proxy user | `kaladin`                |
| Auth type  | `Key pair` (`~/.ssh/id_ed25519`) |

---

## Stack do Servidor

| Recurso | Detalhe                       |
|---------|-------------------------------|
| OS      | Ubuntu 24.04.4 LTS            |
| Kernel  | 6.8.0-117-generic             |
| CPU     | Xeon Gold 6230R (1 vCPU)      |
| RAM     | 3.8GB total, 3.3GB disponível |
| Disco   | 2TB                           |
| Portas  | UFW ativo (22, 80, 443)       |

## Versões dos Runtimes e Serviços

| Runtime / Serviço | Versão      |
|-------------------|-------------|
| Go                | 1.26.3      |
| Python            | 3.14.5      |
| Node.js           | 24.15.0 LTS |
| npm               | 11.12.1     |
| PHP               | 8.5.6       |
| Composer          | 2.9.8       |
| PostgreSQL        | 18.4        |
| ClickHouse        | 26.4.2.10   |
| Redis             | 7.0.15      |
| Nginx             | 1.24.0      |

---

## O que já foi instalado e configurado

- [x] Sistema atualizado (kernel 6.8.0-117)
- [x] `zsh` + `oh-my-zsh` como shell padrão
- [x] Starship prompt (tema Tokyo Night)
- [x] Plugins: `zsh-autosuggestions`, `zsh-syntax-highlighting`
- [x] Ferramentas: `bat`, `eza`, `fzf`, `btop`, `tmux`, `fastfetch`
- [x] Timezone configurado: `America/Cuiaba` (UTC-4)
- [x] **UFW** — ativo com regras: 22/tcp, 80/tcp, 443/tcp
- [x] **Nginx** — habilitado e rodando (v1.24.0)
- [x] **PostgreSQL 18.4** — instalado, habilitado e rodando (upgrade do 16 → 18, fresh install)
- [x] **Redis 7.0.15** — habilitado e rodando (porta 6379, localhost)
- [x] **ClickHouse 26.4.2.10** — instalado, habilitado e rodando
- [x] **fail2ban** — instalado, habilitado e rodando (proteção SSH)
- [x] Usuário `deploy` criado (sem root)
- [x] **Go 1.26.3** — instalado em `/usr/local/go`, PATH via `/etc/profile.d/go.sh` e `/root/.zshrc`
- [x] **Python 3.14.5** — instalado via deadsnakes PPA
- [x] **Node.js 24.15.0 LTS** — instalado via NodeSource
- [x] **PHP 8.5.6** — instalado via ondrej/php PPA, com extensões Laravel (fpm, pgsql, redis, mbstring, xml, curl, zip, bcmath, intl)
- [x] **Composer 2.9.8** — instalado em `/usr/local/bin/composer`
- [x] **GitHub Actions Runner** — instalado para `yuriPeixoto/maestro`, rodando como serviço systemd com usuário `deploy`
- [x] **Maestro deployado** — agent (Go) + API (Python/FastAPI) + frontend (React) em produção via pipeline CI/CD
  - Agent: coletando e publicando métricas no Redis stream
  - API: consumindo do stream, gravando no ClickHouse
  - Frontend: servido pelo Nginx em `http://153.75.226.75`
  - Deploy automático a cada push para `main`
  - **Log Explorer** — visualização em tempo real de `auth.log`, `syslog`, `nginx/access.log`, etc.
  - **Segurança** — página com audit log SSH, stats de brute force e alertas de intrusão em tempo real (dados reais do `auth.log` via ClickHouse)
  - **Autenticação** — tela de login com JWT (bcrypt + python-jose); todas as rotas da API protegidas; authStore Zustand com persist; logout no Sidebar

---

## Pendências

### Fase 4 — Projetos

| Projeto    | Stack                     | Status                      |
|------------|---------------------------|-----------------------------|
| Maestro    | Go + Python + ClickHouse  | ✅ No ar                    |
| Orquestra  | Laravel / PHP             | Aguardando deploy           |
| FoundryVTT | Node.js                   | Aguardando decisão do DM    |
| Mythos     | Django + React            | Planejado                   |
| Sentinel   | Go + TS/PHP SDKs          | Planejado                   |
| Aegis      | Python + FastAPI          | Planejado                   |
| Pulse      | Go + React                | Planejado                   |
| DataScope  | Python + FastAPI + Pandas | Planejado                   |
| PokéOps    | Python + FastAPI + Redis  | Planejado                   |

- [ ] Registrar runner nos demais repositórios conforme os projetos forem deployados
  - Cada repo: Settings → Actions → Runners → New self-hosted runner

---

### Maestro — Próximos Passos

| Prioridade | Issue | Descrição |
|-----------|-------|-----------|
| 🔴 Alta | #17 | Alerting: rules engine com thresholds estáticos (CPU, RAM, disco) |
| 🔴 Alta | Alerts view | Conectar view de Alertas nos dados reais (hoje está mockada) |
| 🟡 Média | #19 | Alerting: canal webhook para notificações |
| 🟡 Média | #49 | Coletar inventário de runtimes e versões do servidor (popular view Infrastructure) |
| 🟢 Baixa | Settings view | Remover do sidebar por ora — sem backend correspondente |

**Phase 1:** ✅ concluída — **Phase 2:** em andamento (4 issues abertas)

---

### Débito Técnico

- [ ] **Timestamps ClickHouse** — o servidor está em `America/Cuiaba (UTC-4)`. O `clickhouse-connect` interpretava datetimes *naive* como horário local, gravando 4h na frente. Corrigido em `consumer.py` e `log_consumer.py` removendo `.replace(tzinfo=None)`. Se algum consumer novo for criado, **sempre inserir datetimes tz-aware (UTC)**.
- [ ] **pg_hba.conf** — PostgreSQL 18 usa `peer` para conexões locais por padrão. Ajustar para `scram-sha-256` antes de deployar qualquer projeto que conecte via usuário/senha (Orquestra, Mythos, etc.)
- [ ] **PHP-FPM não configurado no Nginx** — PHP instalado mas sem bloco de configuração no Nginx. Necessário antes do deploy do Orquestra
- [ ] **Backup** — Estratégia definida: 3-2-1 (VPS local 7 dias + OneDrive via rclone + máquina local via sync automático do OneDrive)
  - Pendente configuração do rclone: requer autenticação OAuth no browser — **fazer do PC pessoal no fds**
  - Instalar rclone no Windows: `winget install Rclone.Rclone`
  - Depois: configurar rclone localmente → copiar config para o servidor → criar script de backup + cron
- [x] **Usuário não-root para uso diário** — usuário `kaladin` criado com sudo; chaves SSH de ambos os PCs configuradas; `PasswordAuthentication no` e `PermitRootLogin no` ativos.
- [ ] **Domínio + SSL** — sem DNS, acesso só por IP. Let's Encrypt requer domínio. *(baixa prioridade — servidor é staging)*

---

### Claude no Servidor

- [ ] **Claude Code CLI** — instalar no servidor para uso direto via SSH; requer chave de API da Anthropic
- [ ] **Claude Routines** — definir automações complementares ao CI/CD, ex:
  - Revisão automática de PRs
  - Resumo semanal de pendências dos projetos
  - *(Fazer sentido quando o Maestro estiver com observabilidade completa)*

---

### Terminal

- [ ] **Símbolo da Apple no Starship** — glifo não suportado pela fonte Lilex NF
  - Opções: trocar fonte local para uma com suporte ao glifo, ou remover/substituir o símbolo em `~/.config/starship.toml`

---

*Atualizado em 15/05/2026 — SSH hardening concluído (key-only, PermitRootLogin no); autenticação JWT no dashboard; Phase 2 (alerting) iniciada*
