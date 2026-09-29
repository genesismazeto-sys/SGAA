(function (global) {
  'use strict';

  const SUPPORTED_EXTENSIONS = ['csv', 'xlsx', 'xls'];
  const HEADER_ALIASES = [
    new Set(['aluno', 'nome']),
    new Set(['e-mail', 'email']),
    new Set(['matricula']),
  ];
  const HEADER_NAMES = new Set(HEADER_ALIASES.flatMap((aliases) => [...aliases]));
  const COLUMN_LABELS = ['Aluno', 'E-mail', 'Matricula'];

  function normalizeHeader(value) {
    return String(value ?? '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim()
      .replace(/\s+/g, ' ')
      .toLowerCase();
  }

  // Espelha _header_name do servidor: uma fórmula nunca é nome de coluna,
  // qualquer que seja o valor calculado.
  function headerName(row, column, expressions) {
    return expressions.has(column) ? '' : normalizeHeader(row[column]);
  }

  function isHeader(row, expressions) {
    return (row || []).length === 3 && HEADER_ALIASES.every(
      (aliases, index) => aliases.has(headerName(row, index, expressions))
    );
  }

  // Espelha _looks_like_header do servidor: dois ou mais nomes de coluna numa
  // linha são um cabeçalho fora da ordem, nunca um aluno.
  function looksLikeHeader(row, expressions) {
    return (row || []).filter(
      (_, column) => HEADER_NAMES.has(headerName(row, column, expressions))
    ).length >= 2;
  }

  // Espelha is_valid_email (app/services/mail_service.py), a regra de todo envio
  // de e-mail do SGAA. O \s do Python também cobre \x1c-\x1f e \x85.
  const EMAIL_RE = /^[^@\s\x1c-\x1f\x85]+@[^@\s\x1c-\x1f\x85.]+(\.[^@\s\x1c-\x1f\x85.]+)+$/;

  function isValidEmail(value) {
    const candidate = String(value ?? '').trim();
    return Boolean(candidate) && candidate.length <= 254 && EMAIL_RE.test(candidate);
  }

  // expressionsByRow: índice da linha -> colunas com fórmula ou valor de erro.
  function normalizeRows(rows, expressionsByRow = new Map()) {
    const nonEmpty = (rows || [])
      .map((row, index) => ({
        values: row || [],
        sourceRow: index + 1,
        expressions: expressionsByRow.get(index) || new Set(),
      }))
      // Como no servidor, uma fórmula conta como conteúdo mesmo com cache vazio.
      .filter(({ values, expressions }) => (
        expressions.size > 0 || values.some((value) => String(value ?? '').trim())
      ));
    if (!nonEmpty.length) throw new Error('Arquivo vazio.');

    const parsed = [];
    const seenEmails = new Map();
    const seenMatriculas = new Map();
    const firstDataIndex = isHeader(nonEmpty[0].values, nonEmpty[0].expressions) ? 1 : 0;
    if (!firstDataIndex && looksLikeHeader(nonEmpty[0].values, nonEmpty[0].expressions)) {
      throw new Error(
        `Linha ${nonEmpty[0].sourceRow}: o cabeçalho deve seguir exatamente esta ordem: Aluno, E-mail, Matricula.`
      );
    }
    for (let index = firstDataIndex; index < nonEmpty.length; index += 1) {
      const { values: row, sourceRow, expressions } = nonEmpty[index];
      if (index > 0 && looksLikeHeader(row, expressions)) {
        throw new Error(
          `Linha ${sourceRow}: cabeçalho repetido no meio do arquivo; o cabeçalho só é aceito na primeira linha.`
        );
      }
      if (row.length > 3) {
        throw new Error(
          `Linha ${sourceRow}: a linha deve ter exatamente 3 colunas: Aluno, E-mail, Matricula.`
        );
      }
      const expressionColumn = [0, 1, 2].find((column) => expressions.has(column));
      if (expressionColumn !== undefined) {
        throw new Error(
          `Linha ${sourceRow}: fórmula ou valor de erro na coluna ${COLUMN_LABELS[expressionColumn]}; a importação aceita apenas valores digitados.`
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

  // Como o servidor, recusa a célula pelo tipo, nunca pelo valor calculado. Uma
  // segunda leitura com sheetStubs mantém a fórmula salva sem valor em cache,
  // que a leitura dos valores descarta; os valores seguem da leitura normal.
  function expressionCells(buffer, extension, sheet) {
    const found = new Map();
    if (extension === 'csv' || !sheet['!ref']) return found;
    const workbook = global.XLSX.read(new Uint8Array(buffer), { type: 'array', sheetStubs: true });
    const stubs = workbook.Sheets[workbook.SheetNames[0]] || {};
    const firstColumn = global.XLSX.utils.decode_range(sheet['!ref']).s.c;
    Object.keys(stubs).forEach((address) => {
      const cell = stubs[address];
      if (address[0] === '!' || !cell || !(cell.f || cell.t === 'e')) return;
      const { r, c } = global.XLSX.utils.decode_cell(address);
      if (!found.has(r)) found.set(r, new Set());
      found.get(r).add(c - firstColumn);
    });
    return found;
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
      return normalizeRows(rows, expressionCells(buffer, extension, sheet));
    });
  }

  function isAvailable() {
    return Boolean(global.XLSX);
  }

  global.StudentImportPreview = Object.freeze({ isAvailable, read });
})(window);
