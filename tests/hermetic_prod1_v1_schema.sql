
CREATE TABLE schema_migrations (
 version INTEGER PRIMARY KEY, name TEXT NOT NULL, schema_epoch TEXT NOT NULL,
 applied_at TEXT NOT NULL DEFAULT (datetime('now')), details_json TEXT
);
CREATE TABLE usuarios (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
 senha TEXT NOT NULL, tipo TEXT NOT NULL CHECK(tipo IN ('admin','aluno')),
 nivel_acesso TEXT NOT NULL DEFAULT 'administrativo', foto_perfil TEXT
);
CREATE TABLE configuracoes_acesso (nivel_acesso TEXT PRIMARY KEY, senha_padrao TEXT NOT NULL);
CREATE TABLE usuarios_permissoes_acesso (
 usuario_id INTEGER NOT NULL, recurso TEXT NOT NULL, escopo TEXT NOT NULL,
 PRIMARY KEY(usuario_id,recurso),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE TABLE configuracoes_app (
 chave TEXT PRIMARY KEY, valor TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE configuracoes_backup (
 chave TEXT PRIMARY KEY, valor TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE configuracoes_presets (
 tipo TEXT NOT NULL CHECK(tipo IN ('respostas','emails')), preset_id INTEGER NOT NULL,
 titulo TEXT NOT NULL, texto TEXT NOT NULL DEFAULT '',
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(tipo,preset_id)
);
CREATE TABLE cloud_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, account_email TEXT,
 token_json TEXT NOT NULL, connected_at TEXT DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT, active INTEGER DEFAULT 1
);
CREATE TABLE backup_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, file_name TEXT, file_size INTEGER,
 status TEXT, error_message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE cloud_drive_settings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL UNIQUE, folder_id TEXT,
 folder_name TEXT, folder_path_label TEXT, drive_id TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE mensagens_editaveis (
 chave TEXT PRIMARY KEY, texto TEXT NOT NULL,
 atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE cursos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, codigo TEXT NOT NULL UNIQUE,
 duracao_periodos INTEGER NOT NULL CHECK(duracao_periodos>0),
 total_horas_aac INTEGER NOT NULL DEFAULT 160 CHECK(total_horas_aac>=0),
 total_horas_aeu INTEGER NOT NULL DEFAULT 80 CHECK(total_horas_aeu>=0),
 periodo TEXT NOT NULL DEFAULT 'diurno',
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo'))
);
CREATE TABLE matrizes_atividades (
 id INTEGER PRIMARY KEY AUTOINCREMENT, curso_id INTEGER NOT NULL, nome TEXT NOT NULL,
 versao TEXT NOT NULL, descricao TEXT,
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','vigente','encerrada','ativa','inativa')),
 data_inicio_vigencia TEXT, data_fim_vigencia TEXT,
 horas_aac_obrigatorias INTEGER NOT NULL DEFAULT 160 CHECK(horas_aac_obrigatorias>=0),
 horas_extensao_obrigatorias INTEGER NOT NULL DEFAULT 80 CHECK(horas_extensao_obrigatorias>=0),
 matriz_origem_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(curso_id) REFERENCES cursos(id) ON DELETE RESTRICT,
 FOREIGN KEY(matriz_origem_id) REFERENCES matrizes_atividades(id) ON DELETE RESTRICT
);
CREATE TABLE turmas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE, turno TEXT,
 status TEXT NOT NULL DEFAULT 'Ativa' CHECK(status IN ('Ativa','Inativa')),
 numero INTEGER NOT NULL, curso_id INTEGER NOT NULL, ano_inicio INTEGER NOT NULL,
 semestre_inicio INTEGER NOT NULL CHECK(semestre_inicio IN (1,2)), codigo TEXT NOT NULL UNIQUE,
 matriz_id INTEGER, ano_fim INTEGER, semestre_fim INTEGER CHECK(semestre_fim IN (1,2)),
 FOREIGN KEY(curso_id) REFERENCES cursos(id) ON DELETE RESTRICT,
 FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE RESTRICT,
 UNIQUE(curso_id,numero)
);
CREATE TABLE alunos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER UNIQUE, nome TEXT NOT NULL,
 matricula TEXT UNIQUE NOT NULL, email TEXT UNIQUE, turma_id INTEGER, foto_perfil TEXT,
 status TEXT DEFAULT 'Ativo' CHECK(status IN ('Ativo','Inativo')),
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE,
 FOREIGN KEY(turma_id) REFERENCES turmas(id) ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE TABLE grupos_def (
 tipo_atividade TEXT NOT NULL CHECK(tipo_atividade IN ('Acadêmica Complementar','Extensão Universitária')),
 numero INTEGER NOT NULL CHECK(numero>0), descricao TEXT,
 PRIMARY KEY(tipo_atividade,numero)
);
CREATE TABLE atividade_base (
 id INTEGER PRIMARY KEY AUTOINCREMENT, nome_conceito TEXT NOT NULL UNIQUE, descricao TEXT,
 status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo')),
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE norma_atividade (
 id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
 eixo TEXT NOT NULL CHECK(eixo IN ('AAC','AEU')), revisao TEXT NOT NULL,
 nome TEXT, descricao TEXT, status TEXT NOT NULL DEFAULT 'ativa' CHECK(status IN ('ativa','inativa')),
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE atividade_versao (
 id INTEGER PRIMARY KEY AUTOINCREMENT, atividade_base_id INTEGER NOT NULL,
 norma_id INTEGER NOT NULL, codigo_normativo TEXT NOT NULL,
 eixo TEXT NOT NULL CHECK(eixo IN ('AAC','AEU')), grupo TEXT,
 ch_por_evento REAL CHECK(ch_por_evento IS NULL OR ch_por_evento>=0),
 limite_semestre REAL CHECK(limite_semestre IS NULL OR limite_semestre>=0),
 limite_total REAL CHECK(limite_total IS NULL OR limite_total>=0),
 observacao_aluno TEXT, observacao_admin TEXT,
 documentos_json TEXT CHECK(documentos_json IS NULL OR json_valid(documentos_json)),
 vigencia_inicio TEXT, vigencia_fim TEXT,
 numero_versao INTEGER NOT NULL DEFAULT 1 CHECK(numero_versao>=1),
 status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho','ativa','inativa','descontinuada','substituida')),
 versao_anterior_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
 FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
 FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 UNIQUE(atividade_base_id,numero_versao), UNIQUE(id,atividade_base_id)
);
CREATE TABLE atividade_transicao (
 id INTEGER PRIMARY KEY AUTOINCREMENT, from_atividade_versao_id INTEGER,
 to_atividade_versao_id INTEGER,
 tipo_transicao TEXT NOT NULL CHECK(tipo_transicao IN ('mesmo_eixo','aac_para_aeu','nova_aeu','descontinuada','sem_transicao')),
 justificativa TEXT, observacao_admin TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(from_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 FOREIGN KEY(to_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
 CHECK(from_atividade_versao_id IS NOT NULL OR to_atividade_versao_id IS NOT NULL),
 CHECK(from_atividade_versao_id IS NULL OR to_atividade_versao_id IS NULL OR from_atividade_versao_id<>to_atividade_versao_id)
);
CREATE TABLE matriz_norma (
 id INTEGER PRIMARY KEY AUTOINCREMENT, matriz_id INTEGER NOT NULL, norma_id INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
 FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
 UNIQUE(matriz_id,norma_id)
);
CREATE TABLE matriz_atividade_versao_item (
 id INTEGER PRIMARY KEY AUTOINCREMENT, matriz_id INTEGER NOT NULL,
 atividade_base_id INTEGER NOT NULL, atividade_versao_id INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(matriz_id) REFERENCES matrizes_atividades(id) ON DELETE CASCADE,
 FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
 FOREIGN KEY(atividade_versao_id,atividade_base_id) REFERENCES atividade_versao(id,atividade_base_id) ON DELETE RESTRICT,
 UNIQUE(matriz_id,atividade_base_id), UNIQUE(matriz_id,atividade_versao_id)
);
CREATE TABLE requisicoes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER, atividade_versao_id INTEGER NOT NULL,
 data_solicitacao TEXT NOT NULL, data_evento TEXT NOT NULL,
 horas_solicitadas REAL NOT NULL CHECK(horas_solicitadas>=0), nome_evento TEXT,
 status TEXT NOT NULL CHECK(status IN ('Pendente','Deferida','Deferida Parcialmente','Indeferida','Devolvida','Encerrada')),
 horas_deferidas REAL CHECK(horas_deferidas IS NULL OR horas_deferidas>=0), observacao TEXT,
 data_processamento TEXT, admin_id INTEGER, aluno_update_notified_at TEXT,
 aluno_update_seen_at TEXT,
 regra_snapshot_json TEXT NOT NULL CHECK(json_valid(regra_snapshot_json) AND json_type(regra_snapshot_json)='object'),
 codigo_normativo_snapshot TEXT NOT NULL CHECK(TRIM(codigo_normativo_snapshot)<>''),
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE SET NULL ON UPDATE CASCADE,
 FOREIGN KEY(atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT ON UPDATE CASCADE,
 FOREIGN KEY(admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE requisicao_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, requisicao_id INTEGER NOT NULL, label TEXT,
 filename TEXT NOT NULL, criado_em TEXT DEFAULT (datetime('now')),
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE
);
CREATE TABLE requisicao_alerta_receipts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, requisicao_id INTEGER NOT NULL,
 usuario_id INTEGER NOT NULL, alert_kind TEXT NOT NULL,
 seen_at TEXT NOT NULL DEFAULT (datetime('now')),
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE ON UPDATE CASCADE,
 FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE,
 UNIQUE(requisicao_id,usuario_id,alert_kind)
);
CREATE TABLE reportes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, aluno_id INTEGER NOT NULL, titulo TEXT NOT NULL,
 descricao TEXT NOT NULL, categoria TEXT NOT NULL DEFAULT 'Bug na plataforma',
 screenshot_filename TEXT, status TEXT NOT NULL DEFAULT 'Novo' CHECK(status IN ('Novo','Em análise','Resolvido')),
 criado_em TEXT NOT NULL DEFAULT (datetime('now')), atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
 admin_id INTEGER,
 FOREIGN KEY(aluno_id) REFERENCES alunos(id) ON DELETE CASCADE ON UPDATE CASCADE,
 FOREIGN KEY(admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE admin_arquivos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descricao TEXT,
 filename TEXT NOT NULL, original_filename TEXT, visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)),
 criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE admin_alertas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT, mensagem TEXT NOT NULL,
 bg_color TEXT NOT NULL DEFAULT '#eff6ff', border_color TEXT NOT NULL DEFAULT '#bfdbfe',
 visivel INTEGER NOT NULL DEFAULT 1 CHECK(visivel IN (0,1)), criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_usuarios_email ON usuarios(email);
CREATE INDEX idx_usuarios_permissoes_usuario ON usuarios_permissoes_acesso(usuario_id);
CREATE INDEX idx_cloud_accounts_provider_active ON cloud_accounts(provider,active,id DESC);
CREATE INDEX idx_backup_logs_provider_created ON backup_logs(provider,created_at DESC,id DESC);
CREATE INDEX idx_turmas_status ON turmas(status); CREATE INDEX idx_turmas_curso ON turmas(curso_id);
CREATE INDEX idx_turmas_matriz ON turmas(matriz_id); CREATE INDEX idx_alunos_usuario_id ON alunos(usuario_id);
CREATE INDEX idx_alunos_matricula ON alunos(matricula); CREATE INDEX idx_alunos_email ON alunos(email);
CREATE INDEX idx_alunos_turma_id ON alunos(turma_id); CREATE INDEX idx_norma_atividade_codigo ON norma_atividade(codigo);
CREATE INDEX idx_norma_atividade_eixo ON norma_atividade(eixo); CREATE INDEX idx_atividade_versao_base ON atividade_versao(atividade_base_id);
CREATE INDEX idx_atividade_versao_norma ON atividade_versao(norma_id); CREATE INDEX idx_atividade_versao_eixo ON atividade_versao(eixo);
CREATE INDEX idx_atividade_versao_status ON atividade_versao(status); CREATE INDEX idx_atividade_transicao_from ON atividade_transicao(from_atividade_versao_id);
CREATE INDEX idx_atividade_transicao_to ON atividade_transicao(to_atividade_versao_id); CREATE INDEX idx_atividade_transicao_tipo ON atividade_transicao(tipo_transicao);
CREATE INDEX idx_matrizes_curso ON matrizes_atividades(curso_id); CREATE INDEX idx_matrizes_status ON matrizes_atividades(status);
CREATE INDEX idx_matriz_norma_matriz ON matriz_norma(matriz_id); CREATE INDEX idx_matriz_norma_norma ON matriz_norma(norma_id);
CREATE INDEX idx_matriz_atividade_versao_item_matriz ON matriz_atividade_versao_item(matriz_id);
CREATE INDEX idx_matriz_atividade_versao_item_base ON matriz_atividade_versao_item(atividade_base_id);
CREATE INDEX idx_matriz_atividade_versao_item_versao ON matriz_atividade_versao_item(atividade_versao_id);
CREATE INDEX idx_reqs_aluno ON requisicoes(aluno_id); CREATE INDEX idx_reqs_status ON requisicoes(status);
CREATE INDEX idx_requisicoes_atividade_versao_id ON requisicoes(atividade_versao_id);
CREATE INDEX idx_reqs_aluno_update_pending ON requisicoes(aluno_id,aluno_update_seen_at,aluno_update_notified_at);
CREATE INDEX idx_req_arquivos_req ON requisicao_arquivos(requisicao_id);
CREATE INDEX idx_req_alert_receipts_user_kind ON requisicao_alerta_receipts(usuario_id,alert_kind);
CREATE INDEX idx_req_alert_receipts_req ON requisicao_alerta_receipts(requisicao_id);
CREATE INDEX idx_reportes_aluno_id ON reportes(aluno_id); CREATE INDEX idx_reportes_status ON reportes(status);
CREATE INDEX idx_reportes_criado_em ON reportes(criado_em); CREATE INDEX idx_admin_arquivos_visivel ON admin_arquivos(visivel);
CREATE INDEX idx_admin_arquivos_criado_em ON admin_arquivos(criado_em); CREATE INDEX idx_admin_alertas_visivel ON admin_alertas(visivel);

CREATE TRIGGER trg_atividade_versao_eixo_norma_insert BEFORE INSERT ON atividade_versao
FOR EACH ROW WHEN EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id=NEW.norma_id AND n.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'atividade_versao.eixo incompatível com norma_atividade.eixo'); END;
CREATE TRIGGER trg_atividade_versao_eixo_norma_update BEFORE UPDATE OF norma_id,eixo ON atividade_versao
FOR EACH ROW WHEN EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id=NEW.norma_id AND n.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'atividade_versao.eixo incompatível com norma_atividade.eixo'); END;
CREATE TRIGGER trg_atividade_versao_prev_same_eixo_insert BEFORE INSERT ON atividade_versao
FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END;
CREATE TRIGGER trg_atividade_versao_prev_same_eixo_update BEFORE UPDATE OF versao_anterior_id,eixo ON atividade_versao
FOR EACH ROW WHEN NEW.versao_anterior_id IS NOT NULL AND EXISTS(SELECT 1 FROM atividade_versao p WHERE p.id=NEW.versao_anterior_id AND p.eixo<>NEW.eixo)
BEGIN SELECT RAISE(ABORT,'Mudança de eixo exige atividade_transicao'); END;
CREATE TRIGGER trg_atividade_transicao_aac_para_aeu_insert BEFORE INSERT ON atividade_transicao
FOR EACH ROW WHEN NEW.tipo_transicao='aac_para_aeu' BEGIN
 SELECT CASE WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa)='' THEN RAISE(ABORT,'Transição aac_para_aeu exige justificativa') END;
 SELECT CASE WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL THEN RAISE(ABORT,'Transição aac_para_aeu exige from/to atividade_versao') END;
 SELECT CASE WHEN (SELECT eixo FROM atividade_versao WHERE id=NEW.from_atividade_versao_id)<>'AAC' OR (SELECT eixo FROM atividade_versao WHERE id=NEW.to_atividade_versao_id)<>'AEU' THEN RAISE(ABORT,'Transição aac_para_aeu exige eixo AAC -> AEU') END;
END;
CREATE TRIGGER trg_atividade_transicao_aac_para_aeu_update BEFORE UPDATE OF tipo_transicao,justificativa,from_atividade_versao_id,to_atividade_versao_id ON atividade_transicao
FOR EACH ROW WHEN NEW.tipo_transicao='aac_para_aeu' BEGIN
 SELECT CASE WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa)='' THEN RAISE(ABORT,'Transição aac_para_aeu exige justificativa') END;
 SELECT CASE WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL THEN RAISE(ABORT,'Transição aac_para_aeu exige from/to atividade_versao') END;
 SELECT CASE WHEN (SELECT eixo FROM atividade_versao WHERE id=NEW.from_atividade_versao_id)<>'AAC' OR (SELECT eixo FROM atividade_versao WHERE id=NEW.to_atividade_versao_id)<>'AEU' THEN RAISE(ABORT,'Transição aac_para_aeu exige eixo AAC -> AEU') END;
END;
CREATE TRIGGER trg_requisicoes_snapshot_immutable
BEFORE UPDATE OF atividade_versao_id,regra_snapshot_json,codigo_normativo_snapshot ON requisicoes
FOR EACH ROW WHEN NEW.atividade_versao_id<>OLD.atividade_versao_id OR NEW.regra_snapshot_json<>OLD.regra_snapshot_json OR NEW.codigo_normativo_snapshot<>OLD.codigo_normativo_snapshot
BEGIN SELECT RAISE(ABORT,'request snapshot authority is immutable'); END;

INSERT INTO schema_migrations(version,name,schema_epoch,details_json)
VALUES(1,'first_production_baseline','prod-1','{"schema_epoch":"prod-1"}');
PRAGMA user_version=1;
