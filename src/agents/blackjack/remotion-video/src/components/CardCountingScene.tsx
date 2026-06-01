import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Sequence,
} from "remotion";

const COLORS = {
  void: "#050505",
  surface: "#0f0f0f",
  surfaceElevated: "#1a1a1a",
  gold: "#d4a853",
  goldDim: "#a68a3f",
  goldBright: "#f0d48a",
  emerald: "#2dd881",
  ruby: "#e85454",
  textPrimary: "#f5f5f0",
  textSecondary: "#999",
};

// Card data for the counting demonstration
// Note: Black suits (♠, ♣) use "#1a1a1a" for visibility on white card backgrounds
const CARDS = [
  { value: "A", suit: "♠", countValue: -1, color: "#1a1a1a" },
  { value: "K", suit: "♥", countValue: -1, color: COLORS.ruby },
  { value: "5", suit: "♦", countValue: 1, color: COLORS.ruby },
  { value: "3", suit: "♣", countValue: 1, color: "#1a1a1a" },
  { value: "7", suit: "♠", countValue: 0, color: "#1a1a1a" },
  { value: "10", suit: "♥", countValue: -1, color: COLORS.ruby },
  { value: "2", suit: "♦", countValue: 1, color: COLORS.ruby },
  { value: "6", suit: "♣", countValue: 1, color: "#1a1a1a" },
];

const PlayingCard: React.FC<{
  value: string;
  suit: string;
  color: string;
  countValue: number;
  delay: number;
  index: number;
}> = ({ value, suit, color, countValue, delay, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardEntrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 15, stiffness: 100 },
    durationInFrames: 20,
  });

  const flipProgress = interpolate(
    spring({
      frame: frame - delay,
      fps,
      config: { damping: 20 },
      durationInFrames: 15,
    }),
    [0, 1],
    [90, 0]
  );

  const cardScale = interpolate(cardEntrance, [0, 1], [0.5, 1]);
  const cardOpacity = interpolate(cardEntrance, [0, 0.3, 1], [0, 1, 1]);

  // Count indicator animation
  const showCount = frame > delay + 15;
  const countOpacity = showCount
    ? interpolate(frame - delay - 15, [0, 10], [0, 1], {
        extrapolateRight: "clamp",
      })
    : 0;

  const countBgColor =
    countValue > 0 ? COLORS.emerald : countValue < 0 ? COLORS.ruby : COLORS.gold;

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
      }}
    >
      {/* Card */}
      <div
        style={{
          width: 100,
          height: 140,
          background: "white",
          borderRadius: 12,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
          transform: `scale(${cardScale}) rotateY(${flipProgress}deg)`,
          opacity: cardOpacity,
          transformStyle: "preserve-3d",
        }}
      >
        <div
          style={{
            fontSize: 36,
            fontWeight: 700,
            fontFamily: "JetBrains Mono, monospace",
            color: color,
          }}
        >
          {value}
        </div>
        <div
          style={{
            fontSize: 32,
            color: color,
          }}
        >
          {suit}
        </div>
      </div>

      {/* Count indicator */}
      <div
        style={{
          background: countBgColor,
          borderRadius: 20,
          padding: "6px 16px",
          opacity: countOpacity,
          transform: `scale(${countOpacity})`,
        }}
      >
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 18,
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

const CountDisplay: React.FC<{ runningCount: number; delay: number }> = ({
  runningCount,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const displayProgress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const scale = interpolate(displayProgress, [0, 1], [0.8, 1]);
  const opacity = interpolate(displayProgress, [0, 1], [0, 1]);

  const countColor =
    runningCount > 0
      ? COLORS.emerald
      : runningCount < 0
      ? COLORS.ruby
      : COLORS.gold;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        transform: `scale(${scale})`,
        opacity,
      }}
    >
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 18,
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
          textShadow: `0 0 40px ${countColor}60`,
        }}
      >
        {runningCount > 0 ? `+${runningCount}` : runningCount}
      </div>
    </div>
  );
};

export const CardCountingScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Calculate which cards have been dealt and running count
  const cardsDealt = Math.min(Math.floor(frame / 25), CARDS.length);
  const runningCount = CARDS.slice(0, cardsDealt).reduce(
    (sum, card) => sum + card.countValue,
    0
  );

  // Title animation
  const titleProgress = spring({
    frame,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1]);
  const titleY = interpolate(titleProgress, [0, 1], [-30, 0]);

  // Subtitle fade in
  const subtitleProgress = spring({
    frame: frame - 10,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const subtitleOpacity = interpolate(subtitleProgress, [0, 1], [0, 1]);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: COLORS.void,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: 60,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Background gradient */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: `radial-gradient(ellipse at 50% 30%, rgba(212, 168, 83, 0.08) 0%, transparent 60%)`,
        }}
      />

      {/* Section title */}
      <div
        style={{
          marginBottom: 20,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
        }}
      >
        <div
          style={{
            fontFamily: "Outfit, sans-serif",
            fontSize: 14,
            color: COLORS.gold,
            letterSpacing: 4,
            textTransform: "uppercase",
            textAlign: "center",
            marginBottom: 12,
          }}
        >
          Card Counting Made Simple
        </div>
        <h2
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 48,
            fontWeight: 600,
            color: COLORS.textPrimary,
            textAlign: "center",
            margin: 0,
          }}
        >
          The Hi-Lo System
        </h2>
      </div>

      {/* Subtitle explanation */}
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 20,
          color: COLORS.textSecondary,
          textAlign: "center",
          maxWidth: 700,
          marginBottom: 50,
          opacity: subtitleOpacity,
        }}
      >
        2-6 = <span style={{ color: COLORS.emerald }}>+1</span> | 7-9 ={" "}
        <span style={{ color: COLORS.gold }}>0</span> | 10-A ={" "}
        <span style={{ color: COLORS.ruby }}>-1</span>
      </div>

      {/* Cards display */}
      <div
        style={{
          display: "flex",
          gap: 20,
          marginBottom: 60,
          justifyContent: "center",
          flexWrap: "wrap",
          maxWidth: 1000,
        }}
      >
        {CARDS.map((card, index) => (
          <PlayingCard
            key={index}
            value={card.value}
            suit={card.suit}
            color={card.color}
            countValue={card.countValue}
            delay={index * 25}
            index={index}
          />
        ))}
      </div>

      {/* Running count display */}
      <CountDisplay runningCount={runningCount} delay={cardsDealt * 25 + 10} />

      {/* Bottom hint */}
      {cardsDealt >= CARDS.length && (
        <Sequence from={CARDS.length * 25 + 30}>
          <div
            style={{
              position: "absolute",
              bottom: 60,
              fontFamily: "Outfit, sans-serif",
              fontSize: 22,
              color: COLORS.gold,
              opacity: interpolate(
                frame - (CARDS.length * 25 + 30),
                [0, 20],
                [0, 1],
                { extrapolateRight: "clamp" }
              ),
            }}
          >
            Higher count = More high cards left = Your advantage
          </div>
        </Sequence>
      )}
    </div>
  );
};
