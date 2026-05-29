"""
Restaura as matrículas corretas dos alunos das turmas T10 e T11.
Também corrige a turma do Cauã Eric da Silva Souza (T11 → T10).
"""
import sqlite3

DB = "database.db"

# Matrículas corretas por nome
T10_MATRICULAS = {
    "Alexandre Posenatto": "25.01.PPA-3.206",
    "Arthur Bispo Almeida": "25.01.PPA-3.208",
    "Breno Kubinyec Furlan": "25.01.PPA-3.207",
    "Cauã Eric da Silva Souza": "25.01.PPA-3.209",
    "Eduarda Aparecida de Lima Setti": "25.01.PPA-3.211",
    "Guilherme Marcelino Silva": "25.02.PPA-3.26",
    "Guilherme Pereira Stranghetti": "25.01.PPA-3.234",
    "Gustavo Alves Ribeiro": "25.01.PPA-3.214",
    "Gustavo Caldas Ximenes": "25.01.PPA-3.215",
    "Heitor Beloti e Silva": "25.01.PPA-3.223",
    "Helena Marostica de Oliveira": "25.01.PPA-3.216",
    "Israel Sant' Ana Campos": "25.01.PPA-3.217",
    "João Guilherme Batista Coimbra Benevello": "25.01.PPA-3.218",
    "João Luca Siqueira Passarin": "25.01.PPA-3.219",
    "João Moreira Estefan": "25.01.PPA-3.220",
    "João Vitor Ramos da Silva": "25.01.PPA-3.221",
    "Leonardo Birolin Fossen": "25.01.PPA-3.222",
    "Matheus Dioto Fumagalli": "25.01.PPA-3.224",
    "Miguel Henrique de Oliveira": "25.01.PPA-3.225",
    "Pedro Maganha Capellari": "25.01.PPA-3.227",
    "Rafael Castro Barbosa": "25.01.PPA-3.228",
    "Renato de Oliveira Carneiro": "25.01.PPA-3.170",
    "Thiago Borges Gregorio": "25.01.PPA-3.231",
    "Tiago de Araújo Dayube": "25.01.PPA-3.232",
}

T11_MATRICULAS = {
    "André Luiz de Queiroz Martins": "26.01.PPA-3.274",
    "Anthony Leônidas Moreira": "26.01.PPA-3.273",
    "Ariel Zanardi": "26.01.PPA-3.260",
    "Augusto Naruhito de Alvarenga Mitsuse": "26.01.PPA-3.261",
    "Caio Henrique dos Santos Simões": "26.01.PPA-3.270",
    "Cauã Roberto Rios Cezar": "26.01.PPA-3.262",
    "Cauã Schott Ranuci": "26.01.PPA-3.263",
    "Daniel Paulo de Lima Dias Filho": "26.01.PPA-3.244",
    "Douglas Ferreira Pradines": "26.01.PPA-3.271",
    "Eduarda Nicolly Freitas Santos": "26.01.PPA-3.245",
    "Eduardo Fernandes Aguiar": "26.01.PPA-3.264",
    "Emely Lucas Mangrasse": "26.01.PPA-3.281",
    "Enzo Bortolato": "26.01.PPA-3.279",
    "Éverto Luza Mognon": "26.01.PPA-3.265",
    "Felipe Borges Oliveira": "26.01.PPA-3.241",
    "Felipe Fernandes Xavier": "26.01.PPA-3.240",
    "Felipe Garcia Constantino": "26.01.PPA-3.278",
    "Felipe Teixeira Silva": "26.01.PPA-3.248",
    "Gabriel Sossai Suzano Rodrigues": "26.01.PPA-3.238",
    "Henry Martins Nogueira": "26.01.PPA-3.269",
    "Igor Martins da Costa Lage": "26.01.PPA-3.251",
    "Joaquim Portezan e Silva": "26.01.PPA-3.252",
    "José Icaro Silva Nogueira": "26.01.PPA-3.272",
    "Juan David Munoz Libreros": "26.01.PPA-3.253",
    "Kauã Bassaga Souza": "26.01.PPA-3.254",
    "Leandro Blöchliger Canuto": "26.01.PPA-3.255",
    "Lucas Gabriel Perissato": "26.01.PPA-3.280",
    "Luciano Oliveira Campos": "26.01.PPA-3.266",
    "Luiz Felipe Pickhardt Degow": "26.01.PPA-3.256",
    "Luiz Fernando Matos Chagas Silva": "26.01.PPA-3.257",
    "Marcos Matheus Saraiva Nunez": "26.01.PPA-3.275",
    "Marcus Augustus Soares de Souza": "26.01.PPA-3.247",
    "Maria Eduarda Vilela Lopes": "26.01.PPA-3.258",
    "Matheus Bolonha Camilo": "26.01.PPA-3.259",
    "Mauricio Vicente Boava": "26.01.PPA-3.237",
    "Murillo Rodrigues de Sousa": "26.01.PPA-3.276",
    "Nicolle Lopes Grilli": "26.01.PPA-3.267",
    "Nikolas Daniel Sarte": "26.01.PPA-3.242",
    "Nolan Huntingford Vianna": "26.01.PPA-3.268",
    "Pedro Machado Jenkins de Lemos": "26.01.PPA-3.239",
    "Pietro Bernardes Guimarães": "26.01.PPA-3.243",
    "Rafael Noce Fraga Mol": "26.01.PPA-3.250",
    "Rafael Pesci Palmeiro": "26.01.PPA-3.235",
    "Victor Hugo Bittencourt de Souza": "26.01.PPA-3.236",
    "Wandrew Gustavo Silva Oliveira": "26.01.PPA-3.249",
}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Obter IDs das turmas
t10 = conn.execute("SELECT id FROM turmas WHERE codigo = 'PPA-T10'").fetchone()
t11 = conn.execute("SELECT id FROM turmas WHERE codigo = 'PPA-T11'").fetchone()

