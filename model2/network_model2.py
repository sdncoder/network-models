#!/usr/bin/env python3
"""
Network Model 2 — NetworkX backbone model with geographic rendering.

Source data: Network-Model2.numbers (Link ID, A-End, Z-End, Capacity, Latency)
10 sites / 17 links: US backbone POPs plus AWS East and AWS West on-ramps.

Usage:
    python network_model2.py [data/Network-Model2.numbers | data/links.csv] [--outdir DIR]

Defaults to data/Network-Model2.numbers and writes to output/, both relative
to this file.

Drawing style:
    - black node outlines, no fill
    - gray links, black text
    - links drawn as curves; each curve's bend is chosen to keep clear of
      other sites and of already-drawn links (best geographic fit)
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.patches import FancyArrowPatch

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "data" / "Network-Model2.numbers"
OUTDIR = HERE / "output"

# --------------------------------------------------------------------------
# Site geography (lat, lon). Cloud on-ramps are placed at their AWS region:
#   AWS East -> us-east-1 (N. Virginia), drawn southwest of ASH so both
#               on-ramp links (ASH, ATL) read clearly and avoid NYC-ATL
#   AWS West -> us-west-2 (Oregon)
# --------------------------------------------------------------------------
SITES = {
    "NYC":      (40.71, -74.01, "New York"),
    "ASH":      (39.04, -77.49, "Ashburn"),
    "ATL":      (33.75, -84.39, "Atlanta"),
    "CHI":      (41.88, -87.63, "Chicago"),
    "DFW":      (32.78, -96.80, "Dallas"),
    "DEN":      (39.74, -104.99, "Denver"),
    "LAX":      (34.05, -118.24, "Los Angeles"),
    "SJC":      (37.34, -121.89, "San Jose"),
    "AWS East": (37.10, -81.60, "us-east-1"),
    "AWS West": (45.84, -119.70, "us-west-2"),
}
CLOUD_NODES = {"AWS East", "AWS West"}

# Where each site's name sits relative to its marker (compass direction).
LABEL_SIDE = {
    "NYC": "E", "ASH": "N", "ATL": "SE", "CHI": "N", "DFW": "S",
    "DEN": "N", "LAX": "SW", "SJC": "W", "AWS East": "W", "AWS West": "W",
}
_COMPASS = {
    "N": (0, 1, "center"), "S": (0, -1, "center"), "E": (1, 0, "left"),
    "W": (-1, 0, "right"), "NE": (0.75, 0.75, "left"), "NW": (-0.75, 0.75, "right"),
    "SE": (0.75, -0.75, "left"), "SW": (-0.75, -0.75, "right"),
}


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
def _rows_from_numbers(path: Path) -> list[list]:
    from numbers_parser import Document  # pip install numbers-parser

    table = Document(str(path)).sheets[0].tables[0]
    return [list(r) for r in table.rows(values_only=True)]


def _rows_from_csv(path: Path) -> list[list]:
    with path.open(newline="") as fh:
        return [row for row in csv.reader(fh)]


def load_links(path: Path) -> list[dict]:
    rows = (
        _rows_from_numbers(path)
        if path.suffix.lower() == ".numbers"
        else _rows_from_csv(path)
    )
    # find header row (Numbers sheet has a blank first row)
    header_idx = next(
        i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Link ID"
    )
    links = []
    for r in rows[header_idx + 1 :]:
        if not r or r[0] in (None, ""):
            continue
        links.append(
            {
                "id": str(r[0]).strip(),
                "a": str(r[1]).strip(),
                "z": str(r[2]).strip(),
                "capacity_gbps": float(r[3]),
                "latency_ms": round(float(r[4]), 2),
            }
        )
    return links


def build_graph(links: list[dict]) -> nx.MultiGraph:
    G = nx.MultiGraph(name="Network Model 2")
    # add sites in link-table order so output is identical run to run
    for site in dict.fromkeys(x for l in links for x in (l["a"], l["z"])):
        lat, lon, label = SITES.get(site, (None, None, site))
        if lat is None:
            raise ValueError(f"No coordinates defined for site '{site}' — add it to SITES")
        G.add_node(
            site,
            lat=lat,
            lon=lon,
            label=label,
            kind="cloud" if site in CLOUD_NODES else "pop",
        )
    for l in links:
        G.add_edge(
            l["a"],
            l["z"],
            key=l["id"],
            link_id=l["id"],
            capacity_gbps=l["capacity_gbps"],
            latency_ms=l["latency_ms"],
        )
    return G


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def simple_view(G: nx.MultiGraph) -> nx.Graph:
    """Collapse parallel links: min latency, summed capacity."""
    H = nx.Graph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, d in G.edges(data=True):
        if H.has_edge(u, v):
            H[u][v]["latency_ms"] = min(H[u][v]["latency_ms"], d["latency_ms"])
            H[u][v]["capacity_gbps"] += d["capacity_gbps"]
        else:
            H.add_edge(u, v, latency_ms=d["latency_ms"], capacity_gbps=d["capacity_gbps"])
    return H


def report(G: nx.MultiGraph) -> str:
    H = simple_view(G)
    out = []
    out.append(f"{G.graph['name']}: {G.number_of_nodes()} sites, {G.number_of_edges()} links")
    out.append(
        f"Total capacity: {sum(d['capacity_gbps'] for *_, d in G.edges(data=True)):.0f} Gbps"
        f"   Connected: {nx.is_connected(H)}"
    )

    out.append("\nSite degree / latency-weighted betweenness")
    bc = nx.betweenness_centrality(H, weight="latency_ms")
    for n in sorted(H, key=lambda n: (-bc[n], n)):
        out.append(f"  {n:<9} degree {G.degree(n):>2}   betweenness {bc[n]:.3f}")

    bridges = list(nx.bridges(H))
    cuts = sorted(nx.articulation_points(H))
    out.append(f"\nSingle-link failure points (bridges): {bridges or 'none'}")
    out.append(f"Single-site failure points (articulation): {cuts or 'none'}")
    out.append(f"Min links to disconnect the network (edge connectivity): {nx.edge_connectivity(H)}")

    out.append("\nLowest-latency path from every POP to each AWS region")
    pops = sorted(n for n, k in H.nodes(data="kind") if k == "pop")
    for cloud in sorted(CLOUD_NODES & set(H)):
        out.append(f"  -> {cloud}")
        for src in pops:
            path = nx.shortest_path(H, src, cloud, weight="latency_ms")
            ms = nx.path_weight(H, path, weight="latency_ms")
            out.append(f"     {src:<4} {ms:5.1f} ms  {' > '.join(path)}")

    out.append("\nCloud diversity: link-disjoint paths from each POP to AWS")
    for cloud in sorted(CLOUD_NODES & set(H)):
        worst = min(nx.edge_connectivity(H, p, cloud) for p in pops)
        out.append(f"  {cloud}: every POP has at least {worst} link-disjoint path(s)")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Geographic layout + curved-link routing
# --------------------------------------------------------------------------
def project(lat: float, lon: float, ref_lat: float = 39.0) -> tuple[float, float]:
    """Equirectangular projection scaled by cos(reference latitude)."""
    return lon * math.cos(math.radians(ref_lat)), lat


def _bezier(p0, p2, rad, n=40):
    """Quadratic Bezier matching matplotlib's arc3 connection style."""
    p0, p2 = np.asarray(p0), np.asarray(p2)
    mid = (p0 + p2) / 2
    d = p2 - p0
    ctrl = mid + rad * np.array([d[1], -d[0]])
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * ctrl + t**2 * p2


