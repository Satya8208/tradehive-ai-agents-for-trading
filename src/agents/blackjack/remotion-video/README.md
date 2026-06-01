# Blackjack God - Promotional Video

A stunning promotional video for the Blackjack God AI card counting system, built with [Remotion](https://remotion.dev).

## Video Overview

**Duration:** 30 seconds @ 30fps (900 frames)
**Resolution:** 1920x1080 (Full HD)
**Format:** MP4/GIF

### Scenes

1. **Intro Scene (0-7s)** - Dramatic logo reveal with floating card suits and gold/black casino aesthetic
2. **Card Counting Demo (6-14s)** - Live Hi-Lo counting visualization with cards flipping and running count
3. **Stats & Features (13-20s)** - Animated statistics and feature highlights
4. **Pricing (19-25s)** - Three-tier pricing cards with spotlight on best value
5. **Outro/CTA (24-30s)** - Final call to action with logo

### Visual Style

- **Colors:** Dark void (#050505), gold accents (#d4a853), emerald for positive (+1), ruby for negative (-1)
- **Fonts:** Cinzel (headlines), Outfit (body), JetBrains Mono (numbers/code)
- **Animations:** Spring physics, fade transitions, gold wipe overlays

## Getting Started

### Prerequisites

- Node.js 18+ or Bun
- npm, yarn, pnpm, or bun

### Installation

```bash
cd src/agents/blackjack/remotion-video
npm install
```

### Development

Start the Remotion Studio to preview and edit:

```bash
npm run dev
```

This opens the Remotion Studio at `http://localhost:3000` where you can:
- Preview the video in real-time
- Scrub through the timeline
- Adjust parameters
- Export frames

### Rendering

Render the final video:

```bash
# MP4 video
npm run build

# or render with custom settings
npx remotion render BlackjackPromo out/blackjack-promo.mp4 --codec=h264
```

Output will be saved to `out/blackjack-promo.mp4`.

### Render Options

```bash
# High quality (slower)
npx remotion render BlackjackPromo out/promo-hq.mp4 --crf=15

# Lower quality (faster, smaller file)
npx remotion render BlackjackPromo out/promo-web.mp4 --crf=28

# GIF (for social previews)
npx remotion render BlackjackPromo out/promo.gif --frames=0-90

# WebM format
npx remotion render BlackjackPromo out/promo.webm --codec=vp8
```

## Project Structure

```
remotion-video/
├── src/
│   ├── Root.tsx           # Composition definitions
│   ├── index.ts           # Entry point
│   ├── BlackjackPromo.tsx # Main video composition
│   └── components/
│       ├── IntroScene.tsx        # Logo animation scene
│       ├── CardCountingScene.tsx # Card counting demo
│       ├── StatsScene.tsx        # Features showcase
│       ├── PricingScene.tsx      # Pricing cards
│       └── OutroScene.tsx        # Final CTA
├── package.json
├── remotion.config.ts
└── tsconfig.json
```

## Customization

### Changing Colors

Edit the `COLORS` object in each component:

```tsx
const COLORS = {
  void: "#050505",      // Background
  gold: "#d4a853",      // Primary accent
  emerald: "#2dd881",   // Positive/success
  ruby: "#e85454",      // Negative/alert
  // ...
};
```

### Adjusting Timing

In `BlackjackPromo.tsx`, modify scene durations:

```tsx
const INTRO_DURATION = 7 * fps;    // 7 seconds
const COUNTING_DURATION = 8 * fps; // 8 seconds
// ...
```

### Adding New Scenes

1. Create component in `src/components/`
2. Import in `BlackjackPromo.tsx`
3. Add `<Sequence>` with appropriate timing

## Animation Guidelines

- Use `useCurrentFrame()` and `interpolate()` for all animations
- Spring physics: `spring({ frame, fps, config: { damping: 200 } })`
- Stagger delays: `delay={index * 20}` for sequential items
- Fade transitions: 15-30 frames (0.5-1 second)

## Troubleshooting

**Fonts not loading?**
- Ensure Google Fonts are available in your network
- Fallback fonts are defined in components

**Rendering slow?**
- Reduce resolution during development
- Use `--frames=0-30` to test short segments
- Lower `--concurrency` if memory issues

**TypeScript errors?**
- Run `npm install` to ensure all types are installed
- Check `tsconfig.json` settings

## License

Part of the Blackjack God project. Built with Remotion.
