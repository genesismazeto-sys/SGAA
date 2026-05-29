# Auditoria de uso de static (2026-05-20)

## Resumo
- Total de arquivos em static: 35
- Usados definitivamente (existentes): 11
- Usados apenas em templates inativos (existentes): 0
- Não referenciados: 24
- Referências para caminhos inexistentes: 1

## Usados definitivamente (existentes)
- css/components/actions-float.css  (templates/admin_acesso.html:8, templates/admin_alertas.html:7, templates/admin_alunos.html:7)
- css/components/list-cards.css  (templates/admin_acesso.html:7, templates/admin_alertas.html:6, templates/admin_alunos.html:6)
- css/modern-style.css  (templates/400.html:10, templates/500.html:7, templates/base.html:15)
- images/ej_favicon.svg  (templates/base.html:16, templates/base_aluno.html:15)
- images/ej_logo.svg  (templates/base.html:40, templates/base_aluno.html:36)
- images/ej_logo_dark.jpg  (templates/login.html:13)
- js/csrf-shim.js  (templates/base.html:20, templates/base_aluno.html:23)
- js/password-toggle.js  (templates/base.html:24, templates/base_aluno.html:27, templates/login.html:8)
- js/table-ellipsis.js  (templates/base.html:23, templates/base_aluno.html:26)
- js/toolbar-filters.js  (templates/admin_acesso.html:567, templates/admin_alertas.html:346, templates/admin_alunos.html:150)
- js/ui-tooltips.js  (templates/base.html:22, templates/base_aluno.html:25)

## Não referenciados (candidatos a exclusão)
- css-copy/css/admin-style.css
- css-copy/css/modern-style - Copia.css
- css-copy/css/modern-style.css
- css/Backup/admin-style.css
- css/Backup/clientes-form-pack.css
- css/Backup/dead/admin-style.css
- css/Backup/dead/buttons.css
- css/Backup/dead/card.css
- css/Backup/dead/clientes-form-pack.css
- css/Backup/dead/compat.css
- css/Backup/dead/modern-style-CS.css
- css/Backup/dead/table.css
- css/Backup/dead/tokens.css
- css/Backup/impressao-style.css
- css/Backup/impressao-style.css.bak
- css/Backup/modern-style - Copia (2).css
- css/Backup/modern-style-CS.css
- css/Backup/modern-style.css
- css/Backup/modern-style.css.bak
- images/ej_logo_blue.png
- images/ej_logo_dark.png
- images/logo.jpg
- images/logoblueantigo.png
- js/Backup/documentos_pills.js

## Referenciados mas inexistentes
- css/clientes-form-pack.css

## Observações
- A classificação usado definitivamente considera referências em templates ativos detectados via render_template literal + cadeia de extends/include/import e em código Python runtime.
- Itens em templates inativos foram separados para revisão manual.