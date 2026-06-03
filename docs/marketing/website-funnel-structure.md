# Unicorn Tears and Unicorn Viz Website Funnel Structure

Owner: Studio Marketing
Status: active
Last updated: 2026-06-03

## Purpose

Define a practical conversion architecture for both official websites so all
campaign traffic has a clean path from discovery to action.

This document covers:

- Site roles and traffic split.
- Page-level funnels and CTAs.
- Launch-mode and post-launch-mode homepage logic.
- Embedded commerce and supporter integration points.

## Site Roles

### unicorntears.com

Primary role: artist and livestream hub.

- Own DJ Unicorn Tears identity, schedule, and premiere narrative.
- Convert visitors into stream attendees, subscribers, supporters, and merch buyers.
- Host campaign storytelling and social proof.

### unicornviz.com

Primary role: product and creator conversion hub.

- Own Unicorn Viz product positioning.
- Convert visitors into free core downloads, paid drop-in buyers, and power users.
- Route creator traffic into tutorials, docs, and premium upgrades.

## Global Funnel Model

All inbound traffic should map to one of these conversion paths:

1. Watch path: click from social to live/replay destination.
2. Download path: click to free core Unicorn Viz install flow.
3. Buy path: click to paid drop-ins, bundles, or merch pages.
4. Join path: click to Substack, Locals, supporter tiers, or email list.

Avoid sending cold traffic to generic pages with too many equal-priority links.

## Homepage Architecture: Launch Mode

### unicorntears.com launch homepage

#### Section order

1. Hero block: premiere headline, countdown, primary watch CTA, secondary "join list" CTA.
2. Stream schedule strip: six-day lineup card with quick day-by-day links.
3. Why this launch block: 3 bullets on artist identity, unreleased visuals, and world-premiere angle.
4. Live destination chooser: YouTube, Twitch, Kick, Rumble, replay destination notes.
5. Support block: memberships, tips, merch, and 10% animal support statement.
6. Recency block: latest clip, latest recap, latest announcement.
7. Footer conversion: email capture + social follow icons + legal/mission links.

#### Primary CTA set

- Main: "Watch the world premiere live"
- Secondary: "Join premiere alerts"
- Tertiary (below fold only): "Support the project"

### unicornviz.com launch homepage

#### Section order

1. Hero block: what Unicorn Viz is, free core CTA, premium drop-ins CTA.
2. Product proof block: 20 to 45 second demo reel with captions.
3. Free-vs-premium comparison block: concise feature differentiation.
4. Launch offers block: free starter pack, premiere bundle, premium drop-ins.
5. Creator outcomes block: use-case cards for DJs, streamers, VJs, visual artists.
6. Docs/tutorials block: links to getting started and key docs.
7. Support mission block: 10% proceeds to animals in need.

#### Primary CTA set

- Main: "Download Unicorn Viz core free"
- Secondary: "Unlock premium drop-ins"
- Tertiary: "Watch it live in action"

## Homepage Architecture: Post-Launch Mode

After D+7, reduce countdown emphasis and replace with replay and product depth.

### unicorntears.com post-launch mode

- Replace countdown with "Watch replay highlights" module.
- Keep weekly stream schedule visible near top.
- Rotate supporter and membership offers by week.

### unicornviz.com post-launch mode

- Promote onboarding flow and top premium bundles.
- Feature one new drop-in or tutorial each week.
- Add social proof from creators using Unicorn Viz.

## Key Landing Pages

### unicorntears.com

- `/premiere`: canonical event page with stream embeds, schedule, and recap links.
- `/live`: always-current live destination with platform chooser.
- `/support`: memberships, tipping rails, mission statement, and FAQ.
- `/music`: Spotify and replay-linked music/track page.
- `/store`: merch and digital artist-side products.

### unicornviz.com

- `/download`: free core acquisition and install flow.
- `/premium`: paid drop-ins and bundles.
- `/affiliates` (planned): affiliate program information, sign-up form, commission terms, and referral resources.
- `/demo`: live product demos and clips.
- `/docs`: onboarding and core documentation links.
- `/compare`: free core versus premium matrix.

## Conversion Blocks and Copy

Use fixed conversion components to reduce production friction.

### High-intent CTA blocks

- "Start free with Unicorn Viz core"
- "Get launch-ready with premium drop-ins"
- "Watch DJ Unicorn Tears live"
- "Join for early drops and behind-the-scenes access"
- "10% of proceeds helps animals in need"

### Trust and proof blocks

- Recent stream metrics or social proof (as available).
- Quote or review cards from early users or partners.
- Screenshots and short loop embeds from real sessions.

## Embedded Commerce and Community

- Embed Fourthwall collections where native and performant.
- Keep checkout path to three clicks or fewer from homepage when possible.
- Keep Substack and Locals signup modules native to each page context.
- Keep Buy Me a Coffee, PayPal, and Rumble Wallet references in support blocks,
  not in every section.

## Information Architecture Rules

- One page, one primary goal.
- No more than two primary CTA buttons above the fold.
- Keep "watch" and "download" paths visually distinct.
- Keep launch messaging and evergreen messaging in separate modules.
- Use campaign tags for all inbound links.

## Measurement Plan

Track both sites at page and flow level.

### Core metrics

- Homepage click-through rate by CTA.
- Landing page conversion rate by source platform.
- Email and community signup conversion.
- Free core download starts and completions.
- Premium drop-in purchase conversion.
- Merch conversion and average order value.

### Weekly optimization loop

1. Identify top traffic source and top converting page path.
2. Replace weakest homepage module with stronger proof or cleaner CTA.
3. A/B test one CTA headline and one hero visual each week.
4. Keep changes incremental to preserve attribution clarity.

## Build Sequence

### Sprint 1: pre-launch essentials

- Build launch-mode homepage versions for both sites.
- Build premiere event page and product download page.
- Wire analytics and campaign-tag routing.
- Add stable global nav and footer with campaign priorities.

### Sprint 2: conversion layers

- Build premium offers page and compare page.
- Add supporter and mission pages.
- Add testimonial and proof modules.

### Sprint 3: post-launch transition

- Swap countdown modules for replay modules.
- Add weekly highlights and release cards.
- Add recurring stream and drop schedule components.

## Quick QA Checklist

- Every key page has one obvious primary action.
- Every CTA button lands on a working page.
- Mobile hero sections render cleanly with no clipped buttons.
- Stream and store embeds load quickly and fail gracefully.
- Mission/donation statement is visible but not intrusive.

## Related Docs

- [Launch Marketing Strategy](launch-marketing-strategy.md)
- [Launch Asset Matrix](launch-asset-matrix-2026-06.md)
