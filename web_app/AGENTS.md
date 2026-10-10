# eregion frontend conventions

The user established the current frontend redesign as the style to continue on
2026-10-08. Extend this design when adding or fixing features.

## Source of truth

- `tokens.css`: colors, light/dark themes, fonts, radii and overlay shadows.
- `apply.css` and `apply.html`: current shell, spacing, components and SVG icons.
- `chat-typography.css`: message typography and Markdown presentation.
- `career-chat.js`, `apply-answers.js`, `pages.js`, `insights.js` and
  `conversations.js`: current result cards, questions and workspace interactions.
- `../design/redesign/v2/`: visual references. The implemented files take
  precedence over old mockups and the proposal sections of `REDESIGN_PLAN.md`.

## Visual language

- Use the existing warm neutral light palette and near-black dark palette.
  Reference semantic CSS variables instead of introducing component-specific
  hard-coded colors. Use `--signal` sparingly for attention/current progress,
  `--good` for verified/success states, and `--danger` for destructive actions.
- Keep Geist as the UI font and Geist Mono for technical snippets/URLs. Follow
  the existing 15px body scale, comfortable line heights, light display numbers
  and restrained 400/500/600 weight hierarchy.
- Preserve generous whitespace, quiet navigation and thin card outlines. Use
  the existing rounded surfaces and reserve stronger shadows for overlays.
- Give a card one visually dominant primary action, using the theme-aware pill
  button. Secondary actions remain quiet text buttons. Reuse the SVG sprite and
  its stroke style for interface icons.
- Present scores as large, light-weight numbers with small denominators and
  simple counts. Follow the existing grayscale chart palette for tracker views.

## Layout and interaction

- Keep conversation central: left history/navigation, a readable central column,
  the bottom composer, and an optional right Agent activity panel. Applications,
  Materials, Archived and Trash remain views within the existing `/apply` shell.
- Reuse the current component anatomy for job matches, documents, questions,
  final review and interview feedback. Keep approved materials collapsible and
  expose detailed traces/evidence progressively.
- Keep the current stepped question presentation and collect answers before the
  final batch submission. Preserve drafts when polling or navigating questions.
- Maintain mobile drawers, keyboard/focus behavior, reduced-motion support and
  both themes. Keep existing IDs and API wiring when changing presentation.
- Use concise user-facing text and rendered Markdown. Place implementation
  details in the activity/debug surfaces when they are needed.

For a visible UI change, inspect the affected state in light and dark themes and
at desktop and mobile sizes. Let the current implementation guide small choices;
ask only when the user's request would materially change this design direction.
