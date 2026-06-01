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
  goldDim: "#a68a3f",
  goldBright: "#f0d48a",
  textPrimary: "#f5f5f0",
};

export const CTAScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo slam
  const logoProgress = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 180 },
    durationInFrames: 15,
  });

  const logoScale = interpolate(logoProgress, [0, 1], [1.5, 1]);
  const logoOpacity = interpolate(logoProgress, [0, 0.3, 1], [0, 1, 1]);

  // "Get the Ebook" text
  const textProgress = spring({
    frame: frame - 10,
    fps,
    config: { damping: 10, stiffness: 150 },
    durationInFrames: 18,
  });

  const textScale = interpolate(textProgress, [0, 1], [1.3, 1]);
  const textOpacity = interpolate(textProgress, [0, 1], [0, 1]);

  // Price button SLAM
  const priceProgress = spring({
    frame: frame - 20,
    fps,
    config: { damping: 6, stiffness: 200 },
    durationInFrames: 15,
  });

  const priceScale = interpolate(priceProgress, [0, 1], [0.5, 1]);
  const priceOpacity = interpolate(priceProgress, [0, 0.5, 1], [0, 1, 1]);

  // Pulsing glow for CTA button
  const ctaGlow = interpolate(
    Math.sin((frame / fps) * Math.PI * 4),
    [-1, 1],
    [0.6, 1]
  );

  // Website URL
  const urlOpacity = interpolate(frame - 35, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Background pulse
  const bgPulse = interpolate(
    Math.sin((frame / fps) * Math.PI * 3),
    [-1, 1],
    [0.2, 0.45]
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
      {/* Intense center glow */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 900,
          height: 900,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${COLORS.gold}60 0%, transparent 50%)`,
          opacity: bgPulse,
        }}
      />

      {/* Secondary glow rings */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 600,
          height: 600,
          borderRadius: "50%",
          border: `2px solid ${COLORS.gold}30`,
          opacity: bgPulse * 0.5,
        }}
      />

      {/* Small logo at top */}
      <div
        style={{
          position: "absolute",
          top: 50,
          display: "flex",
          alignItems: "center",
          gap: 14,
          transform: `scale(${logoScale})`,
          opacity: logoOpacity,
        }}
      >
        <div
          style={{
            width: 45,
            height: 45,
            background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
            borderRadius: 10,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 24,
            boxShadow: `0 8px 25px rgba(212, 168, 83, 0.5)`,
          }}
        >
          🃏
        </div>
        <span
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 24,
            fontWeight: 600,
            letterSpacing: 3,
            background: `linear-gradient(135deg, ${COLORS.goldBright} 0%, ${COLORS.gold} 100%)`,
            backgroundClip: "text",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          BLACKJACK GOD
        </span>
      </div>

      {/* Main CTA content */}
      <div style={{ textAlign: "center" }}>
        {/* "Get the Ebook" */}
        <div
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 64,
            fontWeight: 700,
            color: COLORS.textPrimary,
            marginBottom: 30,
            transform: `scale(${textScale})`,
            opacity: textOpacity,
          }}
        >
          Get the Ebook
        </div>

        {/* Price button */}
        <div
          style={{
            transform: `scale(${priceScale})`,
            opacity: priceOpacity,
            display: "inline-block",
          }}
        >
          <div
            style={{
              background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
              borderRadius: 20,
              padding: "28px 100px",
              boxShadow: `
                0 0 ${80 * ctaGlow}px rgba(212, 168, 83, ${ctaGlow * 0.7}),
                0 20px 50px rgba(0,0,0,0.4)
              `,
            }}
          >
            <span
              style={{
                fontFamily: "Cinzel, serif",
                fontSize: 56,
                fontWeight: 700,
                color: COLORS.void,
              }}
            >
              $27
            </span>
          </div>
        </div>
      </div>

      {/* Website URL */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 26,
          color: COLORS.gold,
          letterSpacing: 4,
          opacity: urlOpacity,
          textShadow: `0 0 20px ${COLORS.gold}60`,
        }}
      >
        blackjackgod.ai
      </div>
    </div>
  );
};
