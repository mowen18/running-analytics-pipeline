"""dbt DAG generator tests: manifest → graph extraction and deterministic
Mermaid rendering. Pure unit tests — no dbt subprocess, no database."""

import json
from pathlib import Path

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
