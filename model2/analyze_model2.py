#!/usr/bin/env python3
"""
Model 2 — latency and failure analysis.

  1. Latency: all-pairs lowest-latency matrix, diameter, hop counts.
  2. Single-link failures: does anything isolate? worst latency stretch per cut.
  3. Double-link failures: every pair of links; which cuts isolate which sites.
  4. Site failures: single and double site outages that strand surviving sites.

Usage: python analyze_model2.py [data/Network-Model2.numbers | data/links.csv]
Writes output/failure_analysis.txt.
"""

from __future__ import annotations

import itertools
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from network_model2 import CLOUD_NODES, DEFAULT_SOURCE, OUTDIR, build_graph, load_links, simple_view

HERE = Path(__file__).resolve().parent
W = "latency_ms"


def lat_matrix(H):
    return dict(nx.all_pairs_dijkstra_path_length(H, weight=W))


def components_after(H, links=(), sites=()):
    K = H.copy()
    K.remove_edges_from(links)
    K.remove_nodes_from(sites)
    return [set(c) for c in nx.connected_components(K)], K


def stranded(comps):
    """Sites cut off from the largest surviving piece."""
    main = max(comps, key=len)
    return sorted(n for c in comps if c is not main for n in c)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    G = build_graph(load_links(src))
    H = simple_view(G)
    link_id = {frozenset((u, v)): d["link_id"] for u, v, d in G.edges(data=True)}
    lid = lambda e: link_id[frozenset(e)]
    nodes = sorted(H)
    out = []
    p = out.append

    # ---------------------------------------------------------------- latency
    L = lat_matrix(H)
    p("=" * 72)
    p("1. LATENCY — lowest one-way latency between every pair of sites (ms)")
    p("=" * 72)
    w = 9
    p(" " * w + "".join(f"{n[:8]:>{w}}" for n in nodes))
    for a in nodes:
        p(f"{a[:8]:<{w}}" + "".join(f"{L[a][b]:>{w}.1f}" if a != b else f"{'-':>{w}}" for b in nodes))

    pairs = [(a, b) for a, b in itertools.combinations(nodes, 2)]
    worst = sorted(pairs, key=lambda e: -L[e[0]][e[1]])[:5]
    p(f"\nNetwork diameter (worst best-case latency): {L[worst[0][0]][worst[0][1]]:.1f} ms")
    p("Five longest site-to-site paths:")
    for a, b in worst:
        path = nx.dijkstra_path(H, a, b, weight=W)
        p(f"  {a:>8} > {b:<8} {L[a][b]:5.1f} ms  {len(path)-1} hops  {' > '.join(path)}")
    avg = sum(L[a][b] for a, b in pairs) / len(pairs)
    p(f"Mean site-to-site latency: {avg:.1f} ms")

    # direct link vs best path: links that are never the best route
    p("\nLinks not on their own endpoints' lowest-latency path (detour is faster):")
    any_ = False
    for u, v, d in H.edges(data=True):
        if L[u][v] < d[W] - 1e-9:
            any_ = True
            p(f"  {lid((u, v))} {u}-{v} direct {d[W]} ms vs {L[u][v]:.1f} ms via "
              f"{' > '.join(nx.dijkstra_path(H, u, v, weight=W))}")
    if not any_:
        p("  none")

    # link utilisation by shortest paths (how many best paths ride each link)
    use = Counter()
    for a, b in pairs:
        path = nx.dijkstra_path(H, a, b, weight=W)
        for e in zip(path, path[1:]):
            use[lid(e)] += 1
    p("\nBest-path load per link (site pairs routed over it, of %d):" % len(pairs))
    for l, c in use.most_common():
        p(f"  {l}: {c}")
    idle = sorted(set(link_id.values()) - set(use))
    p(f"  carrying no best paths: {', '.join(idle) or 'none'}")

    # ------------------------------------------------------- single link cuts
    p("\n" + "=" * 72)
    p("2. SINGLE-LINK FAILURES")
    p("=" * 72)
    rows = []
    for u, v in H.edges():
        comps, K = components_after(H, links=[(u, v)])
        if len(comps) > 1:
            rows.append((lid((u, v)), None, None, stranded(comps)))
            continue
        L2 = lat_matrix(K)
        deltas = [(L2[a][b] - L[a][b], a, b) for a, b in pairs]
        d, a, b = max(deltas)
        rows.append((lid((u, v)), d, (a, b, L[a][b], L2[a][b]), []))
    iso = [r for r in rows if r[3]]
    p(f"Cuts that isolate a site: {len(iso)} of {len(rows)}"
      + ("" if not iso else " -> " + "; ".join(f"{r[0]}: {r[3]}" for r in iso)))
    p("\nWorst latency increase each single cut causes (sorted):")
    for l, d, info, _ in sorted((r for r in rows if r[1] is not None), key=lambda r: -r[1]):
        a, b, before, after = info
        p(f"  {l:<4} +{d:5.1f} ms   worst pair {a} > {b}: {before:.1f} -> {after:.1f} ms")

    # ------------------------------------------------------- double link cuts
    p("\n" + "=" * 72)
    p("3. DOUBLE-LINK FAILURES (every pair of links)")
    p("=" * 72)
    edges = list(H.edges())
    total = 0
    by_site = defaultdict(list)
    partitions = []
    for e1, e2 in itertools.combinations(edges, 2):
        total += 1
        comps, _ = components_after(H, links=[e1, e2])
        if len(comps) > 1:
            s = stranded(comps)
            tag = f"{lid(e1)}+{lid(e2)}"
            partitions.append((tag, s))
            for n in s:
                by_site[n].append(tag)
    p(f"{len(partitions)} of {total} double-link cuts split the network "
      f"({100*len(partitions)/total:.1f}%)\n")
    for tag, s in partitions:
        p(f"  {tag:<9} isolates {', '.join(s)}")
    p("\nExposure by site (double cuts that strand it):")
    for n in nodes:
        p(f"  {n:<9} {len(by_site[n]):>2}  {' '.join(by_site[n])}")

    # ------------------------------------------------------------ site failures
    p("\n" + "=" * 72)
    p("4. SITE FAILURES (power / facility loss)")
    p("=" * 72)
    p("Single-site loss:")
    for n in nodes:
        comps, K = components_after(H, sites=[n])
        if len(comps) > 1:
            p(f"  {n:<9} strands {stranded(comps)}")
        else:
            L2 = lat_matrix(K)
            rest = [x for x in nodes if x != n]
            d, a, b = max((L2[a][b] - L[a][b], a, b) for a, b in itertools.combinations(rest, 2))
            p(f"  {n:<9} no isolation; worst stretch +{d:.1f} ms ({a} > {b})")
    p("\nDouble-site loss that strands a surviving site:")
    hit = False
    for a, b in itertools.combinations(nodes, 2):
        comps, _ = components_after(H, sites=[a, b])
        if len(comps) > 1:
            hit = True
            p(f"  {a} + {b:<9} strands {stranded(comps)}")
    if not hit:
        p("  none")

    # ------------------------------------------------------------ cloud reach
    p("\n" + "=" * 72)
    p("5. CLOUD REACHABILITY UNDER FAILURE")
    p("=" * 72)
    pops = [n for n in nodes if n not in CLOUD_NODES]
    for cloud in sorted(CLOUD_NODES):
        p(f"{cloud}: on-ramps {sorted(H[cloud])}")
        for u, v in edges:
            comps, K = components_after(H, links=[(u, v)])
            worst_d = max(
                (nx.dijkstra_path_length(K, s, cloud, weight=W) - L[s][cloud], s) for s in pops
            )
            if worst_d[0] > 0.05:
                p(f"   lose {lid((u, v)):<4} -> worst POP {worst_d[1]} +{worst_d[0]:.1f} ms")
        reach = sum(
            1 for e1, e2 in itertools.combinations(edges, 2)
            if any(not nx.has_path(components_after(H, links=[e1, e2])[1], s, cloud) for s in pops)
        )
        p(f"   double-link cuts that strand a POP from {cloud}: {reach}")

    text = "\n".join(out)
    print(text)
    OUTDIR.mkdir(exist_ok=True)
    (OUTDIR / "failure_analysis.txt").write_text(text + "\n")


if __name__ == "__main__":
    main()
