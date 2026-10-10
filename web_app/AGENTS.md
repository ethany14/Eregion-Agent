# Eregion frontend conventions

On 2026-10-09 the user chose the Eregion "v4-final" design: v4's layout with v3's
colouring, no background waves and no compass, plus a Day/Night toggle. Extend
this design when adding or fixing features.

## Source of truth

- `tokens.css`: colours, Night (default) and Day palettes, fonts, radii and
  shadows. `../chrome_extension/shared/tokens.css` is a copy without the font
  import; keep the two in sync.
- `eregion.css`: the Eregion visual layer (sidebar, theme toggle, trail, sheets,
  Chronicle, the Road, the Forge). It loads after `apply.css`, which still holds
  the base shell and component layout.
- `apply.html`: shell, SVG sprite (holly mark, Chronicle, Council, Road, Forge,
  beacon, Ithil/Anor) and the head script that applies a saved theme before paint.
- `theme.js`: Day/Night state, stored as `eregion.theme` (`light` or `night`).
  Without a stored choice the app follows the system setting.
- `chat-typography.css`: message typography and Markdown presentation.
- `career-chat.js`, `apply-answers.js`, `pages.js`, `insights.js` and
  `conversations.js`: result cards, questions, pages and workspace interactions.
- `../design/v4-final/`: visual reference. The implemented files take precedence.
  Earlier versions are preserved under `../design/archive/`.

## Visual language

- Night is holly-night with ithildin-silver ink; Day is parchment. Use semantic
  variables only: `--holly` for progress and success, `--signal` (the beacon
  flame) only for "needs you", `--gold` for an offer or a sealed document,
  `--river` for information, `--danger` for destructive actions.
- Type: `--map` (IM Fell English SC) for place names, page titles and section
  labels; `--serif` (EB Garamond) for headings, greetings and large numbers;
  `--sans` (Inter) for UI text; `--mono` for technical snippets.
- Panels are sheets: thin inked frame with two corner ticks, 3–4px radius.
  Keep generous whitespace. Never put decorative patterns, waves or textures
  behind content.
- Every process is a trail (`ol.trail` of `li.st` with `done`, `now`, `wait`
  or `gold`): application stages (Sighted → Prepared → Sent → In interview →
  Offer), materials (Drafted → Tempered → Sealed), the agent's "way", and the
  conversation journey. Use `.trail.compact` in rows.
- A card has one dominant primary action (the pill button); secondary actions
  stay quiet text buttons. Reuse the sprite and its stroke style for icons.

## Layout and naming

- Sidebar: Chronicle (home), Council (conversations), The Road (applications),
  The Forge (materials), Job alerts, "Beacons lit" conversations, Archive
  (Archived and Trash tabs), then the person and the Day/Night toggle.
- The Chronicle is the empty career state: greeting, composer, today's entries,
  beacons and the road. Conversation stays central; The Lookout is the optional
  right panel. All pages are views inside the `/apply` shell.
- Keep the stepped question presentation and batch submission; preserve drafts.
- Keep existing IDs, test hooks and API wiring when changing presentation.
- Maintain mobile drawers, keyboard/focus behaviour and reduced motion.

For a visible UI change, inspect the affected state in Night and Day at desktop
and mobile sizes. A request for a "new version" means a new layout and structure,
not a reskin; preserve the current version under `../design/archive/` first.
