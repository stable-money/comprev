# Manual compliance checklist — rules the engine cannot auto-check

Source policy: **Advertisement Guidelines — Mutual Funds, May 2026**
(`config/policies/mf-ad-guidelines-2026-05.docx`).

comprev reviews what is *in the creative* (on-screen text, voice-over, visuals). The
rules below depend on **process, metadata, or external data** that can't be derived from
the video/image itself, so they are deliberately **not** automated checks — automating
them would risk a false "pass." A human reviewer must confirm these before sign-off.

## Process / approval
- [ ] **AMC written sign-off** obtained for any scheme name / logo / performance / factsheet
      content used in a scheme-specific ad, and retained on record (§2 Dos).
- [ ] Ad conforms to any restrictions the AMC imposed at sign-off (§2 Dos).
- [ ] **Internal compliance review timelines** met: Videos T-7, Creatives T-5, Comms T-3 (§1).

## Data correctness (needs external/source data)
- [ ] **Data cut-off** is the last day of the month-end preceding release (e.g. a June 2026
      ad uses data as of 31 May 2026) (§2 vii).
- [ ] Disclosed **CAGR / point-to-point figures are accurate** against the AMC factsheet /
      credible source, and the source is correctly cited (§2).
- [ ] **Risk-o-meter is the latest** published and reflects last month-end data (§2) — the
      engine can confirm a risk-o-meter is *present* but not that it's current.
- [ ] Any factual claim/statistic is **backed by a verifiable, recent, credible source**
      and the citation actually supports it (§2).

## Scheme-age rules (needs scheme metadata)
- [ ] Scheme **in existence < 6 months** → past performance **NOT** shown (§2 iv).
- [ ] Scheme **6–12 months** → simple annualized growth (not CAGR) for past 6 months and
      since inception (§2 iv).

## Category & celebrity judgement
- [ ] Ad is **correctly categorized** (Scheme-Specific / Non-Scheme-Specific / Celebrity)
      and routed accordingly (§1). The engine flags signals but the category is a human call.
- [ ] If a celebrity appears, confirm it is a **permitted industry-level AMFI campaign** or
      **generic brand promotion that does not promote MFs** — otherwise it is prohibited
      (§4). (The engine flags any recognizable public figure as a violation by default.)

> The engine's automated checks cover the content-detectable rules (disclaimers, banned
> terms/claims, performance-format presence, risk-o-meter presence, celebrity/logos via
> vision, etc.) and stamp each report with the policy version + checks hash. This checklist
> is the human half that makes a review complete.
