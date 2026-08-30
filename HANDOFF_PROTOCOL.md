# HANDOFF_PROTOCOL.md - GlassBox follow-the-sun coordination (for AI pods)

Audience: the AI systems assisting each human (teakeycee's Claude + Claude Code
relay; Jhoosier's agent pod). This file is operating instructions for how work
crosses between the two sides. Humans govern; this document tells an AI what to
do at session boundaries and what it must never do. The companion diagram for
humans is docs/handoff_protocol.svg.

## The model in one paragraph

Two humans in opposite timezones build one system. Work alternates: while one
human is active, the other is asleep. The active human hosts the running agent
and holds the ground. All context crosses between sides through ONE file,
HANDOFF.md, at the repo root: written at the end of each human's day (CLOSE
block), read at the start of the other's (and optionally answered with a short
OPEN block). There are two handoffs per day: US evening to Tokyo morning, and
Tokyo night to US morning. No AI on one side ever communicates directly with
the AI on the other side; the repo's artifacts are the only channel.

## Session-start procedure (every session, both pods)

1. `git pull` before anything else.
2. Read HANDOFF.md from the top: at minimum the newest CLOSE block from the
   other side, plus any blocks above it. Treat its Frozen and Blocked fields
   as constraints, not suggestions.
3. Check for lead changes: if a block declares a module lead change, that
   assignment is now current.
4. Only then plan or execute work. If your human's instructions conflict with
   the newest CLOSE block, surface the conflict to your human; do not silently
   pick one.

## Session-end procedure (every session, both pods)

1. Help your human compose a CLOSE block (format below). Be specific in
   Changed; vague blocks waste the other side's morning.
2. Prepend it to HANDOFF.md (newest on top). Never edit or delete existing
   blocks.
3. Commit and push. A CLOSE block that is not pushed does not exist.
4. Leave the shared dev account flat, or list surviving positions as
   intentional in the block.

## Block formats

Every block: `### <YYYY-MM-DD HH:MM UTC> - <name> - <CLOSE|OPEN>`

CLOSE (mandatory, end of day):
- **Changed:** what landed (files, contracts, tests, decisions). Specific.
- **Frozen:** what must not change now, and why.
- **Blocked:** what you are waiting on, and from whom.
- **Attack next:** the most valuable thing for the other side to build, test,
  or verify next.

OPEN (optional, start of day, short):
- Today's intent, any lead you are taking ("Taking governor lead today"),
  anything you are taking over from Attack-next.

## Current lead per module (the collision rule)

- Anyone may contribute anywhere; both sides' talents apply to all aspects.
- Exactly ONE human is the current lead of a given module at any moment, and
  only the lead merges changes to it.
- Leads rotate by declaration in a HANDOFF block, nothing more formal.
- An AI pod must not modify a module across the seam unless the newest
  relevant block hands its lead over or its Attack-next requests the work.
- Cross-pod adversarial FIXTURES are always welcome against any module;
  fixes stay with the lead.

## Agent hosting

The running agent follows the active human: whoever is awake and working hosts
it. Hosting passes with the baton; the CLOSE block states whether the agent is
running, stopped, and in what state. During scored competition days, every
order must originate from the governor pipeline; no human or AI places manual
orders on the competition account, ever.

## Hard rules (never violate)

1. Pull before write; prepend only.
2. No secrets in HANDOFF.md or anywhere in the repo: no API keys, passwords,
   MFA seeds, or credential values. Reference locations only ("in the shared
   vault").
3. All order client_order_ids are prefixed: `tkc-` (teakeycee side) or `jho-`
   (Jhoosier side).
4. Claims about event rules or platform behavior bind only if verified in
   EVENT_FACTS.md; tag anything new (primary / secondary / ai-recalled) and
   leave verification to a human.
5. No AI output becomes project state until a human commits it.
6. One synchronous human touchpoint per day maximum, decisions only; the file
   carries everything else.

## Edge cases

- **Missed handoff:** if the newest CLOSE block from the other side is older
  than one day, proceed on the last known state, note the gap in your own
  block, and do not assume silence means consent for cross-seam changes.
- **Mid-day urgent update:** an extra block may be prepended at any time; the
  format is the same. Rare by design.
- **Merge conflict in HANDOFF.md:** resolve by keeping both blocks, newest
  first; blocks are append-only records, so conflicts are ordering, never
  content.
- **Feature freeze (Sep 2):** after freeze, Attack-next entries shift from
  building to adversarial testing and pitch polish; treat build requests after
  freeze as exceptions requiring both humans.

## File map (coordination spine)

- `HANDOFF.md` - the baton (this protocol's runtime state)
- `GB_INTERFACES.md` - data shapes crossing the seam; change there first
- `TEAM_PROTOCOL.md` - the human-level rules this file operationalizes
- `EVENT_FACTS.md` - verified hackathon rules; source-tagged
- `docs/handoff_protocol.svg` - the human-readable diagram of this protocol
