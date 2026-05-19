# Maestro — Frontend UX Design Brief

> **Para:** Claude Design (sessão especializada de UX/UI)
> **Contexto:** Este documento foi preparado pelo time de desenvolvimento para uma revisão de UX. O objetivo não é um redesign visual total — o design system dark (Tailwind, glass-card, brand-purple/neon) está bom e deve ser mantido. O problema é mais profundo: a interface **exibe dados, mas não comunica nada**.

---

## 1. O que é o Maestro

Plataforma de observabilidade on-premise para infraestrutura de servidores. Não é um SaaS, não é o Datadog. É rodado dentro da empresa, para a empresa, com dados que nunca saem do servidor.

**Usuário primário:** Desenvolvedor/administrador que cuida de alguns servidores de uma empresa pequena/média. Não é um SRE full-time com um NOC. É alguém que abre o dashboard quando uma coisa quebra ou quando está preocupado — e que quer saber imediatamente se há algo errado, e o quê.

**Stack técnica atual:**
- Frontend: React + Vite + Tailwind CSS + TanStack Query + Zustand
- Gráficos: ECharts (echarts-for-react) — **não trocar, já integrado**
- Dados ML: anomaly scores [0,1] por ponto de métrica (Isolation Forest + River online learning)
- Backend: FastAPI com endpoints para métricas, alertas, logs, segurança, inventário
- Servidor de staging real: dados reais chegando ao vivo

---

## 2. Estado atual — inventário honesto das views

### 2.1 Dashboard (Home)

**O que mostra hoje:**
- 3 cards: "Servidores Ativos" (N de N), "Agentes Online" (mesmo número que o de cima), "Incidentes Críticos" (hardcoded 0)
- Lista de servidores com link para cada um

**Problemas:**
- Dois dos três cards dizem a mesma coisa (total online)
- O terceiro (incidentes críticos) está morto — hardcoded 0, nunca vai mudar
- A lista de servidores é só uma lista de nomes com dot verde/vermelho — não diz nada sobre saúde
- Não há nenhuma resposta para a pergunta "o que eu preciso olhar agora?"

---

### 2.2 Infrastructure (Mapa de Servidores)

**O que mostra hoje:**
- Grid de cards de servidores (nome, versão do agente, online/offline, "Xm atrás")
- Tabela de inventário de serviços e runtimes (nginx: active, python: 3.14.5, etc.)

**Problemas:**
- Cada card de servidor só diz se está online — sem nenhuma métrica atual
- Você não sabe o CPU/RAM de nenhum servidor antes de clicar nele
- O inventário aparece para "o servidor selecionado" mas essa seleção é invisível no UI
- A tabela de inventário de runtimes é informativa mas estática — você já sabia que o Python está instalado

---

### 2.3 ServerDashboard (Dashboard do servidor)

**O que mostra hoje:**
- 4 summary cards com o valor atual de CPU, Memória, Disco, Processos
- 8 gráficos de linha (um por métrica) em grid 2×4
- Toggle de janela temporal (15m, 1h, 6h, 24h)
- Toggle "Anomalias" que sobrepõe dots amber/vermelho nos gráficos

**Problemas:**
- 8 gráficos de igual peso visual — não há hierarquia. CPU crítica tem o mesmo destaque que disk write bytes
- Os summary cards mostram o valor atual mas não dizem se é normal, alto ou crítico para esse servidor
- O toggle de anomalias é uma feature excelente mas está escondido e não tem contexto ("5 anomalias detectadas nas últimas 6h" não existe — só dots nos gráficos)
- Não há resposta para "este servidor está bem?" — você tem que olhar 8 gráficos mentalmente e sintetizar
- Sem comparação temporal: "72% CPU — isso é o normal para este servidor ou é um spike?"
- Sem tendência textual: "Memória crescendo a 2%/h nas últimas 3h"

---

### 2.4 Security & Auth

**O que mostra hoje:**
- 4 stat cards: tentativas 1h, tentativas 24h, IPs únicos 24h, usuário mais visado
- Tabela de audit log SSH (hora, evento, IP, usuário, status)
- Painel lateral: alerta de intrusão (vermelho/verde), resumo da sessão

**Problemas:**
- É bem feita para o que faz, mas todos os dados são do mesmo nível — 3 tentativas ou 3000 tentativas, o UI parece igual
- O alerta de intrusão muda de cor (vermelho/verde) mas não diz "isso é fora do normal para esse servidor?"
- Não há contexto histórico: "hoje teve 3x mais tentativas que a média dos últimos 7 dias"
- A tabela de eventos é uma lista enorme sem agrupamento — 200 linhas do mesmo IP tentando o mesmo username deveriam colapsar em "1 atacante, 200 tentativas"