if not t10 or not t11:
    print("ERRO: Turmas PPA-T10 ou PPA-T11 não encontradas!")
    conn.close()
    exit(1)

t10_id = t10["id"]
t11_id = t11["id"]
print(f"T10 id={t10_id}, T11 id={t11_id}")

updates = 0
nao_encontrados = []

# Corrigir Cauã Eric: mover de T11 para T10 e atualizar matrícula
caua = conn.execute("SELECT id, nome, turma_id FROM alunos WHERE nome = 'Cauã Eric da Silva Souza'").fetchone()
if caua:
    if caua["turma_id"] == t11_id:
        conn.execute("UPDATE alunos SET turma_id = ?, matricula = ? WHERE id = ?",
                     (t10_id, "25.01.PPA-3.209", caua["id"]))
        print(f"  MOVIDO T11→T10 + matrícula corrigida: Cauã Eric da Silva Souza → 25.01.PPA-3.209")
        updates += 1
    else:
        conn.execute("UPDATE alunos SET matricula = ? WHERE id = ?",
                     ("25.01.PPA-3.209", caua["id"]))
        print(f"  Matrícula corrigida (já em T10): Cauã Eric da Silva Souza → 25.01.PPA-3.209")
        updates += 1
else:
    print("  AVISO: Cauã Eric da Silva Souza não encontrado!")

# Atualizar matrículas T10
alunos_t10 = conn.execute("SELECT id, nome FROM alunos WHERE turma_id = ? OR (nome = 'Cauã Eric da Silva Souza')", (t10_id,)).fetchall()
nomes_t10 = {a["nome"]: a["id"] for a in alunos_t10}

for nome, mat in T10_MATRICULAS.items():
    if nome == "Cauã Eric da Silva Souza":
        continue  # já tratado acima
    aluno_id = nomes_t10.get(nome)
    if aluno_id:
        conn.execute("UPDATE alunos SET matricula = ? WHERE id = ?", (mat, aluno_id))
        print(f"  T10 OK: {nome} → {mat}")
        updates += 1
    else:
        nao_encontrados.append(f"T10: {nome}")

# Atualizar matrículas T11
alunos_t11 = conn.execute("SELECT id, nome FROM alunos WHERE turma_id = ?", (t11_id,)).fetchall()
nomes_t11 = {a["nome"]: a["id"] for a in alunos_t11}

for nome, mat in T11_MATRICULAS.items():
    aluno_id = nomes_t11.get(nome)
    if aluno_id:
        conn.execute("UPDATE alunos SET matricula = ? WHERE id = ?", (mat, aluno_id))
        print(f"  T11 OK: {nome} → {mat}")
        updates += 1
    else:
        nao_encontrados.append(f"T11: {nome}")

conn.commit()
conn.close()

print(f"\n✓ {updates} matrículas atualizadas.")
if nao_encontrados:
    print(f"\nNão encontrados no banco ({len(nao_encontrados)}):")
    for n in nao_encontrados:
        print(f"  - {n}")
