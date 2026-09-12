# Cinopsis channel bus — bridge notes

Cinopsis exposes its verbs on the shared Griot MCP **channel** primitive as a *passive file bus*,
the same transport brainstorm and gavel use. This is additive: the stdio MCP tools in
`mcp_server.py` remain the load-bearing path and are unchanged.

## Transport (passive bus, filesystem-mediated)

| Half | Where | What |
|------|-------|------|
| OUT  | `$SCREEN_DIR/*.html` | option / status cards the cockpit renders (`write_card`, `advertise_surfaces`) |
| IN   | `$STATE_DIR/events` (JSONL) | verb requests / wake events (`read_events`, `read_verb_requests`) |

Dir precedence (per cl-plugin-structure channel-patterns):
`explicit arg -> $STATE_DIR / $SCREEN_DIR env -> newest session dir under $GRIOT_BUS_ROOT -> created fallback`.

Because nothing depends on a live notification listener, the **same** code runs in an interactive
terminal, in Cowork cloud, and under headless `claude -p`. Every IO path is guarded — a bus failure
is swallowed to stderr and never reaches stdout (the MCP JSON-RPC channel) or crashes the server.

## Verbs advertised

`fetch` · `digest` · `compare` (see `channel_bus.CINOPSIS_VERBS`). Each maps to the SAME functions
the stdio tools wrap — no forked logic. `mcp_server.py` calls `channel_bus.advertise_surfaces()`
once on startup, writing `cinopsis-surfaces.json` (a `{tools:{}}` floor + verb registry) to
`$STATE_DIR` and a status card to `$SCREEN_DIR`.

Quick check: `python scripts/mcp_server.py --list-bus-verbs` · smoke: `python scripts/channel_bus.py`.

## Bridging to the shared digital-griot-mcp

The reference server is prism `scripts/digital-griot-mcp/digital-griot-mcp.ts`
(`capabilities:{tools:{}}`, `$STATE_DIR/events`, HTML cards to `$SCREEN_DIR`). Cinopsis does **not**
duplicate that server; it mirrors its file-bus contract so a cockpit already watching a session's
`$STATE_DIR`/`$SCREEN_DIR` picks up Cinopsis's surface with zero extra wiring. To route Cinopsis
under a shared session, point `$STATE_DIR`/`$SCREEN_DIR` (or `$GRIOT_BUS_ROOT`) at that session's
dirs — the manifest + cards land beside brainstorm/gavel's.

## Live-push (opt-in, later)

Layer `experimental["claude/channel"]` + `notifications/claude/channel` on top ONLY for interactive
surfaces (real-time wake), never as the load-bearing path — it is inert headless (no consumer).
