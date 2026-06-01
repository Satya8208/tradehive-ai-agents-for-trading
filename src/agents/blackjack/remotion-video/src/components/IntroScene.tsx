import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

// Color palette from Blackjack God branding
const COLORS = {
  void: "#050505",
  surface: "#0f0f0f",
  gold: "#d4a853",
  goldDim: "#a68a3f",
  goldBright: "#f0d48a",
  emerald: "#2dd881",
  ruby: "#e85454",
  textPrimary: "#f5f5f0",
  textSecondary: "#999",
};

const CardSuit: React.FC<{
  suit: string;
  delay: number;
  x: number;
  y: number;
  size: number;
}> = ({ suit, delay, x, y, size }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const floatProgress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
    durationInFrames: 60,
  });

  const opacity = interpolate(floatProgress, [0, 1], [0, 0.08], {
    extrapolateRight: "clamp",
  });

  const translateY = interpolate(
    (frame + delay * 10) % 120,
    [0, 60, 120],
    [0, -20, 0]
  );

  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        fontSize: size,
        color: COLORS.gold,
        opacity,
        transform: `translateY(${translateY}px)`,
        fontFamily: "serif",
      }}
    >
      {suit}
    </div>
  );
};

export const IntroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo icon animation - smooth entrance
  const logoIconScale = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 100 },
    durationInFrames: 25,
  });

  const logoIconRotation = interpolate(
    spring({
      frame,
      fps,
      config: { damping: 15, stiffness: 80 },
      durationInFrames: 25,
    }),
    [0, 1],
    [180, 0]
  );

  // Logo text animation - staggered entrance
  const logoTextOpacity = interpolate(frame, [10, 25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  const logoTextX = interpolate(frame, [10, 25], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  // Headline animation - appears after logo settles
  const headlineProgress = spring({
    frame: frame - 18,
    fps,
    config: { damping: 15, stiffness: 100 },
    durationInFrames: 22,
  });

  const headlineOpacity = interpolate(headlineProgress, [0, 1], [0, 1]);
  const headlineY = interpolate(headlineProgress, [0, 1], [30, 0]);

  // Subtitle animation - follows headline
  const subtitleProgress = spring({
    frame: frame - 35,
    fps,
    config: { damping: 15, stiffness: 100 },
    durationInFrames: 20,
  });

  const subtitleOpacity = interpolate(subtitleProgress, [0, 1], [0, 1]);
  const subtitleY = interpolate(subtitleProgress, [0, 1], [20, 0]);

  // Gold glow pulsing - smooth pulse
  const glowOpacity = interpolate(
    Math.sin((frame / fps) * Math.PI * 2.5),
    [-1, 1],
    [0.12, 0.3]
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: COLORS.void,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Ambient glow */}
      <div
        style={{
          position: "absolute",
          top: "-20%",
          left: "-10%",
          width: 800,
          height: 800,
          borderRadius: "50%",
          background: COLORS.gold,
          filter: "blur(150px)",
          opacity: glowOpacity,
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "-30%",
          right: "-10%",
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${COLORS.goldDim}, #1a3d24)`,
          filter: "blur(120px)",
          opacity: glowOpacity * 0.8,
        }}
      />

      {/* Floating card suits */}
      <CardSuit suit="♠" delay={0} x={8} y={15} size={80} />
      <CardSuit suit="♥" delay={5} x={85} y={20} size={90} />
      <CardSuit suit="♦" delay={10} x={10} y={70} size={70} />
      <CardSuit suit="♣" delay={15} x={88} y={75} size={85} />
      <CardSuit suit="♠" delay={8} x={5} y={45} size={60} />
      <CardSuit suit="♥" delay={12} x={92} y={50} size={75} />

      {/* Logo container */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 24,
          marginBottom: 60,
        }}
      >
        {/* Logo icon */}
        <div
          style={{
            width: 100,
            height: 100,
            background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
            borderRadius: 24,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 56,
            transform: `scale(${logoIconScale}) rotate(${logoIconRotation}deg)`,
            boxShadow: `0 20px 60px rgba(212, 168, 83, 0.4)`,
          }}
        >
          🃏
        </div>

        {/* Logo text */}
        <div
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 48,
            fontWeight: 600,
            letterSpacing: 8,
            background: `linear-gradient(135deg, ${COLORS.goldBright} 0%, ${COLORS.gold} 50%, ${COLORS.goldDim} 100%)`,
            backgroundClip: "text",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            opacity: logoTextOpacity,
            transform: `translateX(${logoTextX}px)`,
          }}
        >
          BLACKJACK GOD
        </div>
      </div>

      {/* Main headline */}
      <h1
        style={{
          fontFamily: "Cinzel, serif",
          fontSize: 72,
          fontWeight: 700,
          color: COLORS.textPrimary,
          textAlign: "center",
          lineHeight: 1.1,
          margin: 0,
          opacity: headlineOpacity,
          transform: `translateY(${headlineY}px)`,
        }}
      >
        Beat the Casino at Blackjack
        <br />
        <span
          style={{
            background: `linear-gradient(135deg, ${COLORS.goldBright}, ${COLORS.gold})`,
            backgroundClip: "text",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          — Legally
        </span>
      </h1>

      {/* Subtitle */}
      <p
        style={{
          fontFamily: "Outfit, sans-serif",
          fontSize: 28,
          color: COLORS.textSecondary,
          marginTop: 30,
          opacity: subtitleOpacity,
          transform: `translateY(${subtitleY}px)`,
        }}
      >
        The complete ebook guide
      </p>
    </div>
  );
};
