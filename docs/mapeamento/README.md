# Mapeamento completo do SGAA

Documentação de arquitetura do **SGAA** (Sistema de Gestão de Atividades
Acadêmicas) — app Flask para gestão de Atividades Acadêmicas Complementares
(AAC) e Atividades de Extensão Universitária (AEU) de uma faculdade.

Esta pasta foi escrita para servir de **mapa canônico** do app, tanto para
humanos quanto para IAs que forem trabalhar no código. Cada arquivo cobre uma
fatia do sistema.

> Gerado em 2026-06-21 a partir do estado da branch `main`.

## Índice

| # | Arquivo | Conteúdo |
|---|---------|----------|
| 00 | [00_visao_geral.md](00_visao_geral.md) | Stack, como roda, estatísticas, estrutura de pastas, fluxo de uma requisição |
| 01 | [01_rotas.md](01_rotas.md) | Mapa **completo** de rotas (URL, métodos, view, permissão exigida, template) |
| 02 | [02_autenticacao_e_seguranca.md](02_autenticacao_e_seguranca.md) | Login, sessão, RBAC por recurso/escopo, CSRF, headers, hashing, rate limit |
| 03 | [03_banco_de_dados.md](03_banco_de_dados.md) | Schema completo (32 tabelas), relacionamentos, índices, migrações |
| 04 | [04_arquitetura_e_modulos.md](04_arquitetura_e_modulos.md) | Quebra por módulo, dependências, dívidas técnicas (monólito, ciclos, código morto) |
| 05 | [05_avaliacao_refactor.md](05_avaliacao_refactor.md) | **Pergunta 1:** vale refatorar? Plano incremental sem quebrar nada |
| 06 | [06_deploy_e_infraestrutura.md](06_deploy_e_infraestrutura.md) | **Pergunta 2:** onde hospedar (~100 alunos, custo baixo). Vercel vs Supabase vs VPS |

## Resumo executivo (TL;DR)

- **Stack:** Python 3 + Flask 3, SQLite (WAL), Jinja2, sem framework JS (HTML
  server-rendered + JS vanilla). Backups OAuth para Google Drive / OneDrive.
- **Tamanho:** ~54 mil linhas de Python; **`main.py` sozinho tem 15.494 linhas**
  e concentra ~113 rotas + toda a lógica de negócio e schema.
- **Dados reais hoje:** 71 usuários, 70 alunos, 41 requisições, 2 turmas, 1 curso.
- **Estado geral:** o app é **robusto e maduro** em segurança (RBAC granular,
  CSRF, PBKDF2, rate limiting, headers, 70 arquivos de teste). O problema **não
  é qualidade — é organização**: um monólito gigante com dependências circulares
  e código morto que dificulta a vida de qualquer pessoa (ou IA) que mexa nele.
- **Refator (P1):** recomendado, mas **incremental e guiado por testes**, não um
  rewrite. Ver [05](05_avaliacao_refactor.md).
- **Deploy (P2):** o desenho atual (SQLite + escrita em disco + backups locais)
  **não combina com Vercel/serverless**. A recomendação para ~100 alunos é uma
  **VPS barata (Fly.io / Render / VPS ~US$5/mês) com disco persistente**, ou
  migrar o banco para **Postgres gerenciado (Supabase/Neon)** se quiser escalar.
  Ver [06](06_deploy_e_infraestrutura.md).
