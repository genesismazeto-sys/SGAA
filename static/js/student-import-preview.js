(function (global) {
  'use strict';

  const SUPPORTED_EXTENSIONS = ['csv', 'xlsx', 'xls'];

  function normalizeHeader(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim()
      .toLowerCase();
  }

  function normalizeRows(rows) {
    const nonEmpty = (rows || []).filter((row) =>
      (row || []).some((value) => String(value ?? '').trim())
    );
    if (!nonEmpty.length) throw new Error('Arquivo vazio.');

    const header = (nonEmpty[0] || []).map(normalizeHeader);
    const validHeader =
      (header[0] === 'aluno' || header[0] === 'nome') &&
      (header[1] === 'e-mail' || header[1] === 'email') &&
      header[2] === 'matricula' &&
      header.length === 3;
    if (!validHeader) {
      throw new Error('O cabeçalho deve seguir exatamente esta ordem: Aluno, E-mail, Matricula.');
    }

    const parsed = [];
    const seenEmails = new Map();
    const seenMatriculas = new Map();
    for (let index = 1; index < nonEmpty.length; index += 1) {
      const row = nonEmpty[index] || [];
      if (row.length > 3) {
        throw new Error(`Linha ${index + 1}: colunas extras não são permitidas.`);
      }
      const values = [0, 1, 2].map((column) => String(row[column] ?? '').trim());
      if (values.some((value) => !value)) {
        throw new Error(`Linha ${index + 1}: Aluno, E-mail e Matricula são obrigatórios.`);
      }
      const emailKey = values[1].toLowerCase();
      if (seenEmails.has(emailKey)) {
        throw new Error(`Linha ${index + 1}: E-mail duplicado no arquivo.`);
      }
      if (seenMatriculas.has(values[2])) {
        throw new Error(`Linha ${index + 1}: Matricula duplicada no arquivo.`);
      }
      seenEmails.set(emailKey, index + 1);
      seenMatriculas.set(values[2], index + 1);
      parsed.push({ aluno: values[0], email: values[1], matricula: values[2] });
    }
    if (!parsed.length) throw new Error('O arquivo não contém nenhum aluno para importar.');
    return parsed;
  }

  function read(file) {
    if (!global.XLSX) return Promise.reject(new Error('Leitor de planilhas não carregado.'));
    const extension = String(file?.name || '').split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(extension)) {
      return Promise.reject(new Error('Formato não suportado. Use CSV, XLSX ou XLS.'));
    }

    return file.arrayBuffer().then((buffer) => {
      const workbook = global.XLSX.read(new Uint8Array(buffer), { type: 'array' });
      const sheet = workbook.Sheets[workbook.SheetNames[0]];
      if (!sheet) throw new Error('Arquivo vazio.');
      const rows = global.XLSX.utils.sheet_to_json(sheet, {
        header: 1,
        raw: false,
        defval: '',
      });
      return normalizeRows(rows);
    });
  }

  global.StudentImportPreview = Object.freeze({ read });
})(window);
