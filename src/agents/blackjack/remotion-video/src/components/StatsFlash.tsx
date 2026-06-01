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
  textPrimary: "#f5f5f0",
  textSecondary: "#999",
};

const StatItem: React.FC<{
  value: string;
  label: string;
  delay: number;
  color?: string;
}> = ({ value, label, delay, color = COLORS.goldBright }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // SLAM animation
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 8, stiffness: 250, mass: 0.8 },
    durationInFrames: 12,
  });

  const scale = interpolate(progress, [0, 1], [2, 1]);
  const opacity = interpolate(progress, [0, 0.3, 1], [0, 1, 1]);
  const y = interpolate(progress, [0, 1], [-30, 0]);

  // Glow pulse after appearing
  const glowIntensity = frame > delay + 10
    ? interpolate(
        Math.sin(((frame - delay - 10) / fps) * Math.PI * 4),
        [-1, 1],
        [0.3, 0.8]
      )
    : 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
        transform: `scale(${scale}) translateY(${y}px)`,
        opacity,
      }}
    >
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 72,
          fontWeight: 700,
          color: color,
          textShadow: `0 0 ${40 * glowIntensity}px ${color}`,
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 22,
          color: COLORS.textSecondary,
          textTransform: "uppercase",
          letterSpacing: 3,
        }}
      >
        {label}
      </div>
    </div>
  );
};

export const StatsFlash: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Background pulse
  const bgPulse = interpolate(
    Math.sin((frame / fps) * Math.PI * 3),
    [-1, 1],
    [0.1, 0.25]
  );

  // Title
  const titleProgress = spring({
    frame,
    fps,
    config: { damping: 10, stiffness: 200 },
    durationInFrames: 15,
  });

  const titleOpacity = interpolate(titleProgress, [0, 1], [0, 1]);
  const titleScale = interpolate(titleProgress, [0, 1], [1.2, 1]);

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
      {/* Background glow */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 1000,
          height: 600,
          background: `radial-gradient(ellipse at center, ${COLORS.gold}40 0%, transparent 60%)`,
          opacity: bgPulse,
        }}
      />

      {/* Title */}
      <div
        style={{
          marginBottom: 60,
          transform: `scale(${titleScale})`,
          opacity: titleOpacity,
        }}
      >
        <div
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 36,
            fontWeight: 600,
            color: COLORS.textPrimary,
          }}
        >
          Everything You Need
        </div>
      </div>

      {/* Stats row */}
      <div
        style={{
          display: "flex",
          gap: 100,
          marginBottom: 50,
        }}
      >
        <StatItem value="90" label="Minutes to Read" delay={8} />
        <StatItem value="8" label="Chapters" delay={16} />
        <StatItem value="1.5%" label="Edge Over Casino" delay={24} color={COLORS.emerald} />
      </div>

      {/* Bottom tagline */}
      <div
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 28,
          color: COLORS.textSecondary,
          opacity: interpolate(frame - 35, [0, 12], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        From <span style={{ color: COLORS.textPrimary }}>zero</span> to{" "}
        <span style={{ color: COLORS.gold }}>advantage player</span>
      </div>
    </div>
  );
};
