---
date: 2026-04-09
topic: Cowork plugin support vs Claude Code plugins
status: research complete
affects: cl-plugin-structure skill (v0.4.0 → planned v0.5.0)
---

# Cowork Plugin Compatibility Research

## Question

Claude now has plugin support in Cowork (https://support.claude.com/en/articles/13837440-use-plugins-in-cowork). How do Cowork plugins differ from Claude Code plugins, and how should the `cl-plugin-structure` skill be updated to cover both surfaces?

## Sources Consulted

1. **Cowork plugin help article** — https://support.claude.com/en/articles/13837440-use-plugins-in-cowork
   - High-level user-facing doc
   - Describes plugins as bundles of "skills, connectors, and sub-agents"
   - Explicitly defers to Claude Code docs for manifest/structure details
2. **Claude Code plugins reference** — https://code.claude.com/docs/en/plugins-reference
   - Authoritative schema reference
   - Does not mention Cowork (Cowork borrows its format)

## Key Finding

**Cowork and Claude Code share the same plugin format.** The Cowork article links to "the Plugins reference in the Claude Code docs" as the canonical structural reference. `plugin.json`, `marketplace.json`, skills, and MCP server configuration are identical across both surfaces.

What differs is **which components are meaningful on each surface**, because Cowork is a desktop chat product and Claude Code is a dev-tool CLI. A component that depends on tool-call lifecycle events or a Bash tool simply has nothing to bind to in Cowork.

## Component Compatibility Matrix

| Component | Claude Code | Cowork | Confidence | Notes |
|---|---|---|---|---|
| `skills/` | yes | **yes — primary surface** | high | Cowork users invoke via `/` or `+` button. Same SKILL.md format. |
| `agents/` | yes | likely yes, UI unclear | medium | Cowork article lists "sub-agents" as a plugin ingredient but doesn't show a UI for invoking them. Ship and test. |
| `.mcp.json` local stdio | yes | **yes** | high | Cowork explicitly: "Plugins may include local MCP servers that run on your computer with the same permissions as any other program you run." |
| `.mcp.json` remote/HTTP connector | yes | **yes, cloud-routed** | high | **Gotcha:** Cowork connectors reach external services *through Anthropic's cloud*, not your local network. Custom connectors must be publicly internet-reachable; firewalled/self-hosted servers require special network config. |
| `hooks/hooks.json` | yes | **no (assumed)** | medium-high | Cowork has no `PostToolUse`/`PreToolUse`/`WorktreeCreate`/`PreCompact` lifecycle the way Claude Code does. Events don't map to a chat UI. Not advertised by Cowork docs. |
| `.lsp.json` | yes | **no** | high | Cowork has no in-editor code intelligence surface. |
| `bin/` executables | yes | **no** | high | Binaries here are added to the Bash tool's PATH. Cowork has no Bash tool. |
| `commands/` slash commands | yes (legacy) | n/a | high | Cowork already owns `/` as the skill picker. |
| `output-styles/` | yes | **no (assumed)** | medium | CC-specific formatting concept; no Cowork equivalent documented. |
| `channels` | yes | unclear | low | Channels are MCP-server-backed, so the MCP half works. The hook/notification integration is Claude Code-flavored; Cowork surface behavior is undocumented. |
| `userConfig` (enable-time prompts) | yes | **yes (equivalent)** | high | Cowork exposes this through its Customize menu. |
| Marketplace (`marketplace.json`) | yes | **yes, conceptually** | medium | Cowork references "a growing library of plugins" browseable via Customize. Schema is presumed shared. |

## Cowork-Specific Concepts

### Plugin Create
A built-in Cowork plugin that "walks you through the process" of creating a custom plugin. The Claude Code equivalent is `claude --plugin-dir ./my-plugin` + `claude plugin validate .`. Plugin Create is the authoring on-ramp for non-CLI Cowork users.

### Customize Menu
Cowork's installation/enable/disable UI lives under the Customize tab in the Cowork sidebar. Functionally equivalent to `claude plugin install|enable|disable`, but surfaced as a GUI. Same underlying scope model presumably applies.

### Connector Cloud Routing (critical gotcha)
> "Connectors in Cowork reach external services through Anthropic's cloud, not through your local network."

This is the single biggest architectural difference for plugin authors. A Claude Code plugin that bundles a local stdio MCP server "just works" in both surfaces. But if you ship a remote MCP connector expecting it to be reachable from the user's machine, it must be **publicly internet-reachable** in Cowork. Self-hosted / firewalled / LAN-only servers need additional network configuration.

## Gaps / Open Questions

1. **Are plugin agents actually exposed in Cowork UI?** Article lists them but shows no UI screenshot. Needs empirical verification.
2. **Do hooks fire at all in Cowork?** Article is silent. Assumed no based on absence of lifecycle concepts, but unconfirmed.
3. **Channels behavior in Cowork** — MCP server half should work; the notification/hook integration is undocumented.
4. **Does `claude plugin validate .` catch Cowork-specific issues?** Presumed no — it validates schema, which is shared.

## Impact on `cl-plugin-structure` Skill

The skill currently frames itself as "Plugin Structure for Claude Code" and presents all components as universal. It needs:

1. **Retitle/reframe** — "Plugin Structure for Claude Code and Cowork" with a note that the format is shared.
2. **Add Cowork column to Components table** ([SKILL.md:87](../../../SKILL.md#L87)) with yes/no/cloud-only annotations.
3. **Add Cowork caveat to the MCP Servers row** — call out cloud routing for remote connectors specifically.
4. **Flag Claude Code-only components** — hooks, LSP, `bin/`, output-styles. Currently presented without surface qualification.
5. **Mention "Plugin Create"** in the Development Workflow section ([SKILL.md:161](../../../SKILL.md#L161)) alongside `claude --plugin-dir`.
6. **Add a "Surface Compatibility" section** near the top so authors make the CC-vs-Cowork decision early rather than discovering constraints during deploy.
7. **Keep all existing Claude Code content** — nothing is deprecated, just qualified.

## Proposed Edits (concrete)

- **Frontmatter `description`**: extend to mention both Claude Code and Cowork
- **Heading `# Plugin Structure for Claude Code`** → `# Plugin Structure for Claude Code and Cowork`
- **New short section after the heading**: "## Surface Compatibility" — one-paragraph summary + link to full matrix in a reference file
- **Components table** ([SKILL.md:87](../../../SKILL.md#L87)): add a "Cowork" column
- **MCP Servers row**: add footnote about cloud-routed connectors
- **New reference file**: `references/cowork-compatibility.md` containing the full matrix + the connector cloud gotcha
- **Development Workflow section**: add a Cowork subsection mentioning Plugin Create + Customize menu install
- **Version bump**: 0.4.0 → 0.5.0 (minor — backward-compatible additions, no removed content)

## Recommendation

Implement the edits above. The skill remains authoritative for plugin authoring in both surfaces. Authors building primarily for Cowork need only the new Surface Compatibility section + the MCP cloud-routing note; everything else just works. Authors building for Claude Code lose nothing — all existing content remains valid.

## References

- https://support.claude.com/en/articles/13837440-use-plugins-in-cowork (Cowork plugin article)
- https://code.claude.com/docs/en/plugins-reference (Claude Code plugin reference)
- https://support.claude.com/en/articles/13205175-get-started-with-claude-cowork (Cowork overview — 404 at time of research)
