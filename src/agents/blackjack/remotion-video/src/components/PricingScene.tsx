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

const PricingCard: React.FC<{
  tier: string;
  price: string;
  features: string[];
  isFeatured?: boolean;
  delay: number;
}> = ({ tier, price, features, isFeatured = false, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 15, stiffness: 80 },
    durationInFrames: 30,
  });

  const scale = interpolate(entrance, [0, 1], [0.8, isFeatured ? 1.05 : 1]);
  const opacity = interpolate(entrance, [0, 1], [0, 1]);
  const y = interpolate(entrance, [0, 1], [50, 0]);

  // Featured card glow pulse
  const glowIntensity = isFeatured
    ? interpolate(
        Math.sin((frame / fps) * Math.PI * 3),
        [-1, 1],
        [0.3, 0.6]
      )
    : 0;

  return (
    <div
      style={{
        background: `linear-gradient(180deg, ${COLORS.surfaceElevated} 0%, ${COLORS.surface} 100%)`,
        border: isFeatured
          ? `2px solid ${COLORS.gold}`
          : `1px solid rgba(255, 255, 255, 0.08)`,
        borderRadius: 24,
        padding: "40px 32px",
        position: "relative",
        transform: `scale(${scale}) translateY(${y}px)`,
        opacity,
        boxShadow: isFeatured
          ? `0 0 60px rgba(212, 168, 83, ${glowIntensity})`
          : "none",
        minWidth: 280,
      }}
    >
      {/* Featured badge */}
      {isFeatured && (
        <div
          style={{
            position: "absolute",
            top: -14,
            left: "50%",
            transform: "translateX(-50%)",
            background: `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`,
            color: COLORS.void,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 2,
            padding: "8px 20px",
            borderRadius: 20,
            fontFamily: "Outfit, sans-serif",
          }}
        >
          BEST VALUE
        </div>
      )}

      {/* Tier name */}
      <div
        style={{
          fontFamily: "Cinzel, serif",
          fontSize: 22,
          fontWeight: 600,
          color: COLORS.textPrimary,
          marginBottom: 8,
          textAlign: "center",
        }}
      >
        {tier}
      </div>

      {/* Price */}
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 48,
          fontWeight: 600,
          color: COLORS.gold,
          marginBottom: 24,
          textAlign: "center",
        }}
      >
        {price}
      </div>

      {/* Features list */}
      <div style={{ marginBottom: 24 }}>
        {features.map((feature, index) => (
          <div
            key={index}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "12px 0",
              borderBottom:
                index < features.length - 1
                  ? "1px solid rgba(255, 255, 255, 0.05)"
                  : "none",
            }}
          >
            <span style={{ color: COLORS.emerald, fontSize: 16 }}>✓</span>
            <span
              style={{
                fontFamily: "Outfit, sans-serif",
                fontSize: 15,
                color: COLORS.textSecondary,
              }}
            >
              {feature}
            </span>
          </div>
        ))}
      </div>

      {/* CTA Button */}
      <div
        style={{
          background: isFeatured
            ? `linear-gradient(135deg, ${COLORS.gold} 0%, ${COLORS.goldDim} 100%)`
            : "transparent",
          border: isFeatured ? "none" : `1px solid ${COLORS.goldDim}`,
          borderRadius: 12,
          padding: 18,
          textAlign: "center",
          fontFamily: "Outfit, sans-serif",
          fontSize: 16,
          fontWeight: 600,
          color: isFeatured ? COLORS.void : COLORS.gold,
        }}
      >
        {isFeatured ? "Get Best Value" : "Get Started"}
      </div>
    </div>
  );
};

export const PricingScene: React.FC = () => {
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

  // Tagline animation
  const taglineProgress = spring({
    frame: frame - 120,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const taglineOpacity = interpolate(taglineProgress, [0, 1], [0, 1]);

  // Glow animation
  const glowOpacity = interpolate(
    Math.sin((frame / fps) * Math.PI * 2),
    [-1, 1],
    [0.1, 0.2]
  );

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: COLORS.surface,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 60,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Background gradients */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: `
            radial-gradient(ellipse at 30% 50%, rgba(212, 168, 83, 0.05) 0%, transparent 50%),
            radial-gradient(ellipse at 70% 50%, rgba(45, 216, 129, 0.03) 0%, transparent 50%)
          `,
          opacity: glowOpacity * 5,
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
          Choose Your Path
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
          Investment Options
        </h2>
      </div>

      {/* Pricing cards */}
      <div
        style={{
          display: "flex",
          gap: 24,
          justifyContent: "center",
          alignItems: "stretch",
          position: "relative",
          zIndex: 1,
        }}
      >
        <PricingCard
          tier="E-Book Only"
          price="$27"
          features={[
            "Complete 8-chapter guide (PDF)",
            "Printable strategy cards",
            "Instant download",
          ]}
          delay={20}
        />

        <PricingCard
          tier="E-Book + AI Tool"
          price="$47"
          features={[
            "Everything in E-Book Only",
            "30-day Blackjack God AI",
            "Training drills & simulation",
            "Progress tracking dashboard",
          ]}
          isFeatured={true}
          delay={35}
        />

        <PricingCard
          tier="Complete Bundle"
          price="$97"
          features={[
            "Everything in E-Book + AI",
            "Lifetime AI access",
            "All future updates",
            "Priority support",
          ]}
          delay={50}
        />
      </div>

      {/* Final tagline */}
      <div
        style={{
          position: "absolute",
          bottom: 50,
          textAlign: "center",
          opacity: taglineOpacity,
        }}
      >
        <p
          style={{
            fontFamily: "Outfit, sans-serif",
            fontSize: 18,
            color: COLORS.textSecondary,
            marginBottom: 8,
          }}
        >
          The casino's edge is a math problem.
        </p>
        <p
          style={{
            fontFamily: "Cinzel, serif",
            fontSize: 28,
            fontWeight: 600,
            color: COLORS.textPrimary,
            margin: 0,
          }}
        >
          This book is{" "}
          <span style={{ color: COLORS.gold }}>the solution.</span>
        </p>
      </div>
    </div>
  );
};