---

### 2.5 Alerts (Central de Alertas)

**O que mostra hoje:**
- Lista de regras ativas (métrica, operador, threshold, severidade, cooldown)
- Configuração de webhook
- Histórico de eventos (FIRING/RESOLVED com timestamp)

**Problemas:**
- As regras são mostradas como texto puro — não há indicação de se a regra está "perto de disparar" agora
- O histórico de eventos é uma lista cronológica flat — não dá para ver "essa regra disparou 5 vezes hoje, geralmente às 14h"
- Não há estado de "saúde das regras": está tudo silencioso porque não há problemas, ou porque ninguém configurou regras?

---

### 2.6 Logs Explorer

**O que mostra hoje:**
- Seletor de arquivo de log
- Tail dos últimos N lines em tabela

**Problemas:**
- Funcional mas passivo — você vê o que o log diz, não o que ele significa
- Sem search/filter no frontend
- Sem correlação temporal com métricas ("o spike de CPU às 14:32 coincide com esse erro no nginx?")

---

## 3. O problema central — dado vs inteligência

Existe uma diferença entre um sistema que **exibe telemetria** e um que **opera como observabilidade**:

| O que temos agora | O que queremos |
|---|---|
| "CPU: 72%" | "CPU acima do normal — 15% acima da média das últimas 24h" |
| Gráfico de linha com dots de anomalia | "3 anomalias detectadas — a mais recente há 12min (score 0.87)" |
| Lista de eventos FIRING/RESOLVED | "Essa regra disparou 4x hoje — padrão: sempre entre 13h–15h" |
| 200 linhas de brute-force no log | "1 atacante (IP 45.33.x.x), 200 tentativas, alvo: usuário 'root'" |
| Dashboard com 3 números e uma lista | "2 servidores ok, 1 com atenção (RAM em tendência), 0 críticos" |

**A pergunta que o usuário faz ao abrir o Maestro:**
> "Está tudo bem? O que eu preciso olhar agora?"

**A resposta que o Maestro dá hoje:**
> Aqui estão seus dados. Você decide.

**A resposta que o Maestro deveria dar:**
> Tudo bem em 2 servidores. No `web-01`: memória crescendo a 1.8%/h nas últimas 4h — vai atingir 90% em ~2h. 3 anomalias de CPU hoje, todas resolvidas. 847 tentativas SSH bloqueadas.

---

## 4. Oportunidades por view

### 4.1 Dashboard — de "lista" para "situational awareness"

**Oportunidade:** Transformar o dashboard em um painel de status operacional.

- **Status consolidado por servidor**: cada servidor deveria ter um score de saúde (OK / Atenção / Crítico) baseado em: regras ativas disparando, anomalias recentes (score > 0.7), tendência de memória/CPU, serviços offline
- **"Foco aqui"**: destacar o servidor que mais precisa de atenção com contexto ("CPU 89% há 15min", "RAM tendência de alta", "2 anomalias")
- **Incidentes reais**: o card "Incidentes Críticos" deveria mostrar alertas FIRING das últimas 24h — não 0 hardcoded

**Dados disponíveis:** `/servers`, `/alerts/{id}/events`, `/metrics/{id}/anomaly-scores`

---

### 4.2 Infrastructure — cards com health snapshot

**Oportunidade:** Cada card de servidor pode mostrar um snapshot de saúde sem clicar.

- CPU atual + trend indicator (↑ ↓ →)
- RAM atual + barra de progresso color-coded
- Status de serviços críticos (um ícone por serviço crítico: nginx, postgres, redis)
- Score de anomalia: 🟢 nenhuma / 🟡 média / 🔴 alta (últimas 6h)

---

### 4.3 ServerDashboard — hierarquia e narrativa

**Oportunidade:** Esta é a view mais rica e a que mais precisa de redesign.

**Hierarquia visual:**
- Métricas de saúde crítica (CPU, RAM, Disco) devem ter peso visual maior
- Métricas de I/O (disk read/write, network) são secundárias — podem estar em seção colapsável ou abas

**Contexto de normalidade:**
- Summary cards deveriam mostrar baseline do servidor: "CPU: 72% | Média 7d: 45% ↑ acima do normal"
- Barra de threshold visual nos cards (linha pontilhada no gráfico onde a regra de alerta está definida)