def site_label_text(G, n):
    return f"{n}\n{G.nodes[n]['label']}" if len(n) > 3 else G.nodes[n]["label"]


def site_label_anchor(G, pos, n):
    """Where a site's name label is drawn: (x, y, ha)."""
    ux, uy, ha = _COMPASS[LABEL_SIDE.get(n, "N")]
    r = 1.25 if G.nodes[n]["kind"] == "cloud" else 1.05
    x, y = pos[n]
    return x + r * ux, y + r * uy, ha


def site_label_points(G, pos):
    """Sample points across each site label's footprint (data units), used as
    obstacles so links and link labels stay off site names."""
    pts = []
    for n in G:
        x, y, ha = site_label_anchor(G, pos, n)
        width = 0.17 * max(len(line) for line in site_label_text(G, n).split("\n"))
        x0 = x if ha == "left" else x - width if ha == "right" else x - width / 2
        pts += [(x0 + f * width, y) for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
    return np.array(pts)


def place_short_label(pos, edge, rad, curve_pts, site_obstacles, text):
    """
    Short links: try label spots along the curve (and beside it) and keep the
    one whose text box has the most clearance from sites, site names and
    every other link. Clearance is measured against the label's box, not
    just its centre.
    """
    u, v, _ = edge
    half_w, half_h = 0.085 * len(text) / 2 + 0.1, 0.24
    p0, p2 = np.asarray(pos[u]), np.asarray(pos[v])
    d = p2 - p0
    normal = np.array([d[1], -d[0]]) / np.linalg.norm(d)
    curve = _bezier(p0, p2, rad, n=21)
    others = np.vstack([c for e, c in curve_pts.items() if e != edge])
    own = curve_pts[edge]

    def clearance(c, obstacles, pad=0.0):
        dx = np.abs(obstacles[:, 0] - c[0]) - half_w
        dy = np.abs(obstacles[:, 1] - c[1]) - half_h
        return float(np.min(np.maximum(dx, dy))) - pad

    best, best_score = None, -math.inf
    for t_idx in (7, 10, 13):                       # t = 0.35, 0.5, 0.65
        base = curve[t_idx]
        for off in (0.0, 0.45, -0.45, 0.7, -0.7, 0.95, -0.95):
            c = base + off * normal
            score = min(
                clearance(c, others),
                clearance(c, site_obstacles, pad=0.55),   # site markers have size
                clearance(c, own) if off else 1.0,        # beside-line labels must clear their own line
            )
            score = min(score, 0.45) - 0.04 * abs(off) - 0.08 * abs(t_idx - 10) / 3
            if score > best_score:
                best, best_score = c, score
    return float(best[0]), float(best[1])


def choose_curvature(G, pos, candidates=np.linspace(-0.4, 0.4, 17)):
    """
    For every link pick the arc3 'rad' that keeps the curve clear of other
    sites and other links, while staying close to the straight geographic
    line. Parallel links between the same pair are fanned out.
    """
    edges = sorted(
        G.edges(keys=True),
        key=lambda e: -np.linalg.norm(np.subtract(pos[e[0]], pos[e[1]])),
    )  # route long-haul links first; short ones fit around them
    span = np.ptp(np.array(list(pos.values())), axis=0).max()
    node_clear = 0.06 * span
    link_clear = 0.025 * span

    labels = site_label_points(G, pos)
    text_clear = 0.025 * span
    drawn: list[np.ndarray] = []
    apexes: list[np.ndarray] = []
    label_clear = 0.07 * span
    chosen: dict = {}
    pair_count: dict = {}

    for u, v, k in edges:
        pair = tuple(sorted((u, v)))
        idx = pair_count.get(pair, 0)
        pair_count[pair] = idx + 1
        others = np.array([pos[n] for n in G if n not in (u, v)])

        best, best_score = 0.0, math.inf
        for rad in candidates:
            pts = _bezier(pos[u], pos[v], rad)
            inner = pts[3:-3]
            # distance to non-endpoint sites
            dn = np.min(np.linalg.norm(inner[:, None, :] - others[None, :, :], axis=2))
            node_pen = max(0.0, node_clear - dn) ** 2 * 400
            # crowding against links already routed
            link_pen = 0.0
            for other in drawn:
                dl = np.min(np.linalg.norm(inner[:, None, :] - other[None, 6:-6, :], axis=2))
                link_pen += max(0.0, link_clear - dl) ** 2 * 120
            # keep this link's label clear of other link labels and sites
            apex = pts[len(pts) // 2]
            for a in apexes:
                link_pen += max(0.0, label_clear - np.linalg.norm(apex - a)) ** 2 * 300
            dapex = np.min(np.linalg.norm(others - apex, axis=1))
            node_pen += max(0.0, node_clear * 1.2 - dapex) ** 2 * 300
            # stay off site-name labels (the line and this link's own label)
            dlab = np.min(np.linalg.norm(inner[:, None, :] - labels[None, :, :], axis=2))
            node_pen += max(0.0, text_clear - dlab) ** 2 * 400
            dlab_apex = np.min(np.linalg.norm(labels - apex, axis=1))
            node_pen += max(0.0, node_clear - dlab_apex) ** 2 * 200
            # prefer gentle, geographically faithful curves (but not dead straight)
            shape_pen = (abs(rad) - 0.12) ** 2 * 2.0
            score = node_pen + link_pen + shape_pen
            if score < best_score:
                best, best_score = rad, score

        if idx:  # fan out parallel links between the same pair
            best += 0.12 * idx * (1 if best >= 0 else -1)
        chosen[(u, v, k)] = float(best)
        drawn.append(_bezier(pos[u], pos[v], best))
        apexes.append(_bezier(pos[u], pos[v], best, n=41)[20])
    return chosen


def draw(G: nx.MultiGraph, outfile: Path, dpi: int = 200,
         paths: list[dict] | None = None, title: str | None = None,
         footer: str | None = None) -> None:
    """
    paths: optional overlays, each {"nodes": [...], "color": "#hex", "name": "A"}.
    Links on a path are drawn solid in that color on top of the gray base map.
    """
    pos = {n: project(d["lat"], d["lon"]) for n, d in G.nodes(data=True)}
    rads = choose_curvature(G, pos)
    site_obstacles = np.vstack([np.array(list(pos.values())), site_label_points(G, pos)])
    curve_pts = {e: _bezier(pos[e[0]], pos[e[1]], r)[4:-4] for e, r in rads.items()}

    fig, ax = plt.subplots(figsize=(15, 8.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    overlay = {}
    for p in paths or []:
        for a, b in zip(p["nodes"], p["nodes"][1:]):
            overlay[frozenset((a, b))] = p

    # links — gray curves (path links in their path color)
    for (u, v, k), rad in rads.items():
        hl = overlay.get(frozenset((u, v)))
        if hl:
            ax.add_patch(
                FancyArrowPatch(
                    pos[u], pos[v], connectionstyle=f"arc3,rad={rad}", arrowstyle="-",
                    color=hl["color"], linewidth=4.2, alpha=0.95,
                    shrinkA=16 if G.nodes[u]["kind"] == "cloud" else 13,
                    shrinkB=16 if G.nodes[v]["kind"] == "cloud" else 13,
                    zorder=2, capstyle="butt",
                )
            )
        d = G.edges[u, v, k]
        ax.add_patch(
            FancyArrowPatch(
                pos[u], pos[v],
                connectionstyle=f"arc3,rad={rad}",
                arrowstyle="-",
                color="#8a8a8a",
                linewidth=1.6 if G.nodes[u]["kind"] == G.nodes[v]["kind"] == "pop" else 1.3,
                linestyle="-" if "cloud" not in (G.nodes[u]["kind"], G.nodes[v]["kind"]) else (0, (4, 2.5)),
                shrinkA=13, shrinkB=13,
                zorder=1,
            )
        )
        # label at curve apex; on short links, set it beside the line
        # so the label never hides the link itself
        mx, my = _bezier(pos[u], pos[v], rad, n=3)[1]
        dx, dy = np.subtract(pos[v], pos[u])
        length = math.hypot(dx, dy)
        if length < 5.0:
            mx, my = place_short_label(pos, (u, v, k), rad, curve_pts, site_obstacles,
                                       f"{d['link_id']}  {d['latency_ms']:g} ms")
        ax.text(
            mx, my, f"{d['link_id']}  {d['latency_ms']:g} ms",
            fontsize=7.2, color="black", ha="center", va="center", zorder=3,
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.9),
        )

    # sites — black outline, no fill (clouds drawn as squares)
    for kind, marker, size in (("pop", "o", 520), ("cloud", "s", 560)):
        nodes = [n for n, k in G.nodes(data="kind") if k == kind]
        ax.scatter(
            [pos[n][0] for n in nodes], [pos[n][1] for n in nodes],
            s=size, marker=marker, facecolors="none", edgecolors="black",
            linewidths=1.8, zorder=4,
        )

    # site labels — black text at each site's assigned side
    for n, (x, y) in pos.items():
        if len(n) <= 3:
            ax.text(x, y, n, fontsize=7.5, fontweight="bold",
                    ha="center", va="center", color="black", zorder=5)
        lx, ly, ha = site_label_anchor(G, pos, n)
        text = site_label_text(G, n)
        ax.text(lx, ly, text, fontsize=8.5, ha=ha, va="center",
                color="black", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))

    total_cap = sum(d["capacity_gbps"] for *_, d in G.edges(data=True))
    ax.set_title(
        title or
        f"Network Model 2 — {G.number_of_nodes()} sites · {G.number_of_edges()} links · "
        f"{total_cap:.0f} Gbps aggregate (100G per link)",
        fontsize=13, color="black", loc="left", pad=14,
    )
    ax.text(
        0.0, -0.04,
        "○ backbone POP    □ AWS region on-ramp    —— backbone link    - - - cloud link    "
        "labels: link ID · one-way latency",
        transform=ax.transAxes, fontsize=8.5, color="black",
    )
    if paths:
        y = -0.125
        for p in paths:
            ax.plot([0.0, 0.035], [y, y], transform=ax.transAxes, color=p["color"],
                    linewidth=4.2, solid_capstyle="round", clip_on=False)
            ax.text(0.045, y, p["label"], transform=ax.transAxes, fontsize=9.5,
                    va="center", color="black")
            y -= 0.045
    if footer:
        ax.text(0.0, -0.08, footer, transform=ax.transAxes, fontsize=8.5, color="black")
    ax.set_aspect("equal")
    ax.margins(0.08)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(outfile, dpi=dpi, bbox_inches="tight")
    fig.savefig(outfile.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE),
                    help="data/Network-Model2.numbers or data/links.csv")
    ap.add_argument("--outdir", default=str(OUTDIR))
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    G = build_graph(load_links(Path(args.source)))
    text = report(G)
    print(text)
    (outdir / "analysis.txt").write_text(text + "\n")
    draw(G, outdir / "network_model2.png")
    print(f"\nWrote {outdir / 'network_model2.png'} (+ .svg)")


if __name__ == "__main__":
    main()
