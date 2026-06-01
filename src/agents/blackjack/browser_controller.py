"""
Browser Controller - Playwright/Comet automation for live blackjack play
Built with love by TradeHive
"""

import sys
import os
import asyncio
import random
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from termcolor import cprint

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    # Create stub types for type hints when Playwright not installed
    Page = Any
    Browser = Any
    BrowserContext = Any
    async_playwright = None
    cprint("Playwright not installed. Install with: pip install playwright && playwright install", "yellow")

# Add project root to path
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)


@dataclass
class GameState:
    """Parsed game state from browser"""
    player_cards: List[str]
    player_value: int
    dealer_upcard: str
    dealer_cards: List[str]
    dealer_value: int
    current_bet: float
    can_hit: bool
    can_stand: bool
    can_double: bool
    can_split: bool
    can_surrender: bool
    is_complete: bool
    result: Optional[str]
    balance: float


class SiteAdapter:
    """
    Base adapter for blackjack sites
    Override methods for specific site implementations
    """

    def __init__(self, page: Page):
        self.page = page

    async def get_game_state(self) -> Optional[GameState]:
        """Extract current game state from page"""
        raise NotImplementedError("Override in site-specific adapter")

    async def place_bet(self, amount: float) -> bool:
        """Place a bet"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_hit(self) -> bool:
        """Click hit button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_stand(self) -> bool:
        """Click stand button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_double(self) -> bool:
        """Click double button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_split(self) -> bool:
        """Click split button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_surrender(self) -> bool:
        """Click surrender button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def click_deal(self) -> bool:
        """Click deal/new hand button"""
        raise NotImplementedError("Override in site-specific adapter")

    async def wait_for_turn(self, timeout: float = 30) -> bool:
        """Wait for player's turn"""
        raise NotImplementedError("Override in site-specific adapter")


class GenericAdapter(SiteAdapter):
    """
    Generic adapter that tries common selectors
    Works with many standard blackjack sites
    """

    # Common button selectors to try
    HIT_SELECTORS = [
        'button:has-text("Hit")', 'button:has-text("HIT")',
        '#hit-button', '.hit-btn', '[data-action="hit"]',
        'button.hit', '.action-hit'
    ]

    STAND_SELECTORS = [
        'button:has-text("Stand")', 'button:has-text("STAND")',
        '#stand-button', '.stand-btn', '[data-action="stand"]',
        'button.stand', '.action-stand'
    ]

    DOUBLE_SELECTORS = [
        'button:has-text("Double")', 'button:has-text("DOUBLE")',
        '#double-button', '.double-btn', '[data-action="double"]',
        'button.double', '.action-double'
    ]

    SPLIT_SELECTORS = [
        'button:has-text("Split")', 'button:has-text("SPLIT")',
        '#split-button', '.split-btn', '[data-action="split"]',
        'button.split', '.action-split'
    ]

    DEAL_SELECTORS = [
        'button:has-text("Deal")', 'button:has-text("DEAL")',
        'button:has-text("New Hand")', 'button:has-text("Play")',
        '#deal-button', '.deal-btn', '[data-action="deal"]'
    ]

    async def _try_click(self, selectors: List[str]) -> bool:
        """Try clicking first available selector"""
        for selector in selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    await self._human_click(element)
                    return True
            except:
                continue
        return False

    async def _human_click(self, element) -> None:
        """Click with human-like behavior"""
        # Random delay before click
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Get element bounds
        box = await element.bounding_box()
        if box:
            # Click at random point within element
            x = box['x'] + random.uniform(5, box['width'] - 5)
            y = box['y'] + random.uniform(5, box['height'] - 5)
            await self.page.mouse.click(x, y)
        else:
            await element.click()

        # Random delay after click
        await asyncio.sleep(random.uniform(0.2, 0.5))

    async def click_hit(self) -> bool:
        return await self._try_click(self.HIT_SELECTORS)

    async def click_stand(self) -> bool:
        return await self._try_click(self.STAND_SELECTORS)

    async def click_double(self) -> bool:
        return await self._try_click(self.DOUBLE_SELECTORS)

    async def click_split(self) -> bool:
        return await self._try_click(self.SPLIT_SELECTORS)

    async def click_deal(self) -> bool:
        return await self._try_click(self.DEAL_SELECTORS)

    async def get_game_state(self) -> Optional[GameState]:
        """Try to extract game state - override for specific sites"""
        # This is a placeholder - real implementation needs site-specific logic
        cprint("Generic adapter: game state extraction not implemented", "yellow")
        return None


