#!/usr/bin/env python3
"""
Model 2 — traffic-engineered A/B paths.

Finds the lowest-latency pair of fully diverse paths between two sites:
  * node-disjoint (no shared transit site and therefore no shared link)
  * pair chosen to minimise total latency (Suurballe objective), ties broken
    by the lower A-path latency; A = the faster of the two, B = the other
  * every candidate pair is enumerated, so the result is exact and the
    runners-up are reported for comparison

Usage:
    python te_paths.py                    # DEN -> AWS East (default)
    python te_paths.py NYC "AWS West"     # any pair
    python te_paths.py DEN "AWS East" --link-disjoint   # allow shared transit sites

Writes output/te_<src>_<dst>.png/.svg and output/te_<src>_<dst>.txt.
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import networkx as nx

from network_model2 import DEFAULT_SOURCE, OUTDIR, build_graph, draw, load_links, simple_view

HERE = Path(__file__).resolve().parent
W = "latency_ms"
RED, BLUE = "#d62728", "#1f5fbf"


def path_latency(H, p):
    return nx.path_weight(H, p, weight=W)


def links_of(p):
    return {frozenset(e) for e in zip(p, p[1:])}


def diverse(p, q, node_disjoint=True):
    if links_of(p) & links_of(q):
        return False
    return not (set(p[1:-1]) & set(q[1:-1])) if node_disjoint else True


def ranked_pairs(H, src, dst, node_disjoint=True):
    paths = [(path_latency(H, p), p) for p in nx.all_simple_paths(H, src, dst)]
    pairs = []
    for (la, a), (lb, b) in itertools.combinations(paths, 2):
        if diverse(a, b, node_disjoint):
            if lb < la:
                (la, a), (lb, b) = (lb, b), (la, a)
            pairs.append((la + lb, la, lb, a, b))
    pairs.sort(key=lambda x: (x[0], x[1]))
    return pairs, len(paths)


def survivability(H, A, B, lid):
    """Single-failure check: which path(s) survive each link / site outage."""
    rows = []
    a_links, b_links = links_of(A), links_of(B)
    for u, v in H.edges():
        e = frozenset((u, v))
        rows.append((f"link {lid[e]} {u}-{v}", e not in a_links, e not in b_links))
    for n in H:
        if n in (A[0], A[-1]):
            continue
        rows.append((f"site {n}", n not in A, n not in B))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?", default="DEN")
    ap.add_argument("dst", nargs="?", default="AWS East")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--link-disjoint", action="store_true",
                    help="require only link diversity (transit sites may be shared)")
    args = ap.parse_args()

    G = build_graph(load_links(Path(args.source)))
    H = simple_view(G)
    lid = {frozenset((u, v)): d["link_id"] for u, v, d in G.edges(data=True)}
    node_disjoint = not args.link_disjoint
    mode = "node-disjoint" if node_disjoint else "link-disjoint"

    pairs, n_paths = ranked_pairs(H, args.src, args.dst, node_disjoint)
    if not pairs:
        raise SystemExit(f"No {mode} path pair exists between {args.src} and {args.dst}")
    total, la, lb, A, B = pairs[0]
    shortest = nx.dijkstra_path(H, args.src, args.dst, weight=W)
    s_lat = path_latency(H, shortest)

    def fmt(p):
        hops = " > ".join(p)
        ids = " ".join(lid[frozenset(e)] for e in zip(p, p[1:]))
        return f"{hops}   [{ids}]"

    out = []
    o = out.append
    o(f"TE A/B PATHS  {args.src} -> {args.dst}   ({mode}, min total latency)")
    o("=" * 72)
    o(f"A (RED)  {la:5.1f} ms  {len(A)-1} hops  {fmt(A)}")
    o(f"B (BLUE) {lb:5.1f} ms  {len(B)-1} hops  {fmt(B)}")
    o(f"\nA/B latency skew: {lb - la:.1f} ms     pair total: {total:.1f} ms")
    o(f"IGP shortest path: {s_lat:.1f} ms  {' > '.join(shortest)}"
      f"  ({'= A' if shortest == A else 'differs from A'})")
    o(f"Shared transit sites: {sorted(set(A[1:-1]) & set(B[1:-1])) or 'none'}"
      f"     shared links: {sorted(lid[e] for e in links_of(A) & links_of(B)) or 'none'}")
    o(f"Bottleneck capacity: A {min(H[u][v]['capacity_gbps'] for u, v in zip(A, A[1:])):.0f}G, "
      f"B {min(H[u][v]['capacity_gbps'] for u, v in zip(B, B[1:])):.0f}G")

    o(f"\nCandidates: {n_paths} simple paths, {len(pairs)} {mode} pairs. Next best pairs:")
    for t, a_l, b_l, a, b in pairs[1:6]:
        o(f"  {t:5.1f} ms  A {a_l:4.1f} {' > '.join(a)}")
        o(f"            B {b_l:4.1f} {' > '.join(b)}")

    rows = survivability(H, A, B, lid)
    both_down = [r for r in rows if not r[1] and not r[2]]
    o("\nSingle-failure survivability")
    o(f"  failures that take down BOTH paths: {len(both_down)}"
      + ("" if not both_down else " -> " + ", ".join(r[0] for r in both_down)))
    for name, a_ok, b_ok in rows:
        if not (a_ok and b_ok):
            o(f"  {name:<26} A {'up' if a_ok else 'DOWN':<4}  B {'up' if b_ok else 'DOWN'}")
    o("  (all other single failures leave both A and B up)")

    text = "\n".join(out)
    print(text)
    slug = f"te_{args.src}_{args.dst}".replace(" ", "")
    OUTDIR.mkdir(exist_ok=True)
    (OUTDIR / f"{slug}.txt").write_text(text + "\n")

    draw(
        G, OUTDIR / f"{slug}.png",
        paths=[
            {"nodes": A, "color": RED, "label": f"Path A (primary)  {la:.1f} ms   {' › '.join(A)}"},
            {"nodes": B, "color": BLUE, "label": f"Path B (diverse)  {lb:.1f} ms   {' › '.join(B)}"},
        ],
        title=f"Network Model 2 — TE diverse paths {args.src} → {args.dst}",
        footer=f"A and B are {mode}: no shared links"
               + (" or transit sites" if node_disjoint else "")
               + f"; lowest combined latency of {len(pairs)} diverse pairs ({total:.1f} ms). "
                 f"A/B skew {lb - la:.1f} ms.",
    )
    print(f"\nWrote {slug}.png / .svg / .txt")


if __name__ == "__main__":
    main()
