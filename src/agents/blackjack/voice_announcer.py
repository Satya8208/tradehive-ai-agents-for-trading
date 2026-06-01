"""
Voice Announcer - Text-to-speech for blackjack decisions and results
Built with love by TradeHive
"""

import threading
from typing import Optional, Literal
from termcolor import cprint

# Try to import pyttsx3, gracefully handle if not installed
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    cprint("pyttsx3 not installed. Voice disabled. Install with: pip install pyttsx3", "yellow")


class VoiceAnnouncer:
    """
    Text-to-speech announcer for blackjack agent

    Announces:
    - Actions (Hit, Stand, Double, Split, Surrender)
    - Results (Win, Lose, Push, Blackjack)
    - Card counts
    - Betting recommendations
    - Warnings and alerts
    """

    # Action announcements
    ACTION_PHRASES = {
        'H': 'Hit',
        'S': 'Stand',
        'D': 'Double down',
        'P': 'Split',
        'R': 'Surrender'
    }

    # Result announcements
    RESULT_PHRASES = {
        'win': 'Winner!',
        'lose': 'Dealer wins',
        'push': 'Push',
        'blackjack': 'Blackjack!',
        'bust': 'Bust',
        'surrender': 'Surrendered'
    }

    def __init__(self, enabled: bool = True, rate: int = 175, volume: float = 1.0):
        """
        Initialize voice announcer

        Args:
            enabled: Whether voice is enabled
            rate: Speech rate (words per minute, default 175)
            volume: Volume level (0.0 to 1.0)
        """
        self.enabled = enabled and PYTTSX3_AVAILABLE
        self.rate = rate
        self.volume = volume
        self.engine = None
        self._lock = threading.Lock()

        if self.enabled:
            self._init_engine()

    def _init_engine(self) -> None:
        """Initialize the TTS engine"""
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', self.rate)
            self.engine.setProperty('volume', self.volume)

            # Try to select a voice (prefer female for variety)
            voices = self.engine.getProperty('voices')
            if len(voices) > 1:
                # Usually index 1 is a female voice on most systems
                self.engine.setProperty('voice', voices[1].id)

            cprint("Voice announcer initialized", "green")

        except Exception as e:
            cprint(f"Voice initialization failed: {e}", "red")
            self.enabled = False

    def _speak_sync(self, text: str) -> None:
        """Speak text synchronously"""
        if not self.enabled or not self.engine:
            return

        with self._lock:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                cprint(f"Speech error: {e}", "red")

    def speak(self, text: str, block: bool = False) -> None:
        """
        Speak text

        Args:
            text: Text to speak
            block: If True, wait for speech to complete
        """
        if not self.enabled:
            return

        if block:
            self._speak_sync(text)
        else:
            thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
            thread.start()

    def announce_action(self, action: str, hand_total: int = None) -> None:
        """
        Announce player action

        Args:
            action: Action code (H, S, D, P, R)
            hand_total: Optional hand total for context
        """
        phrase = self.ACTION_PHRASES.get(action.upper(), action)

        if hand_total and action.upper() in ['H', 'S']:
            self.speak(f"{phrase} on {hand_total}")
        else:
            self.speak(phrase)

    def announce_result(self, result: str, amount: float = None) -> None:
        """
        Announce hand result

        Args:
            result: Result type (win, lose, push, blackjack, bust, surrender)
            amount: Optional P&L amount
        """
        phrase = self.RESULT_PHRASES.get(result.lower(), result)

        if amount is not None:
            if amount > 0:
                self.speak(f"{phrase} Plus {abs(amount):.0f}")
            elif amount < 0:
                self.speak(f"{phrase} Minus {abs(amount):.0f}")
            else:
                self.speak(phrase)
        else:
            self.speak(phrase)

    def announce_count(self, true_count: float, running_count: float = None) -> None:
        """
        Announce current count

        Args:
            true_count: True count
            running_count: Optional running count
        """
        tc_str = f"{true_count:+.1f}".replace('+', 'plus ').replace('-', 'minus ')
        self.speak(f"True count {tc_str}")

    def announce_bet(self, amount: float, reason: str = None) -> None:
        """
        Announce betting recommendation

        Args:
            amount: Bet amount
            reason: Optional reason (e.g., "high count")
        """
        if reason:
            self.speak(f"Bet {amount:.0f}, {reason}")
        else:
            self.speak(f"Bet {amount:.0f}")

    def announce_bankroll(self, bankroll: float, change: float = None) -> None:
        """
        Announce bankroll status

        Args:
            bankroll: Current bankroll
            change: Optional session P&L
        """
        if change is not None:
            direction = "up" if change >= 0 else "down"
            self.speak(f"Bankroll {bankroll:.0f}, {direction} {abs(change):.0f}")
        else:
            self.speak(f"Bankroll {bankroll:.0f}")

    def announce_cards(self, player_cards: list, dealer_upcard: str) -> None:
        """
        Announce dealt cards

        Args:
            player_cards: Player's cards
            dealer_upcard: Dealer's visible card
        """
        player_str = " and ".join(str(c) for c in player_cards)
        self.speak(f"You have {player_str}. Dealer shows {dealer_upcard}")

    def announce_warning(self, message: str) -> None:
        """Announce a warning message"""
        self.speak(f"Warning: {message}")

    def announce_shuffle(self) -> None:
        """Announce shoe shuffle"""
        self.speak("Shuffle")

    def announce_insurance(self, take: bool, reason: str = None) -> None:
        """
        Announce insurance decision

        Args:
            take: Whether to take insurance
            reason: Optional reason
        """
        if take:
            self.speak("Take insurance" + (f", {reason}" if reason else ""))
        else:
            self.speak("No insurance")

    def announce_deviation(self, from_action: str, to_action: str, true_count: float) -> None:
        """
        Announce count-based deviation

        Args:
            from_action: Basic strategy action
            to_action: Deviation action
            true_count: Current true count
        """
        from_phrase = self.ACTION_PHRASES.get(from_action, from_action)
        to_phrase = self.ACTION_PHRASES.get(to_action, to_action)
        self.speak(f"Deviation: {to_phrase} instead of {from_phrase}, count is {true_count:+.0f}")

    def announce_session_start(self, bankroll: float) -> None:
        """Announce session start"""
        self.speak(f"Session started. Bankroll {bankroll:.0f}")

    def announce_session_end(self, pnl: float, hands_played: int) -> None:
        """Announce session end"""
        direction = "profit" if pnl >= 0 else "loss"
        self.speak(f"Session ended. {hands_played} hands. {direction} of {abs(pnl):.0f}")

    def set_rate(self, rate: int) -> None:
        """Change speech rate"""
        self.rate = rate
        if self.engine:
            self.engine.setProperty('rate', rate)

    def set_volume(self, volume: float) -> None:
        """Change volume (0.0 to 1.0)"""
        self.volume = max(0.0, min(1.0, volume))
        if self.engine:
            self.engine.setProperty('volume', self.volume)

    def toggle(self) -> bool:
        """Toggle voice on/off"""
        if PYTTSX3_AVAILABLE:
            self.enabled = not self.enabled
            if self.enabled and not self.engine:
                self._init_engine()
        return self.enabled

    def test(self) -> None:
        """Test the voice announcer"""
        if not self.enabled:
            cprint("Voice is disabled", "yellow")
            return

        cprint("Testing voice...", "cyan")
        self.speak("Blackjack God activated. Ready to count cards.", block=True)


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Voice Announcer Test ===\n", "cyan", attrs=['bold'])

    voice = VoiceAnnouncer(enabled=True)

    if voice.enabled:
        # Test various announcements
        voice.test()

        import time
        time.sleep(0.5)

        voice.announce_cards(['10', '6'], '9')
        time.sleep(1.5)

        voice.announce_action('H', 16)
        time.sleep(1)

        voice.announce_result('win', 20)
        time.sleep(1)

        voice.announce_count(3.5)
        time.sleep(1)

        voice.announce_bet(80, "positive count")
        time.sleep(1)

        voice.announce_deviation('H', 'S', 4)
        time.sleep(1.5)

        voice.announce_session_end(150, 25)

        cprint("\nVoice test complete!", "green")
    else:
        cprint("Voice announcer not available", "yellow")
        cprint("Install with: pip install pyttsx3", "cyan")
