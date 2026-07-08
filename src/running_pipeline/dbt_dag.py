"""Render the dbt DAG from target/manifest.json as a Mermaid flowchart
and idempotently embed it in README.md between HTML comment markers.

Reads dbt artifacts only — never touches the dbt project itself — and
uses nothing outside the standard library, so it stays a docs tool with
no runtime footprint. Nodes are grouped into subgraphs by dbt folder
path (fqn), not database schema: core and marts both materialize into
the analytics schema and would collapse into one group under a schema
grouping. Output is fully sorted so regeneration is diff-stable.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

MARKER_START = "<!-- dbt-dag:start -->"
MARKER_END = "<!-- dbt-dag:end -->"
ANCHOR_HEADING = "## Warehouse models (dbt)"

KEPT_TYPES = frozenset({"source", "seed", "model"})

# Subgraph render order: raw inputs first, then the dbt layer folders in
# lineage order. Folders not listed here (none today) sort after these.
GROUP_ORDER = ("sources", "seeds", "staging", "intermediate", "core", "marts")
GROUP_LABELS = {
    "sources": "Sources",
    "seeds": "Seeds",
    "staging": "Staging",
    "intermediate": "Intermediate",
    "core": "Core",
    "marts": "Marts",
}


@dataclass(frozen=True)
class DagNode:
    unique_id: str  # e.g. "model.running_analytics.fct_runs"
    resource_type: str  # "source" | "seed" | "model"
    label: str  # text shown inside the shape
    group: str  # subgraph key


def _sanitize(unique_id: str) -> str:
    """Turn a manifest unique_id into a valid Mermaid node id (no dots)."""
    return unique_id.replace(".", "_")


def _node_from_entry(unique_id: str, entry: dict) -> DagNode | None:
    resource_type = entry.get("resource_type")
    if resource_type not in KEPT_TYPES:
        return None
    fqn = entry["fqn"]
    if resource_type == "source":
        # fqn = [project, "sources", source_name, table]; the source-name
        # prefix disambiguates tables across sources.
        group, label = "sources", f"{fqn[-2]}.{fqn[-1]}"
    elif resource_type == "seed":
        # Seed fqn has no folder segment ([project, name]), so seeds are
        # grouped by resource_type rather than folder path.
        group, label = "seeds", fqn[-1]
    else:
        group = fqn[1] if len(fqn) >= 3 else "models"
        label = fqn[-1]
    return DagNode(unique_id, resource_type, label, group)


def build_graph(manifest: dict) -> tuple[list[DagNode], list[tuple[str, str]]]:
    """Extract DAG nodes and edges from a parsed manifest dict.

    Keeps only sources, seeds, and models — tests and every other
    resource type are dropped, along with any edge touching them.
    Returns nodes sorted by unique_id and edges sorted by (parent, child).
    """
    nodes: dict[str, DagNode] = {}
    for unique_id, entry in {**manifest.get("nodes", {}), **manifest.get("sources", {})}.items():
        node = _node_from_entry(unique_id, entry)
        if node is not None:
            nodes[unique_id] = node

    edges = [
        (parent_id, child_id)
        for child_id in nodes
        for parent_id in manifest.get("parent_map", {}).get(child_id, [])
        if parent_id in nodes
    ]
    return sorted(nodes.values(), key=lambda n: n.unique_id), sorted(edges)


def _node_line(node: DagNode) -> str:
    """One Mermaid node declaration; the bracket shape encodes the type."""
    node_id = _sanitize(node.unique_id)
    if node.resource_type == "source":
        return f'{node_id}[("{node.label}")]'  # cylinder: raw database table
    if node.resource_type == "seed":
        return f'{node_id}(["{node.label}"])'  # stadium: seeded reference data
    return f'{node_id}["{node.label}"]'


def render_mermaid(nodes: list[DagNode], edges: list[tuple[str, str]]) -> str:
    """Render a deterministic `flowchart LR`, ending in exactly one newline.

    Non-empty groups appear in GROUP_ORDER (unknown groups after, sorted),
    each as a subgraph block, followed by every edge.
    """
    groups: dict[str, list[DagNode]] = {}
    for node in nodes:
        groups.setdefault(node.group, []).append(node)
    ordered = [g for g in GROUP_ORDER if g in groups]
    ordered += sorted(g for g in groups if g not in GROUP_ORDER)

    lines = ["flowchart LR"]
    for group in ordered:
        label = GROUP_LABELS.get(group, group)
        lines += ["", f'    subgraph {group}["{label}"]']
        lines += [f"        {_node_line(node)}" for node in groups[group]]
        lines.append("    end")
    lines.append("")
    lines += [f"    {_sanitize(parent)} --> {_sanitize(child)}" for parent, child in edges]
    return "\n".join(lines) + "\n"


def update_readme_text(readme_text: str, mermaid: str) -> str:
    """Return the README text with the Mermaid block embedded.

    Replaces whatever sits between the dbt-dag markers; on first run
    (no markers yet) inserts the block right after the anchor heading.
    Pure text transform — same input always yields byte-identical output.
    """
    block = f"{MARKER_START}\n```mermaid\n{mermaid}```\n{MARKER_END}"
    start = readme_text.find(MARKER_START)
    end = readme_text.find(MARKER_END)

    if start != -1 and end > start:
        return readme_text[:start] + block + readme_text[end + len(MARKER_END) :]
    if start != -1 or end != -1:
        raise ValueError(
            f"README.md has unbalanced dbt-dag markers — restore both `{MARKER_START}` "
            f"and `{MARKER_END}` (in that order) or delete both and re-run `make dbt-dag`"
        )

    lines = readme_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == ANCHOR_HEADING:
            lines.insert(i + 1, f"\n{block}\n")
            return "".join(lines)
    raise ValueError(
        f'README.md has no dbt-dag markers and no "{ANCHOR_HEADING}" heading — add '
        f"`{MARKER_START}` / `{MARKER_END}` where the diagram belongs, "
        "then re-run `make dbt-dag`"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m running_pipeline.dbt_dag",
        description="Render the dbt DAG as Mermaid; optionally embed it in README.md.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("dbt/target/manifest.json"),
        help="path to the dbt manifest (default: dbt/target/manifest.json)",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=Path("README.md"),
        help="README to update (default: README.md)",
    )
    parser.add_argument(
        "--update-readme",
        action="store_true",
        help="embed between dbt-dag markers instead of printing to stdout",
    )
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        raise SystemExit(
            f"dbt manifest not found at {args.manifest} — generate it with `make dbt-dag`"
        )
    mermaid = render_mermaid(*build_graph(json.loads(args.manifest.read_text())))

    if not args.update_readme:
        sys.stdout.write(mermaid)
        return 0

    if not args.readme.is_file():
        raise SystemExit(f"README not found at {args.readme}")
    old = args.readme.read_text()
    try:
        new = update_readme_text(old, mermaid)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if new != old:
        args.readme.write_text(new)
        print(f"{args.readme}: dbt DAG updated")
    else:
        print(f"{args.readme}: dbt DAG already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
