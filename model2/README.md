# Model 2 — Dual AWS Regions, Failure Analysis & TE Paths

A NetworkX model of a 10-site, 18-link U.S. backbone with two AWS region on-ramps. It builds on [model1](../model1/) by adding an Ashburn PoP, splitting AWS into East and West regions, sweeping every single and double failure, and computing traffic-engineered diverse A/B paths. L18 NYC–ASH was added after the first analysis to remove NYC's dual-cut exposure; see [L18 impact](#l18-nycash-impact).

![Network topology](output/network_model2.png)

## The network

| Link | A-End | Z-End | Capacity (Gbps) | Latency (ms) |
|------|-------|-------|----------------:|-------------:|
| L01 | NYC | CHI | 100 | 18.2 |
| L02 | CHI | DEN | 100 | 14.5 |
| L03 | DEN | LAX | 100 | 13.8 |
| L04 | NYC | ATL | 100 | 15.6 |
| L05 | ATL | DFW | 100 | 12.4 |
| L06 | DFW | LAX | 100 | 17.1 |
| L07 | CHI | DFW | 100 | 12.9 |
| L08 | CHI | ASH | 100 | 21.0 |
| L09 | DEN | DFW | 100 | 9.8 |
| L10 | CHI | ATL | 100 | 11.2 |
| L11 | LAX | SJC | 100 | 5.4 |
| L12 | DEN | SJC | 100 | 16.9 |
| L13 | ASH | ATL | 100 | 12.0 |
| L14 | ASH | AWS East | 100 | 6.0 |
| L15 | ATL | AWS East | 100 | 10.0 |
| L16 | LAX | AWS West | 100 | 18.0 |
| L17 | SJC | AWS West | 100 | 14.0 |
| L18 | NYC | ASH | 100 | 3.8 * |

**Sites:** NYC, ASH, ATL, CHI, DFW, DEN, LAX, SJC (PoPs), AWS East and AWS West (cloud regions)
**Total installed capacity:** 1,800 Gbps

\* **L18 latency is an estimate.** NYC–ASH is 350 km great-circle. Across the other 13 backbone links in this table, latency runs at a median of 11.0 µs per great-circle km (range 8.6–23.0), which gives 3.8 ms. A pure physical estimate (fiber route 1.5× great-circle at 4.9 µs/km) would be about 2.6 ms; 3.8 ms keeps L18 on the same basis as the rest of the model. Replace it with the measured value when the circuit is designed.

### Changes from model1

| | Model 1 | Model 2 |
|---|---|---|
| Sites | 7 PoPs + one `AWS` node | 8 PoPs (adds **ASH**) + **AWS East** and **AWS West** |
| Links | 14, including two NYC–CHI circuits | 18, no parallel circuits |
| Cloud attach | LAX and ATL to a single AWS node | ASH + ATL to AWS East; LAX + SJC to AWS West |
| East coast | NYC–CHI ×2 | Ashburn PoP with CHI–ASH, ASH–ATL and NYC–ASH |

Splitting AWS into two regions removes model1's issue of AWS carrying west↔east transit traffic.

## Programs

| Program | What it does | Outputs |
|---|---|---|
| `network_model2.py` | Builds the graph, runs path and resilience analysis, renders the topology map | `network_model2.png/.svg`, `analysis.txt` |
| `analyze_model2.py` | Latency matrix, single and double link failures, site failures, cloud reachability | `failure_analysis.txt` |
| `te_paths.py` | Lowest-latency pair of fully diverse A/B paths between any two sites | `te_<src>_<dst>.png/.svg/.txt` |

## How it is modeled

- **`nx.MultiGraph`** holds the physical topology. A collapsed **`nx.Graph`** is used for path math, the same approach as model1.
- **Latency (ms)** is the routing weight for Dijkstra paths and betweenness.
- **Sites are placed at real latitude/longitude.** AWS West sits at us-west-2 (Oregon). AWS East represents us-east-1 and is drawn southwest of Ashburn so both of its links stay visible.
- **Curved links.** For each link the renderer scores a range of arc bends and keeps the one that stays clear of other sites, links and labels while staying close to the straight geographic path.
- **Diverse paths are exact.** `te_paths.py` enumerates every simple path, keeps the pairs that share no links and no transit sites, and picks the pair with the lowest combined latency (the Suurballe objective).

## Analyses

| Analysis | NetworkX functions |
|---|---|
| All-pairs lowest-latency matrix, diameter, best-path load per link | `all_pairs_dijkstra_path_length`, `dijkstra_path` |
| Structural SPOFs and redundancy | `bridges`, `articulation_points`, `edge_connectivity` |
| Single-link and double-link failure | removes every link and every link pair, then checks `connected_components` |
| Single-site and double-site failure | removes every site and site pair |
| Cloud reachability under failure | `dijkstra_path_length`, `has_path` to each AWS region |
| Diverse A/B path selection | `all_simple_paths`, `path_weight` |

## L18 NYC–ASH impact

| Metric | Before (17 links) | After (18 links) |
|---|---|---|
| NYC links | 2 | 3 |
| NYC → AWS East | 25.6 ms via ATL | **9.8 ms** via ASH |
| Mean site-to-site latency | 27.8 ms | 27.0 ms |
| Latency diameter | 63.1 ms | 63.1 ms (unchanged) |
| Double-link cuts that isolate a site | 3 of 136 | **2 of 153** (NYC no longer isolable) |
| Worst cost of losing L04 NYC–ATL | +13.8 ms | +0.2 ms |
| Double-site outages that strand sites | 6 | 6 (unchanged) |
| ATL betweenness | 0.44 | 0.39 |

