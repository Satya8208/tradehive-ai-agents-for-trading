import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";

const COLORS = {
  void: "#050505",
  gold: "#d4a853",
  goldBright: "#f0d48a",
  emerald: "#2dd881",
  ruby: "#e85454",
  textPrimary: "#f5f5f0",
  textSecondary: "#999",
};

// Card data - 6 cards for quick demo
const CARDS = [
  { value: "5", suit: "♦", countValue: +1, color: COLORS.ruby },
  { value: "K", suit: "♠", countValue: -1, color: "#1a1a1a" },
  { value: "2", suit: "♥", countValue: +1, color: COLORS.ruby },
  { value: "A", suit: "♣", countValue: -1, color: "#1a1a1a" },
  { value: "6", suit: "♦", countValue: +1, color: COLORS.ruby },
  { value: "10", suit: "♠", countValue: -1, color: "#1a1a1a" },
];

const PunchyCard: React.FC<{
  value: string;
  suit: string;
  color: string;
  countValue: number;
  delay: number;
  index: number;
}> = ({ value, suit, color, countValue, delay, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // PUNCHY card slam animation
  const cardEntrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 8, stiffness: 200, mass: 0.8 },
    durationInFrames: 12,
  });

  const cardScale = interpolate(cardEntrance, [0, 1], [1.5, 1]);
  const cardOpacity = interpolate(cardEntrance, [0, 0.2, 1], [0, 1, 1]);
  const cardY = interpolate(cardEntrance, [0, 1], [-50, 0]);

  // Count badge POP
  const showCount = frame > delay + 8;
  const countProgress = spring({
    frame: frame - delay - 8,
    fps,
    config: { damping: 6, stiffness: 300 },
    durationInFrames: 10,
  });

  const countScale = showCount ? interpolate(countProgress, [0, 1], [0, 1]) : 0;
  const countOpacity = showCount ? interpolate(countProgress, [0, 0.5, 1], [0, 1, 1]) : 0;

  const countBgColor =
    countValue > 0 ? COLORS.emerald : countValue < 0 ? COLORS.ruby : COLORS.gold;

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      {/* Card */}
      <div
        style={{
          width: 75,
          height: 105,
          background: "linear-gradient(145deg, #ffffff 0%, #f5f5f5 100%)",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          boxShadow: `
            0 8px 20px rgba(0,0,0,0.4),
            0 0 ${countOpacity * 30}px ${countBgColor}40
          `,
          transform: `scale(${cardScale}) translateY(${cardY}px)`,
          opacity: cardOpacity,
          border: "2px solid #e0e0e0",
        }}
      >
        <div
          style={{
            fontSize: 28,
            fontWeight: 700,
            fontFamily: "JetBrains Mono, monospace",
            color: color,
          }}
        >
          {value}
        </div>
        <div style={{ fontSize: 24, color: color }}>{suit}</div>
      </div>

      {/* Count badge - POPS */}
      <div
        style={{
          background: countBgColor,
          borderRadius: 14,
          padding: "3px 12px",
          transform: `scale(${countScale})`,
          opacity: countOpacity,
          boxShadow: `0 0 20px ${countBgColor}80`,
        }}
      >
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 16,
            fontWeight: 700,
            color: COLORS.void,
          }}
        >
          {countValue > 0 ? `+${countValue}` : countValue}
        </span>
      </div>
    </div>
  );
};

export const CardCountingTeaser: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Calculate running count
  const cardDelay = 10; // frames between cards
  const cardsDealt = Math.min(Math.floor(frame / cardDelay), CARDS.length);
  const runningCount = CARDS.slice(0, cardsDealt).reduce(
    (sum, card) => sum + card.countValue,
    0
  );

  // Title SLAM
  const titleProgress = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 200 },
    durationInFrames: 15,
  });

  const titleScale = interpolate(titleProgress, [0, 1], [1.3, 1]);
  const titleOpacity = interpolate(titleProgress, [0, 0.3, 1], [0, 1, 1]);

  // Running count display
  const countDisplayDelay = 15;
  const countDisplayProgress = spring({
    frame: frame - countDisplayDelay,
    fps,
    config: { damping: 10, stiffness: 150 },
    durationInFrames: 15,
  });

  const countDisplayScale = interpolate(countDisplayProgress, [0, 1], [0.5, 1]);
  const countDisplayOpacity = interpolate(countDisplayProgress, [0, 1], [0, 1]);

  const countColor =
    runningCount > 0
      ? COLORS.emerald
      : runningCount < 0
      ? COLORS.ruby
      : COLORS.gold;

  // Background pulse synced with cards
  const bgPulse = interpolate(
    Math.sin((frame / fps) * Math.PI * 4),
    [-1, 1],
    [0.08, 0.2]
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: COLORS.void,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Pulsing background */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 1200,
          height: 800,
          background: `radial-gradient(ellipse at center, ${COLORS.gold}30 0%, transparent 60%)`,
          opacity: bgPulse,
        }}
      />

      {/* Title */}
      <div
        style={{
          marginBottom: 30,
          transform: `scale(${titleScale})`,
          opacity: titleOpacity,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 42,
            fontWeight: 700,
            color: COLORS.textPrimary,
          }}
        >
          The <span style={{ color: COLORS.gold }}>Hi-Lo</span> System
        </div>
      </div>

      {/* Cards row */}
      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 30,
        }}
      >
        {CARDS.map((card, index) => (
          <PunchyCard
            key={index}
            value={card.value}
            suit={card.suit}
            color={card.color}
            countValue={card.countValue}
            delay={index * cardDelay}
            index={index}
          />
        ))}
      </div>

      {/* Running count - BIG */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 4,
          transform: `scale(${countDisplayScale})`,
          opacity: countDisplayOpacity,
        }}
      >
        <div
          style={{
            fontFamily: "Outfit, sans-serif",
            fontSize: 16,
            color: COLORS.textSecondary,
            letterSpacing: 3,
            textTransform: "uppercase",
          }}
        >
          Running Count
        </div>
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 72,
            fontWeight: 700,
            color: countColor,
            textShadow: `0 0 50px ${countColor}80`,
            transition: "color 0.2s",
          }}
        >
          {runningCount > 0 ? `+${runningCount}` : runningCount}
        </div>
      </div>

      {/* Hi-Lo key */}
      <div
        style={{
          position: "absolute",
          bottom: 40,
          fontFamily: "Outfit, sans-serif",
          fontSize: 20,
          color: COLORS.textSecondary,
          opacity: interpolate(frame - 50, [0, 15], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <span style={{ color: COLORS.emerald }}>2-6 = +1</span>
        {" • "}
        <span style={{ color: COLORS.gold }}>7-9 = 0</span>
        {" • "}
        <span style={{ color: COLORS.ruby }}>10-A = −1</span>
      </div>
    </div>
  );
};