**Narrativa de anomalias:**
- Se o toggle "Anomalias" está ativo E há anomalias detectadas: mostrar um sumário acima dos gráficos ("4 anomalias nas últimas 6h — a mais severa: cpu_usage_percent às 14:32 (score 0.91)")
- Anomalias sem o gráfico sendo inspecionado não servem para nada

**Projeção / tendência:**
- Para RAM e Disco (tendência monotônica): "Na taxa atual, atingirá 90% em ~X horas"
- Calculável com dados existentes (rate_of_change do feature engineering)

---

### 4.4 Security — agrupamento e contexto

**Oportunidade:** A view de segurança já tem os dados certos, falta apresentação.

- **Agrupamento de ataques**: colapsar múltiplas tentativas do mesmo IP em um único registro expansível ("IP 45.33.x.x — 847 tentativas, 12 usuários diferentes, últimas 6h")
- **Comparativo com baseline**: "Hoje: 3.200 tentativas | Média 7d: 1.100 | 2.9× acima do normal"
- **Linha do tempo de ataques**: sparkline das últimas 24h mostrando volume por hora — fácil de ver se há pico pontual ou pressão constante

---

### 4.5 Alerts — rules com estado vivo

**Oportunidade:** Mostrar as regras como entidades vivas, não só configuração.

- **Valor atual vs threshold**: para cada regra, mostrar "CPU: 72% → threshold 80% (9% de margem)" com uma micro barra de progresso
- **Histórico de disparo por regra**: "essa regra disparou 3× nesta semana, sempre entre 13h–15h" — padrão horário
- **Silêncio vs saudável**: indicar se a ausência de disparos é porque "tudo está bem" ou porque "a regra nunca foi testada"

---

## 5. O que NÃO mudar

- **Design system**: dark theme, glass-card, brand-purple (#7C3AED), brand-neon (#39FF14), slate palette — está com identidade
- **Biblioteca de gráficos**: ECharts (echarts-for-react) — já integrado, funciona bem
- **Estrutura de rotas e navegação**: sidebar + views — funciona para o modelo mental
- **Componentes funcionais existentes**: MetricCard, audit log table, webhook config — funcionam, podem ser aprimorados, não descartados
- **Layout responsivo**: mobile-first mantido

---

## 6. Constraints técnicas para o designer

- **Dados de anomalia**: scores [0,1] disponíveis por ponto de métrica via `GET /metrics/{id}/{metric}/anomaly-scores`
- **Feature engineering disponível**: `rolling_mean_5m`, `rolling_std_5m`, `rate_of_change` — podem gerar narrativas de tendência
- **Alert events**: `GET /alerts/{id}/events` retorna histórico de FIRING/RESOLVED com timestamps — permite análise de frequência
- **Sem WebSocket ativo**: refetch polling (30s métricas, 60s anomalias) — animações de "live" devem ser sutis
- **Sem backend de notificações push**: não há toast de alerta em tempo real ainda (planejado)
- **Multi-servidor**: a UI foi construída para 1 servidor, multi-servidor é próxima fase — não projetar para fleet de 100 servidores, mas manter em mente que haverá 4–8 servidores por empresa típica

---

## 7. O que queremos desta sessão de design

1. **Revisão da arquitetura de informação**: as views atuais fazem sentido? Falta alguma view? Alguma deveria ser unificada?

2. **Redesign do Dashboard home**: como transformar os 3 cards mortos em situational awareness real?

3. **Redesign do ServerDashboard**: como apresentar 8 métricas com hierarquia, contexto de normalidade e narrativa de tendência sem sobrecarregar?

4. **Padrão de "insight card"**: um componente reutilizável que transforma um número bruto em uma leitura contextualizada — pode ser aplicado em Dashboard, Infrastructure e ServerDashboard

5. **Tratamento de anomalias**: como expor visualmente os scores de anomalia de forma que o usuário entenda "isso precisa de atenção" sem precisar entender o que é HalfSpaceTrees?

**Formato esperado:** wireframes em texto (ASCII) ou descrições de layout suficientemente detalhadas para implementação. Não esperamos Figma — queremos diretrizes claras de layout, hierarquia visual e comportamento de componentes.

---

## 8. Pergunta de design central

> Como uma plataforma de observabilidade para um time de 1–3 pessoas, sem NOC, com 4–8 servidores, deve apresentar informações para que a primeira pergunta do usuário — "está tudo bem?" — seja respondida em menos de 5 segundos, e a segunda pergunta — "o que precisa de atenção?" — seja respondida com contexto suficiente para agir sem precisar navegar em mais de 2 views?

---

*Brief gerado em 19/05/2026 — para uso em sessão Claude Design*