- **NYC is now as well protected as any PoP.** No pair of link cuts can isolate it, and NYC–ATL has a near-equal backup via ASH (15.8 ms vs 15.6 ms).
- **NYC's AWS East latency falls by 15.8 ms**, because NYC now reaches AWS East through Ashburn instead of Atlanta.
- **It does not fix the ATL + CHI outage.** ASH's only other backbone exits are also CHI and ATL, so losing both still strands NYC, ASH and AWS East together.
- **ASH now matters more.** Losing the ASH site costs NYC the new AWS East path (+15.8 ms back to 25.6 ms).

## Key findings

### Latency
- **Latency diameter is 63.1 ms**, from AWS West to NYC (AWS West › LAX › DFW › ATL › NYC). Average site-to-site latency is 27.0 ms.
- **Every direct link is the fastest route between its own two ends**, so no link is redundant from a routing view.
- **The southern spine carries most traffic.** L05 ATL–DFW is on the best path for 18 of 45 site pairs and L06 DFW–LAX for 14. West↔east traffic prefers ATL › DFW › LAX over CHI–DEN.

### Failures that isolate sites
- **No single point of failure.** No single link or site outage isolates anything. Edge connectivity is 2.
- **The worst single-link cuts** add latency rather than isolating sites: L11 LAX–SJC (+25.3 ms), L18 NYC–ASH (+23.8 ms, between NYC and ASH themselves) and L09 DEN–DFW (+17.6 ms).
- **Only 2 of 153 double-link cuts split the network**, and each isolates an AWS region, the only sites left with two links:

  | Links lost | Site isolated |
  |---|---|
  | L14 + L15 | AWS East |
  | L16 + L17 | AWS West |

- **Six double-site outages strand surviving sites:**

  | Sites lost | Result |
  |---|---|
  | CHI + DFW | Network splits in half: ASH, ATL, AWS East, NYC \| AWS West, DEN, LAX, SJC |
  | ATL + CHI | Strands ASH, AWS East, NYC |
  | DEN + DFW | Strands AWS West, LAX, SJC |
  | DEN + LAX | Strands AWS West, SJC |
  | ASH + ATL | Strands AWS East |
  | LAX + SJC | Strands AWS West |

- **ATL and DFW are the busiest transit sites** (latency-weighted betweenness 0.39 each). Losing ATL adds 17.5 ms between AWS East and DFW.

### TE diverse paths: DEN → AWS East

![TE paths DEN to AWS East](output/te_DEN_AWSEast.png)

| Path | Latency | Route | Links |
|---|---|---|---|
| A (red) | 32.2 ms | DEN › DFW › ATL › AWS East | L09 L05 L15 |
| B (blue) | 41.5 ms | DEN › CHI › ASH › AWS East | L02 L08 L14 |

- **A and B share no links and no transit sites.** Of the 8 node-disjoint pairs, this one has the lowest combined latency (73.7 ms). L18 does not change the A/B choice.
- **A is the IGP shortest path**, so protecting the route costs no latency on the primary.
- **No single link or site failure takes down both paths.**
- **A/B skew is 9.3 ms.** That is the latency step on failover from A to B, and the buffer needed for 1+1 hitless protection.
- **B now has a close backup.** With L18, B can also run DEN › CHI › NYC › ASH › AWS East at 42.5 ms, only 1.0 ms slower. If L08 CHI–ASH fails, B can be re-signaled over NYC and stay diverse from A.
- **B must still enter AWS East through ASH**, since A uses ATL, so every diverse B path depends on the ASH site and L14.

### Recommendations
- **NYC's third link is done** (L18). It removed NYC's dual-cut exposure.
- **Next, add ASH–DEN or NYC–DEN.** A what-if run shows either one removes both the ATL + CHI and CHI + DFW outages, cutting damaging double-site outages from 6 to 4. ASH–DFW or NYC–DFW only removes ATL + CHI. Today the whole east cluster (NYC, ASH, AWS East) exits the region only through CHI and ATL.
- **Check physical diversity of each AWS on-ramp pair.** If L14/L15 or L16/L17 share conduit, one fiber cut could isolate a region. The link table has no SRLG data, so this needs checking against circuit records.

Full output: [`output/analysis.txt`](output/analysis.txt), [`output/failure_analysis.txt`](output/failure_analysis.txt), [`output/te_DEN_AWSEast.txt`](output/te_DEN_AWSEast.txt).

## Run

From the repo root:

```bash
python model2/network_model2.py      # topology map + analysis.txt
python model2/analyze_model2.py      # latency and failure sweep
python model2/te_paths.py            # DEN -> AWS East A/B paths
python model2/te_paths.py NYC "AWS West"              # any site pair
python model2/te_paths.py DEN "AWS East" --link-disjoint
```

All three read `data/Network-Model2.numbers` by default. Pass `data/links.csv` to `network_model2.py` or `analyze_model2.py`, or `--source data/links.csv` to `te_paths.py`, to use the CSV instead.

## Drawing conventions

- Black-outline, unfilled nodes (○ PoP, □ AWS region), gray links, black text.
- Dashed lines are cloud on-ramp links. Labels show link ID and one-way latency.
- TE paths overlay the map in red (A) and blue (B).
- New sites need an entry in `SITES` (lat, lon, label) and `LABEL_SIDE` in `network_model2.py`.
