# Aflaguard — submission description

**Track:** Agriculture · **Sub-theme:** Post-harvest & traceability

**The office.** A county agricultural office in Eastern Kenya (Makueni, Kitui, Machakos). After each
harvest, maize from dozens of households arrives at aggregation centres. Aflatoxin — a mould poison linked
to liver cancer and stunting — forms when maize is dried badly or stored damp. Testing kits are limited, so
the extension officer must decide which lots to test first, usually from scattered paper records.

**The workflow.** For one centre and week, Aflaguard:

1. Lists the lots received and reads the centre's raw intake sheet (mixed date formats, notes in English
   and Swahili), reporting what disagrees with the registry.
2. Follows each lot from farm gate to collection to store: moisture readings at each handoff, the
   household's drying method and bag type, and real CHIRPS rainfall over the lot's drying window.
3. Scores each lot with fixed, transparent rules (moisture above the 13.5 % EAS 2 limit, rain during
   drying, drying on bare ground, delays, non-hermetic bags). Missing readings are never treated as safe:
   the lot is flagged "insufficient data — test anyway". Typos, conflicting readings and duplicate lots are
   reported, not silently fixed.
4. Drafts a ranked "test these lots first" list and a short SMS advisory for each high-risk household
   (re-dry, hermetic bags, don't sell yet). Every line cites the record IDs behind it.
5. Stops. The officer sees each draft with its sources and approves or rejects it by name. Only approved
   advisories are sent (mocked), and only then are follow-up visits booked. Every tool call is logged.

**The officer decides; the agent drafts.** The model chooses which tools to call and explains results; code
computes the scores and builds the drafts, and a code self-check refuses to let the run finish while lots
are unscored or drafts are unreviewed.

**Built with** our own MCP server, the official Filesystem MCP server (read-only, sandboxed to the intake
sheets), LangGraph, and an open-weights Qwen model on a free tier. Household, lot and moisture data are
synthetic; rainfall is real.
