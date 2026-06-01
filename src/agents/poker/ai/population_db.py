"""
📊 Population Tendencies Database
Default opponent profiles by stake level and player pool
Built with love by TradeHive
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class StakeLevel(Enum):
    """Stake level categories"""
    MICRO = "micro"          # 2NL - 10NL
    LOW = "low"              # 25NL - 50NL
    MID = "mid"              # 100NL - 200NL
    HIGH = "high"            # 500NL+
    LIVE_LOW = "live_low"    # 1/2, 1/3
    LIVE_MID = "live_mid"    # 2/5, 5/10
    LIVE_HIGH = "live_high"  # 10/20+


class PlayerPool(Enum):
    """Player pool categories"""
    ONLINE_REG = "online_reg"
    ONLINE_REC = "online_rec"
    LIVE_REC = "live_rec"
    LIVE_REG = "live_reg"
    TOURNAMENT = "tournament"


@dataclass
class PopulationStats:
    """Population-level statistics"""
    vpip: float
    pfr: float
    three_bet: float
    fold_to_3bet: float
    cbet_flop: float
    cbet_turn: float
    fold_to_cbet: float
    aggression_factor: float
    wtsd: float
    won_at_sd: float

    # Advanced stats
    squeeze: float = 5.0
    four_bet: float = 2.0
    fold_to_4bet: float = 55.0
    probe_bet: float = 30.0
    donk_bet: float = 5.0
    check_raise_flop: float = 8.0
    limp_freq: float = 5.0

    def is_too_loose(self) -> bool:
        return self.vpip > 30

    def is_too_tight(self) -> bool:
        return self.vpip < 18

    def is_passive(self) -> bool:
        return self.aggression_factor < 1.5

    def is_aggressive(self) -> bool:
        return self.aggression_factor > 3.0


@dataclass
class PopulationProfile:
    """Complete population profile"""
    stake: StakeLevel
    pool: PlayerPool
    stats: PopulationStats
    description: str
    common_leaks: List[str] = field(default_factory=list)
    exploits: List[str] = field(default_factory=list)


class PopulationDatabase:
    """
    📊 Population Tendencies Database

    Pre-built profiles for different player pools:
    - Online micro stakes (2NL-10NL)
    - Online regular stakes (25NL+)
    - Live casino low stakes (1/2, 1/3)
    - Live casino mid stakes (2/5, 5/10)
    - Tournament players

    Use for:
    - Default assumptions when no reads available
    - Baseline for opponent modeling
    - Adjustment recommendations
    """

    # Population profiles
    PROFILES = {
        # === ONLINE MICRO STAKES ===
        (StakeLevel.MICRO, PlayerPool.ONLINE_REC): PopulationProfile(
            stake=StakeLevel.MICRO,
            pool=PlayerPool.ONLINE_REC,
            stats=PopulationStats(
                vpip=45, pfr=12, three_bet=3, fold_to_3bet=70,
                cbet_flop=65, cbet_turn=40, fold_to_cbet=55,
                aggression_factor=1.2, wtsd=32, won_at_sd=48,
                limp_freq=25, donk_bet=15
            ),
            description="Micro stakes recreational: Loose-passive, limps often, calls too much",
            common_leaks=["Limps too much", "Calls too much postflop", "Overvalues top pair",
                         "Doesn't fold to 3-bets enough"],
            exploits=["Value bet thin", "Size up with value", "Don't bluff rivers",
                     "Iso-raise limpers wide", "3-bet for value vs their calls"]
        ),

        (StakeLevel.MICRO, PlayerPool.ONLINE_REG): PopulationProfile(
            stake=StakeLevel.MICRO,
            pool=PlayerPool.ONLINE_REG,
            stats=PopulationStats(
                vpip=23, pfr=19, three_bet=7, fold_to_3bet=58,
                cbet_flop=68, cbet_turn=55, fold_to_cbet=45,
                aggression_factor=2.5, wtsd=26, won_at_sd=52
            ),
            description="Micro stakes reg: Tighter, more aggressive, follows charts",
            common_leaks=["Over-folds to 4-bets", "Predictable sizing", "Gives up too easily OOP"],
            exploits=["4-bet light vs their 3-bets", "Attack when they check twice",
                     "Float in position", "Probe their missed c-bets"]
        ),

        # === ONLINE LOW-MID STAKES ===
        (StakeLevel.LOW, PlayerPool.ONLINE_REG): PopulationProfile(
            stake=StakeLevel.LOW,
            pool=PlayerPool.ONLINE_REG,
            stats=PopulationStats(
                vpip=22, pfr=18, three_bet=8, fold_to_3bet=55,
                cbet_flop=65, cbet_turn=50, fold_to_cbet=42,
                aggression_factor=2.8, wtsd=25, won_at_sd=54
            ),
            description="Low stakes reg: Solid fundamentals, balanced",
            common_leaks=["Slightly over-cbets", "Missing thin value rivers"],
            exploits=["Pick spots carefully", "Exploit predictable bet sizing tells"]
        ),

        (StakeLevel.MID, PlayerPool.ONLINE_REG): PopulationProfile(
            stake=StakeLevel.MID,
            pool=PlayerPool.ONLINE_REG,
            stats=PopulationStats(
                vpip=23, pfr=20, three_bet=9, fold_to_3bet=52,
                cbet_flop=58, cbet_turn=48, fold_to_cbet=40,
                aggression_factor=3.0, wtsd=24, won_at_sd=55
            ),
            description="Mid stakes reg: GTO-aware, tough, adapts",
            common_leaks=["Hard to exploit", "May over-adjust"],
            exploits=["Play straightforward", "Unexploitable lines profit long-term"]
        ),

        # === LIVE LOW STAKES ===
        (StakeLevel.LIVE_LOW, PlayerPool.LIVE_REC): PopulationProfile(
            stake=StakeLevel.LIVE_LOW,
            pool=PlayerPool.LIVE_REC,
            stats=PopulationStats(
                vpip=42, pfr=8, three_bet=2, fold_to_3bet=75,
                cbet_flop=55, cbet_turn=35, fold_to_cbet=60,
                aggression_factor=0.8, wtsd=35, won_at_sd=45,
                limp_freq=35, donk_bet=20
            ),
            description="Live 1/2 rec: Limps often, plays fit-or-fold, passive postflop",
            common_leaks=["Limps almost everything", "Calls too much preflop",
                         "Folds to aggression postflop", "Never bluffs river"],
            exploits=["Iso-raise 5-6x vs limpers", "Value bet 3 streets with TPTK+",
                     "Don't bluff - they call", "Size up for value", "Fold to their river raises"]
        ),

        (StakeLevel.LIVE_LOW, PlayerPool.LIVE_REG): PopulationProfile(
            stake=StakeLevel.LIVE_LOW,
            pool=PlayerPool.LIVE_REG,
            stats=PopulationStats(
                vpip=25, pfr=18, three_bet=5, fold_to_3bet=60,
                cbet_flop=70, cbet_turn=50, fold_to_cbet=48,
                aggression_factor=2.2, wtsd=27, won_at_sd=52
            ),
            description="Live 1/2 reg: Solid but exploitable, over-values position",
            common_leaks=["Cbets too often on wet boards", "Overvalues suited hands"],
            exploits=["Check-raise wet flops", "Attack their blind defense"]
        ),

        # === LIVE MID STAKES ===
        (StakeLevel.LIVE_MID, PlayerPool.LIVE_REC): PopulationProfile(
            stake=StakeLevel.LIVE_MID,
            pool=PlayerPool.LIVE_REC,
            stats=PopulationStats(
                vpip=35, pfr=12, three_bet=4, fold_to_3bet=65,
                cbet_flop=60, cbet_turn=40, fold_to_cbet=50,
                aggression_factor=1.5, wtsd=30, won_at_sd=48,
                limp_freq=20
            ),
            description="Live 2/5 rec: Wealthy recreational, gambles, has ego",
            common_leaks=["Doesn't fold overpairs", "Calls too light", "Tilts easily"],
            exploits=["Value bet relentlessly", "Don't bluff", "Let them bluff into you",
                     "Pot control vs aggression - they have it"]
        ),

        # === TOURNAMENT ===
        (StakeLevel.LOW, PlayerPool.TOURNAMENT): PopulationProfile(
            stake=StakeLevel.LOW,
            pool=PlayerPool.TOURNAMENT,
            stats=PopulationStats(
                vpip=22, pfr=16, three_bet=6, fold_to_3bet=62,
                cbet_flop=60, cbet_turn=45, fold_to_cbet=50,
                aggression_factor=2.0, wtsd=26, won_at_sd=50
            ),
            description="Low stakes MTT: ICM-aware, tightens on bubble",
            common_leaks=["Over-tightens on bubble", "Open-shoves too tight"],
            exploits=["Attack bubble tightness", "Steal blinds relentlessly",
                     "Apply ICM pressure when covered"]
        ),
    }

    # Default assumptions when no specific profile
    DEFAULT_ONLINE = PopulationStats(
        vpip=25, pfr=18, three_bet=7, fold_to_3bet=58,
        cbet_flop=65, cbet_turn=50, fold_to_cbet=45,
        aggression_factor=2.2, wtsd=27, won_at_sd=51
    )

    DEFAULT_LIVE = PopulationStats(
        vpip=35, pfr=12, three_bet=4, fold_to_3bet=65,
        cbet_flop=60, cbet_turn=40, fold_to_cbet=52,
        aggression_factor=1.5, wtsd=30, won_at_sd=48
    )

    def __init__(self):
        self.lookups = 0

    def get_profile(self, stake: StakeLevel, pool: PlayerPool) -> Optional[PopulationProfile]:
        """Get population profile for stake/pool combination"""
        self.lookups += 1
        key = (stake, pool)
        return self.PROFILES.get(key)

    def get_default_stats(self, is_live: bool = False) -> PopulationStats:
        """Get default stats for unknown opponent"""
        self.lookups += 1
        return self.DEFAULT_LIVE if is_live else self.DEFAULT_ONLINE

    def get_adjustments(self, stake: StakeLevel, pool: PlayerPool) -> Dict[str, str]:
        """Get strategic adjustments for a population"""
        profile = self.get_profile(stake, pool)
        if not profile:
            return {"general": "Play solid, observe and adjust"}

        adjustments = {}
        stats = profile.stats

        # Preflop adjustments
        if stats.vpip > 35:
            adjustments["preflop"] = "Iso-raise wide vs limpers. 3-bet for value. Don't bluff preflop."
        elif stats.vpip < 20:
            adjustments["preflop"] = "Widen stealing range. 3-bet light vs their opens."

        # Cbet adjustments
        if stats.fold_to_cbet > 55:
            adjustments["cbet"] = "Cbet wide on dry boards. They fold too much."
        elif stats.fold_to_cbet < 40:
            adjustments["cbet"] = "Cbet only for value. Check strong hands to induce."

        # Postflop adjustments
        if stats.aggression_factor < 1.5:
            adjustments["postflop"] = "Value bet thin. Bluff rivers - they won't raise."
        elif stats.aggression_factor > 3.0:
            adjustments["postflop"] = "Let them bluff. Call down light. Check-call strong hands."

        # River adjustments
        if stats.wtsd < 25:
            adjustments["river"] = "Bluff rivers with blockers. They fold too often."
        elif stats.wtsd > 32:
            adjustments["river"] = "Value bet thin on rivers. Don't bluff."

        return adjustments

    def suggest_opening_adjustments(self, stake: StakeLevel, pool: PlayerPool) -> Dict[str, float]:
        """Suggest opening range adjustments vs population"""
        profile = self.get_profile(stake, pool)
        if not profile:
            return {}

        stats = profile.stats
        adjustments = {}

        # If population is passive, we can open wider
        if stats.three_bet < 5:
            adjustments["open_wider"] = 1.2  # Open 20% more hands
        elif stats.three_bet > 10:
            adjustments["open_tighter"] = 0.9  # Open 10% less

        # If they fold to 3-bets a lot, we 3-bet more
        if stats.fold_to_3bet > 65:
            adjustments["3bet_light"] = 1.5  # 50% more 3-bets
        elif stats.fold_to_3bet < 50:
            adjustments["3bet_value"] = 0.7  # Only for value

        return adjustments

    def get_all_profiles(self) -> List[PopulationProfile]:
        """Get all available profiles"""
        return list(self.PROFILES.values())

    def print_profile(self, stake: StakeLevel, pool: PlayerPool):
        """Print detailed profile"""
        profile = self.get_profile(stake, pool)
        if not profile:
            print(f"No profile for {stake.value}/{pool.value}")
            return

        print(f"\n{'='*50}")
        print(f"📊 POPULATION: {stake.value.upper()} {pool.value.upper()}")
        print(f"{'='*50}")
        print(f"Description: {profile.description}")
        print(f"\nStats:")
        print(f"  VPIP/PFR: {profile.stats.vpip}/{profile.stats.pfr}")
        print(f"  3-bet:    {profile.stats.three_bet}%")
        print(f"  Cbet:     {profile.stats.cbet_flop}% flop, {profile.stats.cbet_turn}% turn")
        print(f"  WTSD:     {profile.stats.wtsd}%")
        print(f"  AF:       {profile.stats.aggression_factor}")

        print(f"\nCommon Leaks:")
        for leak in profile.common_leaks:
            print(f"  ⚠️ {leak}")

        print(f"\nExploits:")
        for exploit in profile.exploits:
            print(f"  ✅ {exploit}")


# === Quick Test ===
if __name__ == "__main__":
    from termcolor import cprint

    cprint("\n📊 Testing Population Database...\n", "cyan", attrs=["bold"])

    db = PopulationDatabase()

    # Print a profile
    db.print_profile(StakeLevel.LIVE_LOW, PlayerPool.LIVE_REC)

    # Get adjustments
    cprint("\n🎯 Strategic Adjustments:", "yellow")
    adjustments = db.get_adjustments(StakeLevel.LIVE_LOW, PlayerPool.LIVE_REC)
    for category, adj in adjustments.items():
        print(f"  {category}: {adj}")

    cprint("\n✅ Database ready!", "green")
