"""Nova Requisicao must expose every Matrix activity, numbered group or not.

The Grupo control indexes activities by the leading number of ``N - Descricao``.
Extension activities carry ``grupo='NA'``, which never matched that shape, so
``buildGruposPorTipo`` dropped them and the Atividade select stayed empty: the
server offered five AEU activities and the page let the student reach none.
These tests execute the JavaScript the template actually ships.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

TEMPLATE = pathlib.Path("templates/aluno_nova_requisicao.html")


def _population_source() -> str:
    """The real grupoKey + buildGruposPorTipo source, straight from the template."""
    html = TEMPLATE.read_text(encoding="utf-8")
    start = html.index("function grupoKey(")
    end = html.index("const gruposPorTipo = buildGruposPorTipo();")
    return html[start:end]


def _run_population(options):
    """Execute the shipped functions over stubbed <option> elements."""
    harness = (
        _population_source()
        + """
const allOptions = %s.map(o => ({ getAttribute: (k) => o[k] ?? null }));
const map = buildGruposPorTipo();
const filtered = {};
for (const [tipo, grupos] of Object.entries(map)) {
  filtered[tipo] = {};
  for (const [chave, desc] of Object.entries(grupos)) {
    filtered[tipo][chave] = allOptions.filter(
      (o) => (o.getAttribute('data-tipo') || '') === tipo
        && grupoKey(o.getAttribute('data-grupo') || '') === chave
    ).length;
  }
}
console.log(JSON.stringify({ map, filtered }));
""" % json.dumps(options)
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr}"
    return json.loads(proc.stdout)


AAC = "Acadêmica Complementar"
AEU = "Extensão Universitária"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute the template JS"
)


@requires_node
def test_unnumbered_group_keeps_its_activities_reachable():
    """The regression: grupo='NA' must produce a usable group, not be discarded."""
    result = _run_population([
        {"data-tipo": AEU, "data-grupo": "NA"},
        {"data-tipo": AEU, "data-grupo": "NA"},
    ])

    assert "NA" in result["map"][AEU]
    assert result["filtered"][AEU]["NA"] == 2


@requires_node
def test_numbered_groups_still_index_by_their_number():
    """The established AAC behaviour is unchanged."""
    result = _run_population([
        {"data-tipo": AAC, "data-grupo": "1 - Atividades fora da Faculdade"},
        {"data-tipo": AAC, "data-grupo": "1 - Atividades fora da Faculdade"},
        {"data-tipo": AAC, "data-grupo": "5 - Atividades especiais"},
    ])

    assert result["map"][AAC] == {
        "1": "Atividades fora da Faculdade",
        "5": "Atividades especiais",
    }
    assert result["filtered"][AAC] == {"1": 2, "5": 1}


@requires_node
def test_every_offered_activity_is_reachable_through_some_group():
    """No option may be silently unreachable, whatever its group string is."""
    options = [
        {"data-tipo": AAC, "data-grupo": "1 - Atividades fora da Faculdade"},
        {"data-tipo": AAC, "data-grupo": "5 - Atividades especiais"},
        {"data-tipo": AEU, "data-grupo": "NA"},
        # A group that is neither numbered nor 'NA' must not vanish either.
        {"data-tipo": AEU, "data-grupo": "Extensão - Comunidade"},
    ]
    result = _run_population(options)

    reachable = sum(
        count
        for grupos in result["filtered"].values()
        for count in grupos.values()
    )
    assert reachable == len(options)


@requires_node
def test_group_key_is_the_same_projection_used_by_the_filter():
    """A group containing ' - ' but no number must still match itself."""
    result = _run_population([
        {"data-tipo": AEU, "data-grupo": "Extensão - Comunidade"},
    ])

    assert result["map"][AEU] == {"Extensão - Comunidade": "Extensão - Comunidade"}
    assert result["filtered"][AEU]["Extensão - Comunidade"] == 1


def test_population_never_gates_group_registration_on_the_numeric_shape():
    """Source contract, so the guarantee survives without a JS runtime."""
    source = _population_source()

    assert "function grupoKey(" in source, "the shared group projection must exist"
    # The discarded-group defect was a registration guarded by the regex match.
    assert not re.search(
        r"if\s*\(m\)\s*\{[^}]*map\[t\]\[n\]\s*=", source, re.S
    ), "group registration must not depend on matching 'N - Descrição'"
    assert "const n = m ? m[1] : g;" in source
    assert "const d = m ? m[2] : g;" in source


def test_activity_filter_reuses_the_shared_group_projection():
    """A raw split(' - ') in the filter would desynchronise it from the map."""
    html = TEMPLATE.read_text(encoding="utf-8")
    filter_block = html[html.index("function applyAtividadesFilter()"):]
    filter_block = filter_block[: filter_block.index("function applySuggestedHours()")]

    assert "grupoKey(g)" in filter_block
    assert "g.split(' - ')[0]" not in filter_block
