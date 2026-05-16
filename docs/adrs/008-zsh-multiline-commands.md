# ADR-008: Comandos no Servidor — Evitar Multiline no Zsh Customizado

**Status:** Accepted
**Date:** 2026-05-15

## Context

O servidor de staging roda zsh com oh-my-zsh, Starship prompt e plugins de syntax highlighting
(`zsh-syntax-highlighting`, `zsh-autosuggestions`). Essa combinação causa comportamento
imprevisível com comandos multiline colados diretamente no terminal:

- Continuações com `\` (backslash) podem ser interpretadas literalmente ou ignoradas
- Heredocs (`<<'EOF'`) frequentemente falham ao ser colados — o terminal não aguarda o fechamento
- Blocos `if/for/while` colados de uma vez podem disparar execução prematura
- O syntax highlighting processa cada linha ao ser colada, quebrando o contexto do bloco

Descoberto na prática ao tentar gerar um hash bcrypt com um comando Python multiline — o zsh
executou o bloco incompleto e retornou erro.

## Decision

**Sempre escrever comandos para o servidor em linha única ou em comandos separados sequenciais.**

Regras práticas:

| Situação | Abordagem |
|----------|-----------|
| Lógica simples | Uma linha com `;` separando statements |
| Lógica com condição | Separar em dois comandos distintos |
| Script maior | Criar arquivo `.py` / `.sh` localmente, subir via CI/CD ou `scp`, executar no servidor |
| Variáveis de ambiente | `export VAR=valor` em linha única por variável |
| Instalação + execução | Dois comandos separados (instalar, depois executar) |

**Exemplo do problema (não fazer):**

```bash
python3.14 -c "
from passlib.context import CryptContext
import getpass
ctx = CryptContext(schemes=['bcrypt'])
print(ctx.hash(getpass.getpass('Senha: ')))
"
```

**Exemplo correto (fazer):**

```bash
python3.14 -c "from passlib.context import CryptContext; import getpass; ctx = CryptContext(schemes=['bcrypt']); print(ctx.hash(getpass.getpass('Senha: ')))"
```

Ou separar em etapas:

```bash
python3.14 -m pip install 'bcrypt' --break-system-packages -q
python3.14 -c "import bcrypt, getpass; pwd = getpass.getpass('Senha: ').encode(); print(bcrypt.hashpw(pwd, bcrypt.gensalt(12)).decode())"
```

## Consequences

- Comandos fornecidos por automações (Claude, scripts, docs) devem seguir este padrão
- Scripts com lógica complexa vivem em arquivos no repositório — não são colados no terminal
- A restrição vale apenas para o servidor; terminais locais (Windows PowerShell, Git Bash) não têm esse problema