class BrowserController:
    """
    Browser automation controller for live blackjack play

    Features:
    - Anti-detection measures
    - Human-like interactions
    - Site-specific adapters
    - Screenshot capture for debugging
    """

    def __init__(self, headless: bool = False):
        """
        Initialize browser controller

        Args:
            headless: Run browser in headless mode
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright not installed. Run: pip install playwright && playwright install")

        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.adapter: Optional[SiteAdapter] = None

        # Screenshot directory
        self.screenshot_dir = Path(project_root) / "src" / "data" / "blackjack_agent" / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize browser with anti-detection measures"""
        cprint("Initializing browser...", "cyan")

        self.playwright = await async_playwright().start()

        # Launch with anti-detection args
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )

        # Create context with realistic viewport and user agent
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York'
        )

        # Add anti-detection scripts
        await self.context.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        self.page = await self.context.new_page()

        # Set default timeout
        self.page.set_default_timeout(30000)

        cprint("Browser initialized with anti-detection", "green")

    async def navigate(self, url: str) -> None:
        """Navigate to a URL"""
        if not self.page:
            raise RuntimeError("Browser not initialized")

        cprint(f"Navigating to: {url}", "cyan")
        await self.page.goto(url, wait_until='networkidle')

        # Random delay after navigation
        await asyncio.sleep(random.uniform(1, 2))

    async def set_adapter(self, adapter_class: type = GenericAdapter) -> None:
        """Set the site adapter"""
        if not self.page:
            raise RuntimeError("Browser not initialized")

        self.adapter = adapter_class(self.page)
        cprint(f"Adapter set: {adapter_class.__name__}", "green")

    async def take_screenshot(self, name: str = None) -> Path:
        """Take a screenshot for debugging"""
        if not self.page:
            raise RuntimeError("Browser not initialized")

        if not name:
            name = f"screenshot_{int(time.time())}"

        path = self.screenshot_dir / f"{name}.png"
        await self.page.screenshot(path=str(path))
        cprint(f"Screenshot saved: {path}", "cyan")
        return path

    async def execute_action(self, action: str) -> bool:
        """
        Execute a blackjack action

        Args:
            action: Action code (H, S, D, P, R)

        Returns:
            True if action was executed successfully
        """
        if not self.adapter:
            raise RuntimeError("No adapter set")

        action = action.upper()

        if action == 'H':
            success = await self.adapter.click_hit()
        elif action == 'S':
            success = await self.adapter.click_stand()
        elif action == 'D':
            success = await self.adapter.click_double()
        elif action == 'P':
            success = await self.adapter.click_split()
        elif action == 'R':
            # Surrender often not available, try stand instead
            success = await self.adapter.click_stand()
        else:
            cprint(f"Unknown action: {action}", "red")
            return False

        if success:
            cprint(f"Executed: {action}", "green")
        else:
            cprint(f"Failed to execute: {action}", "red")

        return success

    async def get_game_state(self) -> Optional[GameState]:
        """Get current game state from page"""
        if not self.adapter:
            raise RuntimeError("No adapter set")

        return await self.adapter.get_game_state()

    async def place_bet(self, amount: float) -> bool:
        """Place a bet"""
        if not self.adapter:
            raise RuntimeError("No adapter set")

        return await self.adapter.place_bet(amount)

    async def start_new_hand(self) -> bool:
        """Start a new hand"""
        if not self.adapter:
            raise RuntimeError("No adapter set")

        return await self.adapter.click_deal()

    async def human_delay(self, min_sec: float = 0.5, max_sec: float = 1.5) -> None:
        """Add human-like delay"""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def scroll_randomly(self) -> None:
        """Scroll page randomly to appear human"""
        if not self.page:
            return

        scroll_y = random.randint(-100, 100)
        await self.page.evaluate(f"window.scrollBy(0, {scroll_y})")

    async def move_mouse_randomly(self) -> None:
        """Move mouse randomly to appear human"""
        if not self.page:
            return

        x = random.randint(100, 1800)
        y = random.randint(100, 900)
        await self.page.mouse.move(x, y)

    async def close(self) -> None:
        """Close browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        cprint("Browser closed", "yellow")

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class CometAdapter(SiteAdapter):
    """
    Adapter for Perplexity Comet browser
    Comet is an AI-powered browser that can help with automation

    Comet's key advantage: Built-in vision AI that can analyze screenshots
    and understand game state without custom OCR/CV models.

    Usage:
        1. Navigate to blackjack site
        2. Comet takes screenshot
        3. Comet's AI reads cards, buttons, game state
        4. Agent makes decision
        5. Comet clicks the action
    """

    # Vision prompt for extracting blackjack game state
    GAME_STATE_PROMPT = """
    Analyze this blackjack game screenshot and extract:

    1. PLAYER CARDS: List each card (e.g., "10", "K", "A", "5")
    2. DEALER VISIBLE CARD: The dealer's face-up card
    3. AVAILABLE ACTIONS: Which buttons are clickable (Hit, Stand, Double, Split, Surrender)
    4. CURRENT BET: The bet amount if visible
    5. BALANCE: Player's chip balance if visible
    6. GAME STATUS: Is the hand complete? Who won?

    Respond in this exact JSON format:
    {
        "player_cards": ["card1", "card2", ...],
        "dealer_upcard": "card",
        "dealer_cards": ["card1", "card2", ...] or null if hidden,
        "can_hit": true/false,
        "can_stand": true/false,
        "can_double": true/false,
        "can_split": true/false,
        "can_surrender": true/false,
        "is_complete": true/false,
        "result": "win"/"lose"/"push"/"blackjack" or null,
        "current_bet": number or null,
        "balance": number or null
    }
    """

    CARD_READING_PROMPT = """
    Look at the blackjack table in this screenshot.
    What cards does the PLAYER have? List each card value (2-10, J, Q, K, A).
    What card is the DEALER showing face-up?
    Respond as: Player: [cards] | Dealer shows: [card]
    """

    BUTTON_DETECTION_PROMPT = """
    Find the blackjack action buttons in this screenshot.
    Which of these buttons are visible and clickable?
    - Hit
    - Stand
    - Double (or Double Down)
    - Split
    - Surrender

    Also identify their approximate screen positions if possible.
    """

    def __init__(self, page):
        super().__init__(page)
        self.last_screenshot_path = None
        self.screenshot_counter = 0

    async def capture_and_analyze(self, prompt: str) -> str:
        """
        Take screenshot and ask Comet's AI to analyze it

        Comet workflow:
        1. Take screenshot of current page
        2. Send screenshot + prompt to Comet's vision AI
        3. Get structured response

        Args:
            prompt: What to analyze in the screenshot

        Returns:
            Comet's AI response as string
        """
        # Take screenshot
        self.screenshot_counter += 1
        screenshot_path = f"/tmp/comet_blackjack_{self.screenshot_counter}.png"
        await self.page.screenshot(path=screenshot_path)
        self.last_screenshot_path = screenshot_path

        cprint(f"Screenshot captured: {screenshot_path}", "cyan")

        # In Comet browser, we can interact with the AI assistant
        # This is the key integration point - Comet has a sidebar or command interface
        # where we can ask questions about the current page/screenshot

        # Method 1: Use Comet's built-in vision command (if available)
        # await self.page.keyboard.press('Control+Shift+C')  # Example hotkey
        # await self.page.type('[comet-input]', prompt)

        # Method 2: Use Comet's API endpoint (if exposed)
        # response = await self._call_comet_api(screenshot_path, prompt)

        # Method 3: Use the Comet sidebar chat interface
        # await self._open_comet_sidebar()
        # await self._send_to_comet(prompt)

        # For now, return a placeholder - actual implementation depends on
        # how Comet exposes its vision capabilities
        cprint("Sending to Comet vision AI...", "magenta")

        return await self._invoke_comet_vision(prompt)

    async def _invoke_comet_vision(self, prompt: str) -> str:
        """
        Invoke Comet's vision AI to analyze current page

        This is where we hook into Comet's specific API/interface.
        Comet may expose this through:
        - A JavaScript API: window.comet.analyze()
        - A browser extension API
        - Keyboard shortcuts
        - A sidebar chat interface
        """
        try:
            # Try to use Comet's JavaScript API if available
            result = await self.page.evaluate("""
                async (prompt) => {
                    // Check if Comet API is available
                    if (typeof window.comet !== 'undefined' && window.comet.vision) {
                        return await window.comet.vision.analyze(prompt);
                    }
                    // Alternative: Check for Perplexity extension
                    if (typeof window.__perplexity !== 'undefined') {
                        return await window.__perplexity.analyzeScreen(prompt);
                    }
                    return null;
                }
            """, prompt)

            if result:
                return result

            # Fallback: Manual OCR-style detection using common patterns
            cprint("Comet API not detected, using fallback detection", "yellow")
            return await self._fallback_detection()

        except Exception as e:
            cprint(f"Comet vision error: {e}", "red")
            return ""

    async def _fallback_detection(self) -> str:
        """
        Fallback card detection using DOM inspection
        Works when Comet's vision API isn't available
        """
        # Try to find cards in the DOM
        card_selectors = [
            '.card-value', '.card', '[data-card]', '.playing-card',
            '.hand .card', '.player-card', '.dealer-card'
        ]

        player_cards = []
        dealer_cards = []

        for selector in card_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for el in elements:
                    text = await el.inner_text()
                    if text:
                        # Determine if player or dealer based on parent
                        parent_text = await el.evaluate('el => el.closest(".player, .dealer, [class*=player], [class*=dealer]")?.className || ""')
                        if 'dealer' in parent_text.lower():
                            dealer_cards.append(text.strip())
                        else:
                            player_cards.append(text.strip())
            except:
                continue

        return f"Player: {player_cards} | Dealer: {dealer_cards}"

    async def get_game_state(self) -> Optional[GameState]:
        """
        Use Comet's vision AI to extract complete game state
        """
        cprint("Comet: Analyzing game state with vision AI...", "cyan")

        try:
            # Get vision analysis
            response = await self.capture_and_analyze(self.GAME_STATE_PROMPT)

            if not response:
                return None

            # Parse JSON response
            import json
            try:
                # Try to extract JSON from response
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    data = json.loads(response[json_start:json_end])
                else:
                    cprint("Could not parse game state JSON", "yellow")
                    return None
            except json.JSONDecodeError:
                cprint(f"JSON parse error: {response[:100]}", "yellow")
                return None

            # Calculate hand values
            player_value = self._calculate_hand_value(data.get('player_cards', []))
            dealer_value = self._calculate_hand_value(data.get('dealer_cards', [])) if data.get('dealer_cards') else 0

            return GameState(
                player_cards=data.get('player_cards', []),
                player_value=player_value,
                dealer_upcard=data.get('dealer_upcard', ''),
                dealer_cards=data.get('dealer_cards'),
                dealer_value=dealer_value,
                current_bet=data.get('current_bet', 0) or 0,
                can_hit=data.get('can_hit', False),
                can_stand=data.get('can_stand', False),
                can_double=data.get('can_double', False),
                can_split=data.get('can_split', False),
                can_surrender=data.get('can_surrender', False),
                is_complete=data.get('is_complete', False),
                result=data.get('result'),
                balance=data.get('balance', 0) or 0
            )

        except Exception as e:
            cprint(f"Game state extraction error: {e}", "red")
            return None

    def _calculate_hand_value(self, cards: List[str]) -> int:
        """Calculate blackjack hand value from card list"""
        value = 0
        aces = 0

        for card in cards:
            card = card.upper().strip()
            if card in ['J', 'Q', 'K']:
                value += 10
            elif card == 'A':
                aces += 1
                value += 11
            elif card.isdigit():
                value += int(card)
            elif card == '10':
                value += 10

        # Adjust for aces
        while value > 21 and aces:
            value -= 10
            aces -= 1

        return value

    async def read_cards_quick(self) -> Tuple[List[str], str]:
        """
        Quick card reading - just get player cards and dealer upcard

        Returns:
            (player_cards, dealer_upcard)
        """
        response = await self.capture_and_analyze(self.CARD_READING_PROMPT)

        # Parse simple format: "Player: [A, 10] | Dealer shows: 9"
        player_cards = []
        dealer_upcard = ""

        if "Player:" in response and "|" in response:
            parts = response.split("|")
            player_part = parts[0].split("Player:")[-1].strip()
            dealer_part = parts[1].split(":")[-1].strip() if len(parts) > 1 else ""

            # Extract cards from brackets or comma-separated
            import re
            player_cards = re.findall(r'[2-9]|10|[JQKA]', player_part.upper())
            dealer_match = re.findall(r'[2-9]|10|[JQKA]', dealer_part.upper())
            dealer_upcard = dealer_match[0] if dealer_match else ""

        return player_cards, dealer_upcard

    async def find_and_click_action(self, action: str) -> bool:
        """
        Ask Comet to find and click the action button

        Args:
            action: Action code (H, S, D, P, R)

        Returns:
            True if click was successful
        """
        action_names = {
            'H': 'Hit',
            'S': 'Stand',
            'D': 'Double',
            'P': 'Split',
            'R': 'Surrender'
        }

        action_name = action_names.get(action.upper(), action)

        # Ask Comet to find and click the button
        click_prompt = f"""
        Find the "{action_name}" button on this blackjack table and click it.
        The button might say "{action_name}", "{action_name.upper()}", or have an icon.
        Click the button and confirm the click was successful.
        """

        try:
            # Use Comet's click capability
            result = await self.page.evaluate("""
                async (actionName) => {
                    // Try Comet's action API
                    if (typeof window.comet !== 'undefined' && window.comet.click) {
                        return await window.comet.click(actionName + " button");
                    }
                    return false;
                }
            """, action_name)

            if result:
                cprint(f"Comet clicked: {action_name}", "green")
                return True

            # Fallback to standard button detection
            return await self._try_click(self._get_selectors_for_action(action))

        except Exception as e:
            cprint(f"Click error: {e}", "red")
            return False

    def _get_selectors_for_action(self, action: str) -> List[str]:
        """Get CSS selectors for an action"""
        selectors = {
            'H': GenericAdapter.HIT_SELECTORS,
            'S': GenericAdapter.STAND_SELECTORS,
            'D': GenericAdapter.DOUBLE_SELECTORS,
            'P': GenericAdapter.SPLIT_SELECTORS,
            'R': ['button:has-text("Surrender")', '#surrender-button']
        }
        return selectors.get(action.upper(), [])

    async def click_hit(self) -> bool:
        return await self.find_and_click_action('H')

    async def click_stand(self) -> bool:
        return await self.find_and_click_action('S')

    async def click_double(self) -> bool:
        return await self.find_and_click_action('D')

    async def click_split(self) -> bool:
        return await self.find_and_click_action('P')

    async def click_surrender(self) -> bool:
        return await self.find_and_click_action('R')

    async def wait_for_cards(self, timeout: float = 10) -> bool:
        """
        Wait for cards to appear on screen using vision

        Returns:
            True if cards detected
        """
        import time
        start = time.time()

        while time.time() - start < timeout:
            player_cards, dealer_upcard = await self.read_cards_quick()

            if player_cards and dealer_upcard:
                cprint(f"Cards detected: Player {player_cards} vs Dealer {dealer_upcard}", "green")
                return True

            await asyncio.sleep(0.5)

        cprint("Timeout waiting for cards", "yellow")
        return False


# Utility functions for running async code
def run_browser_session(url: str, headless: bool = False):
    """Run a browser session synchronously"""
    async def _session():
        async with BrowserController(headless=headless) as browser:
            await browser.navigate(url)
            await browser.set_adapter(GenericAdapter)

            # Take initial screenshot
            await browser.take_screenshot("initial")

            # Keep browser open for manual interaction
            cprint("\nBrowser ready. Press Ctrl+C to close.", "cyan")
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass

    asyncio.run(_session())


# Standalone test
if __name__ == "__main__":
    cprint("\n=== Browser Controller Test ===\n", "cyan", attrs=['bold'])

    if not PLAYWRIGHT_AVAILABLE:
        cprint("Playwright not installed!", "red")
        cprint("Install with: pip install playwright && playwright install chromium", "yellow")
        sys.exit(1)

    # Test with a simple page
    test_url = "https://www.google.com"

    cprint(f"Testing browser automation with: {test_url}", "white")
    cprint("This will open a browser window...\n", "yellow")

    try:
        run_browser_session(test_url, headless=False)
    except Exception as e:
        cprint(f"Error: {e}", "red")
        import traceback
        traceback.print_exc()
