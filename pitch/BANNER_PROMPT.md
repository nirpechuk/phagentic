# PHAGENTIC — Banner image prompt

Prompts for generating a hero/banner image (Devpost header, slide title, repo social card). The look must match our UI: warm parchment, ink line-work, methylene-blue accents, a hand-drawn naturalist/lab-notebook feel — **not** a glossy tech banner.

**Brand constants (keep these consistent across any tool):**
- Background: warm parchment / aged paper `#ece4d6`
- Ink: warm dark brown-grey `#3b372f`
- Accent: deep methylene blue `#265cc8`, fading to a pale colorless `#e4e2d6`
- Type: title in an elegant serif (Instrument Serif); supporting text in a clean geometric sans (Space Grotesk)
- Motif: a line-drawn **bacteriophage** (icosahedral head, tail sheath, leg fibers) + a **blue⇄colorless oscillation waveform**
- Mood: scientific, calm, precise, slightly vintage — a control-systems sketch in a naturalist's field journal

---

## Primary prompt (drop into your image tool)

> A wide landscape banner in the style of a vintage scientific field journal. Warm parchment paper background (color #ece4d6) with subtle watercolor washes and faint dot-grid texture. Centered: a single elegant line-drawn bacteriophage — a geometric icosahedral head on a slender tail with delicate leg fibers — inked in warm dark brown-grey (#3b372f), with its head washed in deep methylene blue (#265cc8). A smooth blue-to-colorless oscillating sine wave (#265cc8 fading to pale #e4e2d6) runs horizontally across the banner, threading behind the phage like a heartbeat trace, representing a chemical reaction oscillating between blue and clear. Small hand-plotted lab annotations and hairline measurement marks in monospace around the edges. The title "PHAGENTIC" in a refined editorial serif, with the tagline "The OS for autonomous bioreactors" in a clean geometric sans beneath it. Composition feels like an antique botanical/anatomical plate crossed with a modern control-systems diagram. Flat, elegant, no 3D gloss, no neon, no photorealism. Muted, sophisticated, scientific. 16:9, high detail, plenty of negative space.

**Negative prompt:** glossy, neon, dark mode, 3D render, photorealistic lab photo, stock cloud/server icons, busy clutter, cartoonish, sci-fi UI, lens flare, gradient mesh.

---

## Variations (pick per surface)

**A — Minimal logo lockup (favicon / social card):**
> A minimalist emblem on warm parchment (#ece4d6): one small line-drawn bacteriophage (icosahedral head, tail, fibers) in ink (#3b372f) with a methylene-blue (#265cc8) head, sitting above the word "PHAGENTIC" in an elegant serif. A single thin oscillating waveline beneath. Lots of negative space, centered, flat, refined. Square 1:1.

**B — The bioreactor scene (storytelling header):**
> Vintage scientific illustration on aged paper: a laboratory flask of oscillating blue liquid (the Blue Bottle reaction, half deep methylene blue #265cc8, half going colorless #e4e2d6) connected by thin inked lines to a small circuit board, a stirrer, and two pumps — drawn like an engineer's notebook schematic. Faint sine-wave trace overlaid showing the oscillation. Warm #ece4d6 background, brown-grey ink (#3b372f). Hand-annotated, calm, precise. Title "PHAGENTIC" top-left in editorial serif. 16:9, flat, no gloss.

**C — The closed loop (concept-forward):**
> A circular control-loop diagram rendered as elegant journal line-art on parchment (#ece4d6): a color sensor → a brain → pumps and a stirrer → a flask of blue↔colorless oscillating liquid → back to the sensor, the loop traced in a flowing methylene-blue ribbon (#265cc8). A small phage glyph marks the loop. Ink #3b372f, monospace labels. "PHAGENTIC — closing the loop on antibiotic resistance" in serif. 16:9, flat, sophisticated, no 3D.

---

## Notes
- If the tool over-saturates, instruct: "muted, desaturated, vintage print, limited 3-color palette (parchment, ink, methylene blue)."
- Ask for **text rendered cleanly**, or generate text-free and overlay "PHAGENTIC" in Instrument Serif yourself for crisp type.
- For a repo social card, target 1280×640; for a Devpost header, 1200×675 (16:9); for slides, 1920×1080.
- The phage glyph here should match the one on our landing page (icosahedral head + tail fibers) so the banner and the app feel like one product.
