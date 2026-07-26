DEFAULT_CURSO_TOTAL_HORAS_AAC = 160
DEFAULT_CURSO_TOTAL_HORAS_AEU = 80


def gerar_codigo_turma(curso_codigo: str, numero: int) -> str:
    return f"{curso_codigo}-T{int(numero):02d}"
