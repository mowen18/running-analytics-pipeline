"""Render the dbt DAG from target/manifest.json as a Mermaid flowchart
and idempotently embed it in README.md between HTML comment markers.

Reads dbt artifacts only — never touches the dbt project itself — and
uses nothing outside the standard library, so it stays a docs tool with
no runtime footprint. Nodes are grouped into subgraphs by dbt folder
path (fqn), not database schema: core and marts both materialize into
the analytics schema and would collapse into one group under a schema
grouping. Output is fully sorted so regeneration is diff-stable.
"""

from dataclasses import dataclass

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
