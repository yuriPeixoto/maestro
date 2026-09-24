-- Maestro — setup de usuário dedicado no ClickHouse compartilhado da empresa (10.10.1.30)
--
-- Rodar manualmente via DataGrip, autenticado como `default` (admin).
-- NÃO automatizar via CI/migrations — esta instância é multi-tenant (serve outros
-- produtos, ex: Telemetria/cli_carvalima), então criação de usuário/database fica
-- fora do pipeline automático por segurança.
--
-- Contexto: docs/deployment.md descreve o mesmo padrão de least-privilege
-- (usuário `maestro_app`, GRANT restrito a maestro.*) só que pra VPS antiga
-- (153.75.226.75, desativada). Este script é o equivalente pro host novo.
--
-- NOTA: as migrations em migrations/*.sql têm "maestro." hardcoded no nome de
-- cada tabela (não usam o database corrente do console) — por isso não dá pra
-- separar dev/prod só trocando o database do console. Um único `maestro` serve
-- por enquanto; se algum dia quiser um ambiente dev de verdade, as migrations
-- precisam ser editadas pra referenciar o database via variável.

-- ============================================================
-- 1. Database dedicado — isolado de cli_carvalima e demais tenants
-- ============================================================

CREATE DATABASE IF NOT EXISTS maestro;

-- ============================================================
-- 2. Usuário dedicado, least-privilege (mesmo padrão do docs/deployment.md)
-- ============================================================

CREATE USER IF NOT EXISTS maestro_app
    IDENTIFIED WITH sha256_password BY 'CHANGE_ME_STRONG_PASSWORD';

GRANT SELECT, INSERT ON maestro.* TO maestro_app;

-- `default` continua sendo o único usuário com DDL (roda as migrations em
-- migrations/*.sql) — não revogar privilégios de `default`, mesma nota já
-- presente no docs/deployment.md.

-- ============================================================
-- 3. Verificação — confirmar que o escopo NÃO vaza pra cli_carvalima ou outros bancos
-- ============================================================

SHOW GRANTS FOR maestro_app;

-- ============================================================
-- Rollback
-- ============================================================
-- DROP USER IF EXISTS maestro_app;
-- DROP DATABASE IF EXISTS maestro;  -- ⚠️ só depois de confirmar que nada em produção depende disso

-- ============================================================
-- Limpeza do maestro_dev/maestro_app_dev criados na primeira tentativa
-- (a separação dev/prod não funciona com as migrations atuais — ver nota acima)
-- ============================================================
-- DROP USER IF EXISTS maestro_app_dev;
-- DROP DATABASE IF EXISTS maestro_dev;
