(function (global) {
  'use strict';

  const SUPPORTED_EXTENSIONS = ['csv', 'xlsx', 'xls'];
  const HEADER_ALIASES = [
    new Set(['aluno', 'nome']),
    new Set(['e-mail', 'email']),
    new Set(['matricula']),
  ];
  const HEADER_NAMES = new Set(HEADER_ALIASES.flatMap((aliases) => [...aliases]));

  function normalizeHeader(value) {
    return String(value ?? '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim()
      .replace(/\s+/g, ' ')
      .toLowerCase();
  }

  function isHeader(row) {
    return (row || []).length === 3 && HEADER_ALIASES.every(
      (aliases, index) => aliases.has(normalizeHeader(row[index]))
    );
  }

  // Espelha _looks_like_header do servidor: dois ou mais nomes de coluna numa
  // linha são um cabeçalho fora da ordem, nunca um aluno.
  function looksLikeHeader(row) {
    return (row || []).filter((value) => HEADER_NAMES.has(normalizeHeader(value))).length >= 2;
  }

  // Espelha is_valid_email (app/services/mail_service.py), a regra de todo envio
  // de e-mail do SGAA. O \s do Python também cobre \x1c-\x1f e \x85.
  const EMAIL_RE = /^[^@\s\x1c-\x1f\x85]+@[^@\s\x1c-\x1f\x85.]+(\.[^@\s\x1c-\x1f\x85.]+)+$/;

  function isValidEmail(value) {
    const candidate = String(value ?? '').trim();
    return Boolean(candidate) && candidate.length <= 254 && EMAIL_RE.test(candidate);
  }

  function normalizeRows(rows) {
    const nonEmpty = (rows || [])
      .map((row, index) => ({ values: row || [], sourceRow: index + 1 }))
      .filter(({ values }) => values.some((value) => String(value ?? '').trim()));
    if (!nonEmpty.length) throw new Error('Arquivo vazio.');

    const parsed = [];
    const seenEmails = new Map();
    const seenMatriculas = new Map();
    const firstDataIndex = isHeader(nonEmpty[0].values) ? 1 : 0;
    if (!firstDataIndex && looksLikeHeader(nonEmpty[0].values)) {
      throw new Error(
        `Linha ${nonEmpty[0].sourceRow}: o cabeçalho deve seguir exatamente esta ordem: Aluno, E-mail, Matricula.`
      );
    }
    for (let index = firstDataIndex; index < nonEmpty.length; index += 1) {
      const { values: row, sourceRow } = nonEmpty[index];
      if (index > 0 && looksLikeHeader(row)) {
        throw new Error(
          `Linha ${sourceRow}: cabeçalho repetido no meio do arquivo; o cabeçalho só é aceito na primeira linha.`
        );
      }
      if (row.length > 3) {
        throw new Error(
          `Linha ${sourceRow}: a linha deve ter exatamente 3 colunas: Aluno, E-mail, Matricula.`
        );
      }
      const values = [0, 1, 2].map((column) => String(row[column] ?? '').trim());
      if (values.some((value) => !value)) {
        throw new Error(`Linha ${sourceRow}: Aluno, E-mail e Matricula são obrigatórios.`);
      }
      if (!isValidEmail(values[1])) {
        throw new Error(`Linha ${sourceRow}: e-mail inválido.`);
      }
      const emailKey = values[1].toLowerCase();
      if (seenEmails.has(emailKey)) {
        throw new Error(`Linha ${sourceRow}: E-mail duplicado no arquivo.`);
      }
      if (seenMatriculas.has(values[2])) {
        throw new Error(`Linha ${sourceRow}: Matricula duplicada no arquivo.`);
      }
      seenEmails.set(emailKey, sourceRow);
      seenMatriculas.set(values[2], sourceRow);
      parsed.push({ aluno: values[0], email: values[1], matricula: values[2] });
    }
    if (!parsed.length) throw new Error('O arquivo não contém nenhum aluno para importar.');
    return parsed;
  }

  function readWorkbook(buffer, extension) {
    if (extension !== 'csv') {
      return global.XLSX.read(new Uint8Array(buffer), { type: 'array' });
    }
    // Como o servidor: CSV só em UTF-8, e cada célula permanece texto (sem
    // converter matrícula em número nem perder zeros à esquerda).
    let text;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
    } catch (_) {
      throw new Error('O CSV deve estar codificado em UTF-8.');
    }
    return global.XLSX.read(text, { type: 'string', raw: true });
  }

  function read(file) {
    if (!global.XLSX) return Promise.reject(new Error('Leitor de planilhas não carregado.'));
    const extension = String(file?.name || '').split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(extension)) {
      return Promise.reject(new Error('Formato não suportado. Use CSV, XLSX ou XLS.'));
    }

    return file.arrayBuffer().then((buffer) => {
      const workbook = readWorkbook(buffer, extension);
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      if (!sheet) throw new Error('Arquivo vazio.');
      const rows = global.XLSX.utils.sheet_to_json(sheet, {
        header: 1,
        raw: false,
        defval: '',
        range: 0,
      });
      return normalizeRows(rows);
    });
  }

  function isAvailable() {
    return Boolean(global.XLSX);
  }

  global.StudentImportPreview = Object.freeze({ isAvailable, read });
})(window);
