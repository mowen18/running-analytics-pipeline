"""dbt DAG generator tests: manifest → graph extraction, deterministic
Mermaid rendering, and idempotent README embedding. Pure unit tests —
no dbt subprocess, no database."""

import json
import shutil
from pathlib import Path

import pytest

from running_pipeline import dbt_dag

FIXTURES = Path(__file__).resolve().parent / "fixtures"

EXPECTED_MERMAID = """\
flowchart LR

    subgraph sources["Sources"]
        source_demo_raw_a_orders[("raw_a.orders")]
        source_demo_raw_b_hourly[("raw_b.hourly")]
    end

    subgraph seeds["Seeds"]
        seed_demo_bands(["bands"])
    end

    subgraph staging["Staging"]
        model_demo_stg_orders["stg_orders"]
    end

    subgraph intermediate["Intermediate"]
        model_demo_int_orders["int_orders"]
    end

    subgraph marts["Marts"]
        model_demo_mart_orders["mart_orders"]
    end

    model_demo_int_orders --> model_demo_mart_orders
    model_demo_stg_orders --> model_demo_int_orders
    seed_demo_bands --> model_demo_int_orders
    source_demo_raw_a_orders --> model_demo_stg_orders
    source_demo_raw_b_hourly --> model_demo_mart_orders
"""


SAMPLE_README = """\
# Demo project

Intro prose above the anchor.

## Warehouse models (dbt)

The dbt project lives in `dbt/` and is driven through make.

## Next section

Prose after the anchor section.
"""


def load_manifest() -> dict:
    return json.loads((FIXTURES / "dbt_manifest.json").read_text())


def test_build_graph_keeps_only_dag_nodes():
    nodes, _ = dbt_dag.build_graph(load_manifest())

    assert [n.unique_id for n in nodes] == [
        "model.demo.int_orders",
        "model.demo.mart_orders",
        "model.demo.stg_orders",
        "seed.demo.bands",
        "source.demo.raw_a.orders",
        "source.demo.raw_b.hourly",
    ]
    by_id = {n.unique_id: n for n in nodes}
    assert by_id["source.demo.raw_a.orders"].group == "sources"
    assert by_id["source.demo.raw_a.orders"].label == "raw_a.orders"
    assert by_id["seed.demo.bands"].group == "seeds"
    assert by_id["seed.demo.bands"].label == "bands"
    assert by_id["model.demo.stg_orders"].group == "staging"
    assert by_id["model.demo.int_orders"].group == "intermediate"
    assert by_id["model.demo.mart_orders"].group == "marts"


def test_build_graph_edges_from_parent_map():
    _, edges = dbt_dag.build_graph(load_manifest())

    assert edges == [
        ("model.demo.int_orders", "model.demo.mart_orders"),
        ("model.demo.stg_orders", "model.demo.int_orders"),
        ("seed.demo.bands", "model.demo.int_orders"),
        ("source.demo.raw_a.orders", "model.demo.stg_orders"),
        ("source.demo.raw_b.hourly", "model.demo.mart_orders"),
    ]
    assert not any("test.demo" in end for edge in edges for end in edge)


def test_render_mermaid_golden():
    assert dbt_dag.render_mermaid(*dbt_dag.build_graph(load_manifest())) == EXPECTED_MERMAID


def test_render_mermaid_omits_empty_groups():
    mermaid = dbt_dag.render_mermaid(*dbt_dag.build_graph(load_manifest()))

    assert "subgraph core" not in mermaid  # fixture has no core model
    subgraphs = [line.split("[")[0].strip() for line in mermaid.splitlines() if "subgraph" in line]
    assert subgraphs == [
        "subgraph sources",
        "subgraph seeds",
        "subgraph staging",
        "subgraph intermediate",
        "subgraph marts",
    ]


def test_update_readme_inserts_after_heading():
    result = dbt_dag.update_readme_text(SAMPLE_README, EXPECTED_MERMAID)

    expected_block = (
        f"## Warehouse models (dbt)\n\n{dbt_dag.MARKER_START}\n"
        f"```mermaid\n{EXPECTED_MERMAID}```\n{dbt_dag.MARKER_END}\n\n"
        "The dbt project lives in `dbt/` and is driven through make.\n"
    )
    assert expected_block in result
    for line in SAMPLE_README.splitlines():
        assert line in result  # every original line survives the insert
    assert result.endswith("Prose after the anchor section.\n")
    assert not result.endswith("\n\n")


def test_update_readme_replace_is_byte_idempotent():
    first = dbt_dag.update_readme_text(SAMPLE_README, EXPECTED_MERMAID)

    assert dbt_dag.update_readme_text(first, EXPECTED_MERMAID) == first

    changed = dbt_dag.update_readme_text(first, "flowchart LR\n")
    assert "```mermaid\nflowchart LR\n```" in changed
    prefix = first[: first.find(dbt_dag.MARKER_START)]
    suffix = first[first.find(dbt_dag.MARKER_END) + len(dbt_dag.MARKER_END) :]
    assert changed.startswith(prefix)  # text outside the markers is untouched
    assert changed.endswith(suffix)


def test_update_readme_missing_heading_errors():
    with pytest.raises(ValueError, match="Warehouse models"):
        dbt_dag.update_readme_text("# Some other README\n\nNo anchor here.\n", "flowchart LR\n")


def test_update_readme_unbalanced_markers_errors():
    broken = SAMPLE_README + f"\n{dbt_dag.MARKER_START}\n"
    with pytest.raises(ValueError, match="unbalanced"):
        dbt_dag.update_readme_text(broken, "flowchart LR\n")


def test_main_updates_readme_idempotently(tmp_path):
    manifest = tmp_path / "manifest.json"
    shutil.copy(FIXTURES / "dbt_manifest.json", manifest)
    readme = tmp_path / "README.md"
    readme.write_text(SAMPLE_README)
    argv = ["--manifest", str(manifest), "--readme", str(readme), "--update-readme"]

    assert dbt_dag.main(argv) == 0
    first = readme.read_bytes()
    assert dbt_dag.MARKER_START.encode() in first

    assert dbt_dag.main(argv) == 0
    assert readme.read_bytes() == first


def test_main_prints_mermaid_without_flag(tmp_path, capsys):
    readme = tmp_path / "README.md"
    readme.write_text(SAMPLE_README)

    exit_code = dbt_dag.main(
        ["--manifest", str(FIXTURES / "dbt_manifest.json"), "--readme", str(readme)]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == EXPECTED_MERMAID
    assert readme.read_text() == SAMPLE_README  # README untouched without the flag


def test_main_missing_manifest_errors(tmp_path):
    missing = tmp_path / "nope" / "manifest.json"
    with pytest.raises(SystemExit, match=r"dbt manifest not found at .* `make dbt-dag`"):
        dbt_dag.main(["--manifest", str(missing)])
