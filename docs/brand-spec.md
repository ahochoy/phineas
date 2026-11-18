# Phineas web-demo design direction

User-approved direction: credit-union-inspired, sans-serif, black and white with
orange accents, square edges. This is an independent Phineas interface, not a
reproduction of another institution's identity. No credit-union logos, assets,
affiliation claims, or external font requests.

## Visual system

- Header and section-title bars: near-black `#151515` with white `#ffffff` text.
- Primary content: white with near-black text; secondary text `#555555`.
- Accent: orange `#f26922`; primary orange buttons use near-black text rather
  than white. Links on white use darker orange `#a63b00` with underlines.
- Typography: local sans-serif stack, `Arial, Helvetica, sans-serif`; bold
  sans-serif headings, not the earlier proposed serif heading treatment.
- Spacing: 8px base, 16px and 24px panel spacing, 32px section separation.
- Radius: 0 by default; at most 2px for controls. No pill-shaped controls.
- Borders: thin neutral dividers; no decorative shadows or gradients.
- Motion: state feedback only; preserve visible keyboard focus and readable
  loading, empty, quota, expiration, and failure states.

## First screen

Show Phineas and a synthetic-data notice in the black header. Offer two approved
sample choices and a Start analysis action. Once active, present findings beside
a bounded chat panel with six supported-question shortcuts. Stack panels on
mobile. Include End session and purge, with no arbitrary upload control, invented
findings, persistent chat history, or unsupported free-form-assistant claims.

## Design read

Greenfield financial-analysis workspace for recruiters and technical reviewers.
Familiar, restrained layout; low motion; medium information density; no imagery
dependence; original Phineas identity guided by the user's explicit palette and
shape preferences. Dials: visual variance 2/10, motion 1/10, density 6/10,
asset dependence 1/10, brand fidelity 3/10 (new identity, not a bank replica).

The screen's purpose is immediate use, not a marketing landing page. Optimize for
laptop and phone reading distance, an authoritative but approachable tone, and
findings/chat content that fits without decorative sections.

## Approved draft and live extension

The developer approved the first visual draft. Preserve its layout, palette,
type, spacing, square controls, and mobile stacking. Remove the temporary
Interface preview badge and preview-only copy when connecting real API behavior;
retain Synthetic data only. Replace Clear preview with End session & purge and
enable the bounded question composer. No redesign, visual variants, external
assets, analytics, or typography changes are part of that extension.

## Phineas's conversational voice

Phineas is a financial-analysis partner, not a detached report narrator or a
financial adviser. The intended audience includes millennial and Gen Z adults
getting a handle on their finances; write naturally without assuming that every
visitor shares an age, income, spending habit, or attitude toward AI.

Use first person for Phineas's observations ("I found", "I can't tell from this
summary") and second person for the reader's choices. Never attribute Phineas's
findings to the reader. Keep answers warm, concise, and nonjudgmental, with natural
contractions, clear uncertainty, and at most one useful, topic-specific next step.
Avoid institutional filler, repeated recommendations, forced slang, emojis,
cheerleading, and manufactured reassurance. Personality does not imply access to
bank accounts, actions taken, professional credentials, or financial advice.

## Synthetic source preview extension

Keep the approved screen unchanged except for a native Preview records
disclosure below the sample choices. Use the existing black/white headers,
neutral dividers, square edges, and small sans-serif table text. Show every source
column and row, preserve the CSV cell strings, and use horizontal scrolling
inside the table region rather than widening the page. Column headings, row
numbers, a caption, and keyboard access make the read-only grid understandable.
Label it as synthetic, pre-sanitization source data; do not imply these records
are model inputs or that previewing starts an analysis session.
