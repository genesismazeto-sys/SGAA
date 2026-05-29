# Release 1.0 checks

## Resultado final atual

- release suite: 14 passed
- pytest completo: 123 passed
- smoke basico: ok
- smoke admin: ok
- smoke RBAC: 51 passed
- observacao: Google Drive/OneDrive real e Playwright/E2E permanecem fora da automacao desta versao.

## Cobertura funcional adicional da suite 1.0

- Acoes reais por modulo administrativo sensivel (Alertas, Reportes, Arquivos e Requisicoes).
- Validacao de permissoes de escrita por perfil (permitido x bloqueado) para operacoes administrativas.
- Verificacao de ausencia de erro 405 (Method Not Allowed) nos fluxos de alteracao testados.
- Regressao com CSRF ativo no fluxo real de Reportes (status e exclusao), incluindo cenario sem token (400) e com token valido (sucesso).
- Acoes administrativas POST agora possuem verificacao dedicada com CSRF ativo em `tests/test_release_admin_actions_csrf.py`.
- Mensagens de sistema e Reportes possuem regressao CSRF especifica (com token valido e sem token).
- Testes executados com CSRF desabilitado nao sao suficientes para aprovar fechamento de release.
