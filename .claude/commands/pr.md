Você está criando um Pull Request para o projeto Maestro.

Contexto adicional (se fornecido): $ARGUMENTS

Execute os seguintes passos:

1. **Verifique o estado atual:**
   ```bash
   git status
   git log --oneline main..HEAD
   git diff main...HEAD --stat
   ```

2. **Confirme que está tudo pronto por componente:**
   - Go: `go vet ./...` e `go test ./...` passando
   - Python: testes passando, sem erros de lint
   - Frontend: `npm run type-check` passando

3. **Crie o PR** via `gh pr create` com o template abaixo.
   Base branch: `main`.

```
gh pr create --base main --title "<título conciso em inglês>" --body "$(cat <<'EOF'
## Summary

- <o que foi implementado>
- <decisões técnicas relevantes>

## Components Changed

- [ ] Agent (Go)
- [ ] API (Python)
- [ ] Frontend (React)
- [ ] Infra / Config

## Test Plan

- [ ] Go: `go test ./...` passando
- [ ] Python: testes passando
- [ ] Frontend: `npm run type-check` passando
- [ ] Testado manualmente

## Notes

<contexto adicional, trade-offs, próximos passos>

Closes #<número da issue>
EOF
)"
```

4. **Retorne a URL do PR** criado.
