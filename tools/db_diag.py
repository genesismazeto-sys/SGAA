import os, sqlite3, json, re, sys
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.path.dirname(BASE), 'database.db')

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
c = con.cursor()

res = {}
# tables and columns
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
cols = lambda t: [dict(name=r[1], type=r[2], notnull=bool(r[3]), dflt=r[4], pk=bool(r[5])) for r in con.execute(f'PRAGMA table_info({t})')]
res['tables'] = {t: cols(t) for t in tabs if t in ('atividades','grupos_def','requisicoes','requisicao_arquivos','alunos')}

# atividades group patterns
get = lambda q,*p: c.execute(q,p).fetchone()[0]
res['atividades_counts'] = {
  'total': get('SELECT COUNT(*) FROM atividades'),
  'with_any_digit': get("SELECT COUNT(*) FROM atividades WHERE grupo IS NOT NULL AND grupo REGEXP '[0-9]'") if 'REGEXP' in ''.join(tabs) else get("SELECT COUNT(*) FROM atividades WHERE grupo IS NOT NULL AND grupo GLOB '*[0-9]*'"),
  'with_digit_start': get("SELECT COUNT(*) FROM atividades WHERE grupo IS NOT NULL AND grupo GLOB '[0-9]*'"),
  'with_hyphen_space': get("SELECT COUNT(*) FROM atividades WHERE grupo IS NOT NULL AND INSTR(grupo,' - ')>0"),
  'null_or_empty': get("SELECT COUNT(*) FROM atividades WHERE grupo IS NULL OR TRIM(grupo)='' ")
}

# samples
res['samples'] = {
  'non_digit_start': [dict(id=r['id'], grupo=r['grupo']) for r in c.execute("SELECT id, grupo FROM atividades WHERE grupo IS NOT NULL AND NOT (grupo GLOB '[0-9]*') LIMIT 10")],
  'no_digits_any': [dict(id=r['id'], grupo=r['grupo']) for r in c.execute("SELECT id, grupo FROM atividades WHERE grupo IS NOT NULL AND NOT (grupo GLOB '*[0-9]*') LIMIT 10")]
}

# grupos_def presence and mapping
res['grupos_def_exists'] = ('grupos_def' in tabs)
if res['grupos_def_exists']:
    res['grupos_def_count'] = get('SELECT COUNT(*) FROM grupos_def')
    res['grupos_def_samples'] = [dict(tipo=row[0], numero=row[1], descricao=row[2]) for row in c.execute('SELECT tipo_atividade, numero, descricao FROM grupos_def ORDER BY tipo_atividade, numero LIMIT 10')]

# cross-check: atividades without leading number but matching a grupos_def descricao for same tipo
cross_matches = []
if res['grupos_def_exists']:
    # build map tipo -> desc->numero
    gmap = {}
    for t, num, desc in c.execute('SELECT tipo_atividade, numero, descricao FROM grupos_def'):
        gmap.setdefault(t, {})[(desc or '').strip()] = str(num)
    for r in c.execute('SELECT id, tipo_atividade, grupo FROM atividades WHERE grupo IS NOT NULL AND NOT (grupo GLOB "[0-9]*")'):
        gid, tipo, grp = r
        if not grp:
            continue
        desc = grp.split(' - ', 1)[1].strip() if ' - ' in grp else grp.strip()
        numero = gmap.get(tipo, {}).get(desc)
        if numero:
            cross_matches.append({'id': gid, 'tipo': tipo, 'grupo': grp, 'numero_sugerido': numero})
res['desc_matches_suggested'] = cross_matches[:15]

print(json.dumps(res, ensure_ascii=False, indent=2))

# human-friendly summary
print('\n--- Summary ---')
ativ = res.get('tables',{}).get('atividades',[])
cols_ativ = [c['name'] for c in ativ]
if 'grupo' in cols_ativ and not any(n in cols_ativ for n in ('grupo_numero','grupo_descricao')):
    print('atividades: apenas coluna grupo (texto). Não há colunas separadas para número/descrição.')
if res.get('grupos_def_exists'):
    print('grupos_def: existe e guarda numero (int) + descricao (texto) por tipo_atividade (mapeamento canônico).')
print('Amostra de grupos sem número inicial:', len(res.get('samples',{}).get('non_digit_start',[])))
print('Sugestões por descrição (sem número):', len(res.get('desc_matches_suggested',[])))
