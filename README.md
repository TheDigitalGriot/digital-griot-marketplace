# digital-griot-marketplace

TheDigitalGriot's **unified plugin marketplace** — one repo, every Griot tool.

Each tool (Prism, Cinopsis, Fragment, Audion, Valence, Synaptiq, …) keeps its own
code repo. On release, its closing ceremony runs `scripts/sync-to-marketplace.sh`,
which mirrors just that tool's plugin dirs into a thin `‹tool›-plugin/` folder here
and upserts one entry in `.claude-plugin/marketplace.json`.

## Why one marketplace repo

Claude Desktop / Cowork's remote marketplace backend rejects `source: "."` and times
out cloning a multi‑GB tool monorepo. This repo stays small (thin plugin dirs only,
a few MB) and every entry uses a spec‑valid relative `./‹tool›-plugin` source — so the
backend clones it fast and content validation passes. This generalizes the proven
`TheDigitalGriot/prism-plugin` single‑tool mirror to the whole suite.

## Layout

```
digital-griot-marketplace/
├── .claude-plugin/
│   └── marketplace.json        # lists every Griot plugin, source: "./‹tool›-plugin"
├── prism-plugin/               # thin mirror of Prism's plugin dirs (generated)
│   └── .claude-plugin/plugin.json
├── ‹tool›-plugin/              # one per tool, added by each tool's ceremony
├── scripts/
│   └── sync-to-marketplace.sh  # run FROM a tool repo to sync its folder in
└── README.md
```

## Install in Claude Desktop / Cowork

Customize → Plugins → add marketplace **TheDigitalGriot/digital-griot-marketplace**,
then install any listed plugin (`prism`, …).

## Add / update a tool

From the tool's repo root (must have `.claude-plugin/plugin.json` + its plugin dirs):

```sh
sh /path/to/digital-griot-marketplace/scripts/sync-to-marketplace.sh
# or, wired into the tool's closing ceremony / release step
```

The script clones this marketplace, replaces only that tool's `‹tool›-plugin/`
folder, upserts its manifest entry, and commits — **every other tool is preserved**.
Generated folders are build artifacts: never edit `‹tool›-plugin/` here by hand.

## Source of truth

Skills and plugin code live in each **tool's own repo**. This marketplace is a
generated, one‑way mirror. Edit upstream; let the sync push it here.
