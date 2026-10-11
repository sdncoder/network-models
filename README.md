# network-models

Network topology models and analysis built in Python with [NetworkX](https://networkx.org/). Each model lives in its own folder with its source data, program, outputs and README. Later models build on earlier ones with more advanced analysis.

## Models

| Model | Focus | Highlights |
|---|---|---|
| [model1](model1/) | Backbone topology & resilience | 8 sites, 14 links. Latency-weighted shortest paths, centrality, SPOF detection, single-link and single-site failure analysis, topology map |
| [model2](model2/) | Dual AWS regions, failure analysis & TE paths | 10 sites, 17 links. Adds Ashburn and separate AWS East/West on-ramps. Full single and double link/site failure sweep, curved geographic map, lowest-latency node-disjoint A/B paths (red/blue) between any two sites |

## Roadmap

Ideas for upcoming models:

- Traffic matrix and link utilization, including utilization after failures
- Shared-risk link groups (SRLG) on top of model2's dual-failure analysis
- IGP metric and ECMP modeling
- RSVP-TE / SR-TE what-if paths with bandwidth constraints (model2 covers latency-optimal diverse A/B paths)
- Capacity planning: which links to upgrade first

## Getting started

```bash
git clone https://github.com/sdncoder/network-models.git
cd network-models
pip install -r requirements.txt
python model1/network_model.py
python model2/network_model2.py
python model2/te_paths.py
```

Requires Python 3.10 or newer.

## Repo layout

```
network-models/
├── README.md
├── requirements.txt
└── modelN/
    ├── README.md
    ├── <program>.py
    ├── data/      # input link tables
    └── output/    # generated graphics and reports
```

## License

MIT. See [LICENSE](LICENSE).
