Você está iniciando uma sprint no projeto Maestro.

Issues desta sprint: $ARGUMENTS

Execute os seguintes passos:

1. **Leia cada issue** usando `gh issue view <number> --repo yuriPeixoto/maestro` para entender o escopo e acceptance criteria.

2. **Verifique o branch atual** com `git branch` e `git status`. Se não estiver na main, mude para ela e faça pull.

3. **Crie o branch da feature:**
   ```bash
   git checkout main && git pull origin main && git checkout -b feature/<slug>
   ```

4. **Identifique em qual componente o trabalho se encaixa:**
   - `agent/` → Go 1.26 (coletor, Worker Pool, Buffered Channels)
   - `api/` → Python 3.10+ FastAPI (ingestão, alertas, analytics)
   - `frontend/` → React + Vite + ECharts (dashboard)
   - Infra/config → Docker Compose, ClickHouse schemas, Redis config

5. **Consulte os ADRs relevantes** em `docs/adrs/` antes de qualquer decisão arquitetural.

6. **Apresente um plano de implementação** antes de codificar:
   - Qual componente(s) será afetado
   - Arquivos a criar/modificar
   - Padrões Go ou Python a aplicar
   - Testes necessários

7. **Aguarde aprovação** antes de começar.

Regras por componente:

**Go (agent/):**
- Sem dependências desnecessárias — binário leve é o objetivo
- Usar goroutines para coleta concorrente
- Batching obrigatório (50 items OU 5s timeout) antes de enviar
- `go vet ./...` antes de qualquer commit

**Python (api/):**
- Todos os endpoints `async def`
- Pydantic models para contratos de request/response
- Workers como processos independentes
- `ruff` ou `flake8` para lint

**Frontend (frontend/):**
- Se a issue envolver UI, ative a skill UI/UX Pro Max para decisões de design
- ECharts para todos os gráficos (já no projeto)
- Responsivo: 375px, 768px, 1024px, 1440px

Lembre: todos os novos arquivos de documentação devem ser `.md`, não `.txt`.
