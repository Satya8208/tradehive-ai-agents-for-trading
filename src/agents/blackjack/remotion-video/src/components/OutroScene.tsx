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
  gold: "#d4a853",
  goldDim: "#a68a3f",
  goldBright: "#f0d48a",
  emerald: "#2dd881",
  textPrimary: "#f5f5f0",
  textSecondary: "#999",
};

export const OutroScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo animation
  const logoProgress = spring({
    frame,
    fps,
    config: { damping: 12, stiffness: 80 },
    durationInFrames: 40,
  });

  const logoScale = interpolate(logoProgress, [0, 1], [0.5, 1]);
  const logoOpacity = interpolate(logoProgress, [0, 1], [0, 1]);

  // Tagline animation
  const taglineProgress = spring({
    frame: frame - 20,
    fps,
    config: { damping: 200 },
    durationInFrames: 30,
  });

  const taglineOpacity = interpolate(taglineProgress, [0, 1], [0, 1]);
  const taglineY = interpolate(taglineProgress, [0, 1], [30, 0]);

  // CTA animation
  const ctaProgress = spring({
    frame: frame - 40,
    fps,
    config: { damping: 15 },
    durationInFrames: 30,
  });

  const ctaScale = interpolate(ctaProgress, [0, 1], [0.8, 1]);
  const ctaOpacity = interpolate(ctaProgress, [0, 1], [0, 1]);

  // Pulsing glow for CTA
  const ctaGlow = interpolate(
    Math.sin((frame / fps) * Math.PI * 4),
    [-1, 1],
    [0.4, 0.8]
  );

  // Background glow
  const glowOpacity = interpolate(
    Math.sin((frame / fps) * Math.PI * 2),
    [-1, 1],
    [0.15, 0.3]
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
      {/* Central glow */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 800,
          height: 800,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${COLORS.gold}40 0%, transparent 70%)`,
          opacity: glowOpacity,
        }}
      />

      {/* Logo */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          marginBottom: 40,
          transform: `scale(${logoScale})`,
          opacity: logoOpacity,
        }}
      >
        <div
          style={{
            width: 80,
            height: 80,
            background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
            borderRadius: 20,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 44,
            boxShadow: `0 15px 50px rgba(212, 168, 83, 0.5)`,
          }}
        >
          🃏
        </div>
        <span
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 40,
            fontWeight: 600,
            letterSpacing: 6,
            background: `linear-gradient(135deg, ${COLORS.goldBright} 0%, ${COLORS.gold} 50%, ${COLORS.goldDim} 100%)`,
            backgroundClip: "text",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          BLACKJACK GOD
        </span>
      </div>

      {/* Tagline */}
      <div
        style={{
          textAlign: "center",
          marginBottom: 50,
          opacity: taglineOpacity,
          transform: `translateY(${taglineY}px)`,
        }}
      >
        <p
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 48,
            fontWeight: 600,
            color: COLORS.textPrimary,
            margin: 0,
            marginBottom: 16,
          }}
        >
          Start Winning Today
        </p>
        <p
          style={{
            fontFamily: "Outfit, sans-serif",
            fontSize: 24,
            color: COLORS.textSecondary,
            margin: 0,
          }}
        >
          Join thousands of advantage players
        </p>
      </div>

      {/* CTA Button */}
      <div
        style={{
          transform: `scale(${ctaScale})`,
          opacity: ctaOpacity,
        }}
      >
        <div
          style={{
            background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
            borderRadius: 16,
            padding: "24px 60px",
            boxShadow: `0 0 60px rgba(212, 168, 83, ${ctaGlow})`,
          }}
        >
          <span
            style={{
              fontFamily: "Outfit, sans-serif",
              fontSize: 24,
              fontWeight: 700,
              color: COLORS.void,
            }}
          >
            Get Started — From $27
          </span>
        </div>
      </div>

      {/* Website URL */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 20,
          color: COLORS.gold,
          letterSpacing: 2,
          opacity: interpolate(frame - 60, [0, 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        blackjackgod.ai
      </div>
    </div>
  );
};
