import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
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

const StatCard: React.FC<{
  label: string;
  value: string;
  delay: number;
  color?: string;
}> = ({ label, value, delay, color = COLORS.gold }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 15, stiffness: 100 },
    durationInFrames: 25,
  });

  const scale = interpolate(entrance, [0, 1], [0.8, 1]);
  const opacity = interpolate(entrance, [0, 1], [0, 1]);
  const y = interpolate(entrance, [0, 1], [30, 0]);

  // Animate value counting up
  const numericValue = parseFloat(value.replace(/[^0-9.]/g, ""));
  const isPercentage = value.includes("%");
  const prefix = value.includes("+") ? "+" : "";
  const suffix = isPercentage ? "%" : "";

  const countProgress = interpolate(frame - delay, [0, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const displayValue =
    numericValue > 0
      ? `${prefix}${(numericValue * countProgress).toFixed(isPercentage ? 1 : 0)}${suffix}`
      : value;

  return (
    <div
      style={{
        background: `linear-gradient(135deg, ${COLORS.surfaceElevated} 0%, ${COLORS.surface} 100%)`,
        border: `1px solid rgba(255, 255, 255, 0.05)`,
        borderRadius: 20,
        padding: "32px 40px",
        textAlign: "center",
        transform: `scale(${scale}) translateY(${y}px)`,
        opacity,
        minWidth: 200,
      }}
    >
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 48,
          fontWeight: 600,
          color: color,
          marginBottom: 12,
          textShadow: `0 0 30px ${color}40`,
        }}
      >
        {displayValue}
      </div>
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 16,
          color: COLORS.textSecondary,
          textTransform: "uppercase",
          letterSpacing: 2,
        }}
      >
        {label}
      </div>
    </div>
  );
};

const FeatureItem: React.FC<{
  text: string;
  delay: number;
}> = ({ text, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const x = interpolate(entrance, [0, 1], [-30, 0]);
  const opacity = interpolate(entrance, [0, 1], [0, 1]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        transform: `translateX(${x}px)`,
        opacity,
        marginBottom: 16,
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          background: `rgba(45, 216, 129, 0.15)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: COLORS.emerald,
          fontSize: 16,
          fontWeight: 700,
        }}
      >
        ✓
      </div>
      <span
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 20,
          color: COLORS.textPrimary,
        }}
      >
        {text}
      </span>
    </div>
  );
};

export const StatsScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Title animation
  const titleProgress = spring({
    frame,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1]);
  const titleY = interpolate(titleProgress, [0, 1], [-30, 0]);

  // Glow animation
  const glowOpacity = interpolate(
    Math.sin((frame / fps) * Math.PI * 2),
    [-1, 1],
    [0.1, 0.2]
  );

  const features = [
    "3 counting systems (Hi-Lo, Omega II, Wong Halves)",
    "Perfect basic strategy tables",
    "True count conversion mastery",
    "Betting spread optimization",
    "Casino countermeasure avoidance",
    "AI-powered practice partner",
  ];

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
      {/* Background glow */}
      <div
        style={{
          position: "absolute",
          top: "20%",
          left: "50%",
          transform: "translateX(-50%)",
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${COLORS.gold}30 0%, transparent 70%)`,
          opacity: glowOpacity,
        }}
      />

      {/* Section header */}
      <div
        style={{
          textAlign: "center",
          marginBottom: 50,
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
            marginBottom: 12,
          }}
        >
          What You Get
        </div>
        <h2
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 48,
            fontWeight: 600,
            color: COLORS.textPrimary,
            margin: 0,
          }}
        >
          Complete Blackjack Mastery
        </h2>
      </div>

      {/* Stats row */}
      <div
        style={{
          display: "flex",
          gap: 30,
          marginBottom: 60,
          justifyContent: "center",
          flexWrap: "wrap",
        }}
      >
        <StatCard
          label="Minutes to Read"
          value="90"
          delay={10}
          color={COLORS.gold}
        />
        <StatCard
          label="Chapters"
          value="8"
          delay={20}
          color={COLORS.goldBright}
        />
        <StatCard
          label="Edge Over Casino"
          value="+1.5%"
          delay={30}
          color={COLORS.emerald}
        />
        <StatCard
          label="Success Rate"
          value="94%"
          delay={40}
          color={COLORS.emerald}
        />
      </div>

      {/* Features list - two columns */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "0 60px",
          maxWidth: 900,
        }}
      >
        {features.map((feature, index) => (
          <FeatureItem
            key={index}
            text={feature}
            delay={50 + index * 10}
          />
        ))}
      </div>

      {/* Bottom tagline */}
      <div
        style={{
          position: "absolute",
          bottom: 60,
          fontFamily: "Cinzel, serif",
          fontSize: 24,
          color: COLORS.gold,
          opacity: interpolate(frame - 120, [0, 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        From zero to advantage player in weeks, not years
      </div>
    </div>
  );
};
