#!/usr/bin/env python3
"""
network_model.py — NetworkX model of the backbone defined in Network-Model1.numbers

Reads the link table (Link ID, A-End, Z-End, Capacity (Gbps), Latency (ms)),
builds a NetworkX MultiGraph (parallel links such as the two NYC–CHI circuits
are kept as separate edges), runs a set of standard backbone analyses, and
renders a graphics model of the network.

Usage:
    pip install networkx matplotlib numbers-parser
    python network_model.py [data/Network-Model1.numbers | data/links.csv] [--outdir DIR]

Defaults to data/Network-Model1.numbers and writes to output/, both relative
to this script.

Outputs (in --outdir):
    network_topology.png      topology map: latency labels, capacity, roles
    network_resilience.png    single-link-failure impact chart
    network_report.txt        text report of every analysis below
    links.csv                 the link table exported as CSV
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
import networkx as nx

# --------------------------------------------------------------------------
# Site metadata (used only for drawing — the graph itself comes from the file)
# Approximate (lon, lat) so the map reads like a US backbone.
# --------------------------------------------------------------------------
SITE_POS = {
    "SJC": (-121.9, 37.4),
    "LAX": (-118.2, 34.0),
    "DEN": (-104.9, 39.7),
    "DFW": (-97.0, 32.9),
    "CHI": (-87.6, 41.9),
    "ATL": (-84.4, 33.7),
    "NYC": (-74.0, 40.7),
    "AWS": (-101.0, 27.0),   # cloud on-ramp — placed off-grid below the core
}
SITE_ROLE = {"AWS": "cloud"}  # everything else defaults to "pop"

EXPECTED_COLS = ["Link ID", "A-End", "Z-End", "Capacity (Gbps)", "Latency (ms)"]


# --------------------------------------------------------------------------
# 1. Load the link table
# --------------------------------------------------------------------------
def load_links(path: Path) -> list[dict]:
    """Return a list of link dicts from a .numbers or .csv file."""
    if path.suffix.lower() == ".numbers":
        from numbers_parser import Document

        rows = []
        for sheet in Document(str(path)).sheets:
            for table in sheet.tables:
                rows.extend(table.rows(values_only=True))
    else:
        with path.open(newline="") as fh:
            rows = list(csv.reader(fh))

    # Find the header row anywhere in the table (the sheet has a blank row 1)
    header_idx = next(
        i for i, r in enumerate(rows)
        if r and str(r[0]).strip() == "Link ID"
    )
    header = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
    col = {name: header.index(name) for name in EXPECTED_COLS}

    links = []
    for r in rows[header_idx + 1:]:
        if not r or r[col["Link ID"]] in (None, ""):
            continue
        links.append({
            "id": str(r[col["Link ID"]]).strip(),
            "a": str(r[col["A-End"]]).strip(),
            "z": str(r[col["Z-End"]]).strip(),
            "capacity": float(r[col["Capacity (Gbps)"]]),
            "latency": round(float(r[col["Latency (ms)"]]), 3),
        })
    return links


# --------------------------------------------------------------------------
# 2. Build the NetworkX model
# --------------------------------------------------------------------------
def build_graph(links: list[dict]) -> nx.MultiGraph:
    G = nx.MultiGraph(name="Network-Model1")
    for site in {l["a"] for l in links} | {l["z"] for l in links}:
        G.add_node(site, role=SITE_ROLE.get(site, "pop"))
    for l in links:
        G.add_edge(l["a"], l["z"], key=l["id"],
                   capacity=l["capacity"], latency=l["latency"])
    return G


def collapse(G: nx.MultiGraph) -> nx.Graph:
    """Simple Graph for path math: parallel links -> best latency, summed capacity."""
    H = nx.Graph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, k, d in G.edges(keys=True, data=True):
        if H.has_edge(u, v):
            e = H[u][v]
            e["capacity"] += d["capacity"]
            e["links"].append(k)
            if d["latency"] < e["latency"]:
                e["latency"] = d["latency"]
        else:
            H.add_edge(u, v, latency=d["latency"], capacity=d["capacity"], links=[k])
    return H


# --------------------------------------------------------------------------
# 3. Analyses
# --------------------------------------------------------------------------
def all_pairs_latency(H: nx.Graph) -> dict:
    return dict(nx.all_pairs_dijkstra_path_length(H, weight="latency"))


def single_link_failures(G: nx.MultiGraph) -> list[dict]:
    """Remove each link in turn; report partition and worst-case latency impact."""
    base = all_pairs_latency(collapse(G))
    base_worst = max(d for src in base.values() for d in src.values())
    results = []
    for u, v, k in list(G.edges(keys=True)):
        G2 = G.copy()
        G2.remove_edge(u, v, key=k)
        H2 = collapse(G2)
        connected = nx.is_connected(H2)
        worst_delta, worst_pair = 0.0, None
        if connected:
            after = all_pairs_latency(H2)
            for s, t in itertools.combinations(sorted(H2.nodes), 2):
                delta = after[s][t] - base[s][t]
                if delta > worst_delta + 1e-9:
                    worst_delta, worst_pair = delta, (s, t)
            new_worst = max(d for src in after.values() for d in src.values())
        else:
            new_worst = float("inf")
        results.append({
            "link": k, "a": u, "z": v, "connected": connected,
            "worst_delta": worst_delta, "worst_pair": worst_pair,
            "diameter_after": new_worst, "diameter_before": base_worst,
        })
    return sorted(results, key=lambda r: r["link"])


def single_node_failures(G: nx.MultiGraph) -> list[dict]:
    out = []
    for n in sorted(G.nodes):
        H = collapse(G)
        H.remove_node(n)
        comps = list(nx.connected_components(H))
        out.append({"node": n, "components": len(comps),
                    "isolated": [sorted(c) for c in comps] if len(comps) > 1 else []})
    return out


def edge_disjoint_paths(H: nx.Graph) -> dict:
    """Minimum edge connectivity per pair (how many links must fail to cut them)."""
    return {(s, t): nx.edge_connectivity(H, s, t)
            for s, t in itertools.combinations(sorted(H.nodes), 2)}


# --------------------------------------------------------------------------
# 4. Graphics
# --------------------------------------------------------------------------
INK = "#1f2933"
MUTED = "#6b7785"
POP_COLOR = "#2563eb"
CLOUD_COLOR = "#f59e0b"
CRIT_COLOR = "#dc2626"


def draw_topology(G: nx.MultiGraph, H: nx.Graph, out: Path, stats: dict) -> None:
    pos = {n: SITE_POS.get(n) for n in G.nodes}
    missing = [n for n, p in pos.items() if p is None]
    if missing:  # any site we don't have coordinates for gets a spring position
        auto = nx.spring_layout(H, seed=7)
        for n in missing:
            pos[n] = tuple(auto[n] * 10 + (-95, 35))

    fig, ax = plt.subplots(figsize=(15, 9), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f8fafc")

    btw = stats["betweenness"]
    lat_vals = [d["latency"] for _, _, d in G.edges(data=True)]
    lo, hi = min(lat_vals), max(lat_vals)
    cmap = plt.get_cmap("viridis_r")

    # --- edges (curve parallel links so both are visible) -----------------
    for u, v in {tuple(sorted((a, b))) for a, b in G.edges()}:
        bundle = sorted(G[u][v].items())       # [(link_id, attrs), ...]
        n = len(bundle)
        for i, (lid, d) in enumerate(bundle):
            rad = 0.0 if n == 1 else (-0.18 + 0.36 * i / (n - 1))
            norm = (d["latency"] - lo) / (hi - lo) if hi > lo else 0.5
            color = cmap(0.15 + 0.75 * norm)
            width = 1.5 + d["capacity"] / 40
            patch = FancyArrowPatch(
                pos[u], pos[v], arrowstyle="-", connectionstyle=f"arc3,rad={rad}",
                color=color, lw=width, alpha=0.9, zorder=1,
                shrinkA=18, shrinkB=18,
            )
            ax.add_patch(patch)

            # label at curve midpoint
            (x1, y1), (x2, y2) = pos[u], pos[v]
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = x2 - x1, y2 - y1
            mx += rad * dy * 0.5 * (1 if u < v else -1) * -1
            my += rad * -dx * 0.5 * (1 if u < v else -1) * -1
            ax.text(mx, my, f"{lid}\n{d['latency']:.1f} ms",
                    fontsize=7.5, ha="center", va="center", color=INK,
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec=color, lw=0.8, alpha=0.95), zorder=4)

    # --- nodes ------------------------------------------------------------
    articulation = set(stats["articulation_points"])
    for node in G.nodes:
        x, y = pos[node]
        role = G.nodes[node]["role"]
        base = 900 + 4500 * btw[node]
        face = CLOUD_COLOR if role == "cloud" else POP_COLOR
        edge = CRIT_COLOR if node in articulation else "white"
        ax.scatter([x], [y], s=base, c=face, edgecolors=edge,
                   linewidths=3 if node in articulation else 2, zorder=5,
                   marker="h" if role == "cloud" else "o")
        ax.text(x, y, node, ha="center", va="center", fontsize=10,
                fontweight="bold", color="white", zorder=6)
        ax.text(x, y - 1.55, f"deg {G.degree(node)} · {int(G.degree(node)*100)}G",
                ha="center", va="top", fontsize=7.5, color=MUTED, zorder=6)

    # --- legend & title ---------------------------------------------------
    legend = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=POP_COLOR,
               markersize=12, label="PoP (size = betweenness centrality)"),
        Line2D([0], [0], marker="h", color="w", markerfacecolor=CLOUD_COLOR,
               markersize=12, label="Cloud on-ramp"),
        Line2D([0], [0], color=cmap(0.15), lw=3, label=f"Low latency ({lo:.1f} ms)"),
        Line2D([0], [0], color=cmap(0.9), lw=3, label=f"High latency ({hi:.1f} ms)"),
    ]
    if articulation:
        legend.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="white",
                             markeredgecolor=CRIT_COLOR, markeredgewidth=2.5,
                             markersize=12, label="Articulation point (SPOF)"))
    ax.legend(handles=legend, loc="lower left", fontsize=9, frameon=True,
              facecolor="white", edgecolor="#d0d7de")

    s = stats
    ax.set_title(
        f"Network-Model1 — {G.number_of_nodes()} sites · {G.number_of_edges()} links · "
        f"{s['total_capacity']:.0f} Gbps installed · latency diameter "
        f"{s['diameter']:.1f} ms ({' → '.join(s['diameter_path'])})",
        fontsize=12, color=INK, loc="left", pad=12)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 5, max(xs) + 5)
    ax.set_ylim(min(ys) - 4, max(ys) + 3.5)
    ax.set_aspect(1.2)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def draw_resilience(failures: list[dict], out: Path) -> None:
    labels = [f"{f['link']}  {f['a']}–{f['z']}" for f in failures]
    vals = [f["worst_delta"] if f["connected"] else 0 for f in failures]
    colors = [CRIT_COLOR if not f["connected"]
              else ("#f59e0b" if f["worst_delta"] >= 10 else POP_COLOR if f["worst_delta"] > 0
                    else "#94a3b8") for f in failures]

    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    y = range(len(labels))
    ax.barh(list(y), vals, color=colors, height=0.6)
    ax.set_yticks(list(y), labels, fontsize=9)
    ax.invert_yaxis()
    for i, f in enumerate(failures):
        if not f["connected"]:
            txt = "PARTITIONS NETWORK"
        elif f["worst_delta"] > 0:
            s, t = f["worst_pair"]
            txt = f"+{f['worst_delta']:.1f} ms  ({s}↔{t})"
        else:
            txt = "no impact (redundant parallel link)"
        ax.text(vals[i] + 0.3, i, txt, va="center", fontsize=8, color=INK)
    ax.set_xlabel("Worst-case added latency for any site pair after the link fails (ms)")
    ax.set_title("Single-link failure impact", loc="left", fontsize=12, color=INK)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(vals + [1]) * 1.45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# 5. Report
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent
    ap.add_argument("source", nargs="?", default=str(here / "data" / "Network-Model1.numbers"))
    ap.add_argument("--outdir", default=str(here / "output"))
    args = ap.parse_args(argv)

    src, outdir = Path(args.source), Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    links = load_links(src)
    G = build_graph(links)
    H = collapse(G)

    # export link table
    with (outdir / "links.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(EXPECTED_COLS)
        for l in links:
            w.writerow([l["id"], l["a"], l["z"], l["capacity"], l["latency"]])

    apl = all_pairs_latency(H)
    sites = sorted(H.nodes)
    diam_pair = max(itertools.combinations(sites, 2), key=lambda p: apl[p[0]][p[1]])
    diam_path = nx.dijkstra_path(H, *diam_pair, weight="latency")
    stats = {
        "betweenness": nx.betweenness_centrality(H, weight="latency"),
        "articulation_points": sorted(nx.articulation_points(H)),
        "bridges": sorted(tuple(sorted(b)) for b in nx.bridges(H)),
        "total_capacity": sum(d["capacity"] for *_, d in G.edges(data=True)),
        "diameter": apl[diam_pair[0]][diam_pair[1]],
        "diameter_path": diam_path,
    }
    link_fail = single_link_failures(G)
    node_fail = single_node_failures(G)
    edge_conn = edge_disjoint_paths(H)

    # graphics
    draw_topology(G, H, outdir / "network_topology.png", stats)
    draw_resilience(link_fail, outdir / "network_resilience.png")

    # text report
    L = []
    p = L.append
    p("NETWORK-MODEL1 — NetworkX analysis")
    p("=" * 60)
    p(f"Source file           : {src.name}")
    p(f"Sites                 : {G.number_of_nodes()}  ({', '.join(sites)})")
    p(f"Links                 : {G.number_of_edges()}  (site adjacencies: {H.number_of_edges()})")
    par = [(u, v, d['links']) for u, v, d in H.edges(data=True) if len(d['links']) > 1]
    p(f"Parallel links        : " + ("; ".join(f"{u}–{v} {ls}" for u, v, ls in par) or "none"))
    p(f"Installed capacity    : {stats['total_capacity']:.0f} Gbps")
    p(f"Connected             : {nx.is_connected(H)}")
    p(f"Edge connectivity     : {nx.edge_connectivity(H)}  (min links to cut the network)")
    p(f"Node connectivity     : {nx.node_connectivity(H)}  (min sites to cut the network)")
    p(f"Articulation points   : {stats['articulation_points'] or 'none'}")
    p(f"Bridges (SPOF links)  : {stats['bridges'] or 'none'}")
    p(f"Latency diameter      : {stats['diameter']:.1f} ms  {' → '.join(diam_path)}")
    p(f"Avg shortest latency  : {nx.average_shortest_path_length(H, weight='latency'):.2f} ms")
    p("")
    p("Per-site metrics")
    p("-" * 60)
    p(f"{'Site':<5} {'Role':<6} {'Links':>5} {'Gbps':>6} {'Betweenness':>12} {'Closeness':>10}")
    clo = nx.closeness_centrality(H, distance="latency")
    for n in sorted(sites, key=lambda n: -stats["betweenness"][n]):
        p(f"{n:<5} {G.nodes[n]['role']:<6} {G.degree(n):>5} "
          f"{sum(d['capacity'] for *_, d in G.edges(n, data=True)):>6.0f} "
          f"{stats['betweenness'][n]:>12.3f} {clo[n]:>10.4f}")
    p("")
    p("All-pairs lowest-latency matrix (ms)")
    p("-" * 60)
    p("      " + "".join(f"{s:>7}" for s in sites))
    for s in sites:
        p(f"{s:<6}" + "".join(f"{apl[s][t]:>7.1f}" if s != t else f"{'—':>7}" for t in sites))
    p("")
    p("Lowest-latency paths")
    p("-" * 60)
    for s, t in itertools.combinations(sites, 2):
        path = nx.dijkstra_path(H, s, t, weight="latency")
        p(f"{s}→{t:<4} {apl[s][t]:>6.1f} ms  {' → '.join(path)}")
    p("")
    p("Single-link failure analysis")
    p("-" * 60)
    for f in link_fail:
        if not f["connected"]:
            p(f"{f['link']} {f['a']}–{f['z']}: PARTITIONS THE NETWORK")
        elif f["worst_delta"] > 0:
            s, t = f["worst_pair"]
            p(f"{f['link']} {f['a']}–{f['z']}: worst +{f['worst_delta']:.1f} ms ({s}↔{t}); "
              f"diameter {f['diameter_before']:.1f} → {f['diameter_after']:.1f} ms")
        else:
            p(f"{f['link']} {f['a']}–{f['z']}: no latency impact")
    p("")
    p("Single-site failure analysis")
    p("-" * 60)
    for f in node_fail:
        p(f"{f['node']}: " + ("remaining network stays connected" if f["components"] == 1
                              else f"splits into {f['components']} parts {f['isolated']}"))
    p("")
    p("Pairs with only 2 edge-disjoint paths (two link failures can isolate them)")
    p("-" * 60)
    weak = [f"{s}–{t}" for (s, t), c in edge_conn.items() if c <= 2]
    p(", ".join(weak) if weak else "none")

    report = "\n".join(L)
    (outdir / "network_report.txt").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
