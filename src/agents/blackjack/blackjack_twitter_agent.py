"""
🎰 Blackjack God Twitter Agent - Dedicated Content Engine
Built with love by TradeHive

A strategic Twitter content engine focused on blackjack, card counting,
and advantage play content. Generates threads, tweets, and engagement content
for building an audience around blackjack expertise.
"""

import os
import sys
import json
import random
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from termcolor import cprint
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.model_factory import model_factory

# Configuration
AI_MODEL = os.getenv('BLACKJACK_TWITTER_MODEL', 'claude-sonnet-4-6')  # Sonnet 4.6 for Twitter content
TEMPERATURE = 0.85  # Balanced creativity for social media content

# Data paths
DATA_DIR = PROJECT_ROOT / "src" / "data" / "blackjack_twitter"
TWEETS_DIR = DATA_DIR / "generated_tweets"
THREADS_DIR = DATA_DIR / "generated_threads"
CONTENT_CALENDAR_DIR = DATA_DIR / "content_calendar"

# Ensure directories exist
for dir_path in [TWEETS_DIR, THREADS_DIR, CONTENT_CALENDAR_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ============================================
# PROMPTS
# ============================================

BRAND_PERSONA = """
You are "Blackjack God" - an anonymous expert who profits consistently from blackjack
using mathematics and card counting. You've been banned from 12 casinos.

VOICE:
- CONTRARIAN: Challenge every gambling myth with cold math
- SYSTEMATIC: Every piece of advice comes with exact steps to implement
- DIRECT: Short sentences. No fluff. Say it plain.
- DATA-BACKED: Numbers and probabilities, not opinions

SIGNATURE STYLE:
- Start hooks with "How to..." or "The [X] that [surprising claim]"
- Use ">" for step breakdowns
- One sentence per line (creates rhythm)
- End with a takeaway they can use TODAY

NEVER:
- Start any sentence with "I"
- Use hashtags or more than 1 emoji
- Say "feeling lucky", "hot streak", or gambling hype
- Give advice without specific numbers or steps
- Write walls of text - white space is your friend

LANGUAGE RULES:
- "Use" not "utilize"
- "Help" not "facilitate"
- "Get better" not "optimize performance"
- If a 14-year-old can't understand it, simplify it

THE BOOKMARK TEST:
Before outputting, ask: "Would someone bookmark this to reference later?"
If no, add specific steps or a system they can implement.
"""

TWEET_GENERATION_PROMPT = """
{persona}

Generate {count} standalone tweets about: {topic}

EVERY TWEET MUST:
1. Pass the bookmark test - would you save this to reference later?
2. Give them something to DO, not just something to KNOW
3. Be under 280 characters

HOOK FORMULA (pick ONE per tweet):
- "How to [specific outcome] in [timeframe/steps]"
- "The [X] mistake costing you [specific amount/outcome]"
- "[Controversial claim]. Here's the math:"

FORMAT:
- Hook = first line, punchy, under 10 words ideal
- If multiple points, use:
  > point one
  > point two
- One idea per tweet

EXAMPLES OF GOOD vs BAD:

BAD: "Card counting is a skill that takes practice to master"
(vague, no action, everyone knows this)

GOOD: "How to count a deck in under 30 seconds:
> Start with Hi-Lo (+1 low, -1 high)
> Practice pairs: 3+K = 0, 5+2 = +2
> Speed drill: full deck daily for 2 weeks"
(specific system, steps, timeframe)

Return each tweet on a new line, numbered.
"""

THREAD_GENERATION_PROMPT = """
{persona}

Write a {length}-tweet thread about: {topic}
Angle: {thesis}

STRUCTURE:

1/ HOOK
- Controversial claim OR surprising stat
- Must make them NEED to read the next tweet
- Under 200 chars

2/ STAKES
- Why this matters to their wallet
- Specific: "costs the average player $X per hour"

3-{length_minus_2}/ THE SYSTEM
- Step-by-step breakdown
- Each tweet = one actionable step
- Use ">" for sub-steps
- Include specific numbers/percentages

{length_minus_1}/ PROOF
- Real scenario or calculation
- "Here's what this looks like with a $25 bet:"

{length}/ TAKEAWAY + SOFT CTA
- One sentence summary they can screenshot
- "Save this thread" or "Follow for more systems"
- NOT "like if you agree" (desperate)

ENGAGEMENT STRATEGY (pick one):
A) CONTROVERSIAL: Take a stance people will argue with
   "Hi-Lo beats Omega II for 99% of players. Fight me."

B) COLLABORATIVE: Invite their experience
   "This is my betting spread. Curious what others use:"

FORMAT RULES:
- One sentence per line
- White space between ideas
- No tweet starts with "I"
- Max 1 emoji in entire thread
- Each tweet under 280 chars

Output format: "1/ [tweet]" etc.
"""

ENGAGEMENT_PROMPT = """
{persona}

Someone tweeted: "{tweet}"

Generate 3 reply options to engage with this tweet. One in each mode:

1. EDUCATIONAL: Add value by sharing a relevant card counting or probability insight
2. CONTRARIAN: Respectfully challenge their premise with math/data
3. WIT: Clever observation or unexpected angle

Each reply must:
- Be under 280 characters
- Add value to the conversation
- NOT be self-promotional
- Showcase expertise subtly

Format:
EDUCATIONAL: [reply]
CONTRARIAN: [reply]
WIT: [reply]
"""

FACELESS_VIDEO_SCRIPT_PROMPT = """
{persona}

Create a script for a 30-60 second faceless video about: {topic}

This will be a screen recording of the Blackjack God dashboard with AI voiceover.
The visual will show card counting in action.

STRUCTURE:
- HOOK (0-5 sec): One line that makes viewers stop scrolling
- PROBLEM (5-10 sec): What most people get wrong
- SOLUTION (10-40 sec): The key insight or technique
- PROOF (40-50 sec): Quick demonstration or stat
- CTA (50-60 sec): What they should do next

Format:
[HOOK]
(visual description)
Script line

[PROBLEM]
(visual description)
Script line

... etc

Keep voiceover punchy and confident. No filler words.
"""

# Topic banks for content generation - ACTION-FOCUSED
TOPIC_BANK = {
    "counting_systems": [
        "How to count a full deck in under 30 seconds",
        "The 3-day Hi-Lo training system that actually works",
        "True count conversion: the mental math shortcut pros use",
        "Wong Halves in 5 steps (yes, the fractions are worth it)",
        "The exact count threshold where you should increase bets",
        "How to practice counting with a metronome (the pro method)",
        "The pair counting drill that cuts your training time in half",
    ],
    "strategy_systems": [
        "The 7 basic strategy rules that cover 90% of hands",
        "Soft 18: the one hand that separates pros from amateurs",
        "When to surrender (the math that saves you $50/hour)",
        "The split decision framework: 4 questions, perfect accuracy",
        "Dealer bust probabilities: the cheat sheet you need",
        "How to memorize basic strategy in one weekend",
        "The 3-second decision rule that stops costly mistakes",
    ],
    "money_systems": [
        "The Kelly Criterion bet sizing system (exact formula)",
        "How to calculate your risk of ruin before you play",
        "Betting spreads: 1-8 vs 1-12 vs 1-16 (when to use each)",
        "The $5,000 bankroll blueprint for $25 minimum tables",
        "Session management: when math says to leave the table",
        "How to size your bets based on true count (the formula)",
        "The 2% rule that protects your bankroll from ruin",
    ],
    "myth_busting": [
        "The gambler's fallacy is costing you $X per session",
        "Insurance: the worst bet on the table (here's the math)",
        "Why the third baseman can't hurt you (probability proof)",
        "Hot and cold streaks: what the data actually shows",
        "The 'card counting is illegal' myth casinos love",
        "Why 'feeling lucky' costs the average player $200/session",
        "The house edge myth that keeps 99% of players losing",
    ],
    "casino_tactics": [
        "How casinos spot counters (the 5 red flags)",
        "Cover betting: the system to stay under radar",
        "Heat management: when to color up and leave",
        "Table selection: the 3 factors that matter most",
        "The legal rights casinos don't want you to know",
        "How to wong in and out without raising suspicion",
        "The 'cover play' bet that makes you look like a tourist",
    ],
}

# Signature formatting patterns for consistent style
SIGNATURE_ELEMENTS = {
    "step_marker": ">",           # Always use > for steps
    "hook_patterns": [
        "How to {X}",
        "The {X} that {Y}",
        "{Controversial claim}. Here's why:",
    ],
    "cta_patterns": [
        "Save this for your next session.",
        "Follow for more systems.",
        "Bookmark this before you forget.",
    ],
    "proof_phrases": [
        "Here's the math:",
        "The numbers:",
        "Proof:",
    ]
}

# Simple language replacements - avoid corporate speak
SIMPLIFY_WORDS = {
    "utilize": "use",
    "facilitate": "help",
    "optimize": "improve",
    "implement": "do",
    "subsequently": "then",
    "methodology": "method",
    "leverage": "use",
    "synergy": "work together",
    "paradigm": "approach",
    "holistic": "complete",
}


class BlackjackTwitterAgent:
    """Blackjack God Twitter Growth Engine"""

    def __init__(self):
        """Initialize the agent"""
        load_dotenv()

        cprint("\n🎰 BLACKJACK GOD TWITTER ENGINE", "cyan", attrs=["bold"])
        cprint("=" * 50, "cyan")

        # Initialize AI model - determine model type from name
        try:
            model_type = "gemini"  # Default to gemini
            if "claude" in AI_MODEL.lower():
                model_type = "claude"
            elif "gpt" in AI_MODEL.lower() or "o1" in AI_MODEL.lower():
                model_type = "openai"
            elif "grok" in AI_MODEL.lower():
                model_type = "xai"
            elif "deepseek" in AI_MODEL.lower():
                model_type = "deepseek"

            self.model = model_factory.get_model(model_type, AI_MODEL)
            if self.model is None:
                raise ValueError(f"Model {AI_MODEL} not available")
            cprint(f"✅ AI Model: {AI_MODEL}", "green")
        except Exception as e:
            cprint(f"❌ Model initialization failed: {e}", "red")
            raise

        # Stats tracking
        self.generated_tweets = 0
        self.generated_threads = 0

    def _generate(self, system_prompt: str, user_content: str, temp: float = TEMPERATURE) -> str:
        """Generate response from model"""
        try:
            response = self.model.generate_response(
                system_prompt=system_prompt,
                user_content=user_content,
                max_tokens=2000,
                temperature=temp
            )
            if response:
                # Handle different response types
                if hasattr(response, 'content'):
                    return response.content.strip()
                elif isinstance(response, str):
                    return response.strip()
                else:
                    return str(response).strip()
            return ""
        except Exception as e:
            cprint(f"❌ Generation error: {e}", "red")
            return ""

    def validate_tweet(self, tweet: str) -> tuple:
        """Validate tweet against quality principles from the viral article"""
        issues = []

        # Check actionability (Principle 2: Immediately actionable)
        actionable_markers = ["how to", "step", "here's", ">", "1.", "2.", "the formula", "the system"]
        if not any(m in tweet.lower() for m in actionable_markers):
            issues.append("Not actionable - add steps or 'how to'")

        # Check for begging (Principle 3: Natural engagement)
        begging_phrases = ["like if", "retweet if", "share if", "drop a", "comment below"]
        if any(p in tweet.lower() for p in begging_phrases):
            issues.append("Remove begging language")

        # Check length
        if len(tweet) > 280:
            issues.append(f"Too long: {len(tweet)} chars")

        # Check starts with I (Principle 5: Style)
        if tweet.strip().startswith("I ") or tweet.strip().startswith("I'"):
            issues.append("Don't start with 'I'")

        # Check for hashtags
        if tweet.count('#') > 0:
            issues.append("Remove hashtags")

        # Check for excessive emojis (Unicode emoji ranges)
        emoji_count = sum(1 for c in tweet if ord(c) >= 0x1F300 and ord(c) <= 0x1FAD6)
        if emoji_count > 1:
            issues.append(f"Too many emojis: {emoji_count}")

        return (len(issues) == 0, issues)

    def simplify_text(self, text: str) -> str:
        """Replace corporate speak with simple language"""
        result = text
        for complex_word, simple_word in SIMPLIFY_WORDS.items():
            result = result.replace(complex_word, simple_word)
            result = result.replace(complex_word.capitalize(), simple_word.capitalize())
        return result

    def generate_tweets(self, topic: str = None, count: int = 5, category: str = None) -> List[str]:
        """Generate standalone tweets"""

        # Pick topic from bank if not provided
        if not topic:
            if category and category in TOPIC_BANK:
                topic = random.choice(TOPIC_BANK[category])
            else:
                category = random.choice(list(TOPIC_BANK.keys()))
                topic = random.choice(TOPIC_BANK[category])

        cprint(f"\n📝 Generating {count} tweets about: {topic}", "yellow")

        prompt = TWEET_GENERATION_PROMPT.format(
            persona=BRAND_PERSONA,
            topic=topic,
            count=count
        )

        response = self._generate(BRAND_PERSONA, prompt)

        # Parse tweets - collect multi-line content for each numbered tweet
        tweets = []
        current_tweet_lines = []
        lines = response.split('\n')

        for line in lines:
            stripped = line.strip()
            # Check if this is a new numbered tweet (e.g., "1.", "2)", "1 ")
            is_new_tweet = (stripped and stripped[0].isdigit() and
                           len(stripped) > 1 and stripped[1] in '.):/ ')

            if is_new_tweet:
                # Save previous tweet if exists
                if current_tweet_lines:
                    tweet_text = '\n'.join(current_tweet_lines)
                    tweets.append(tweet_text)
                    current_tweet_lines = []

                # Remove number prefix and start new tweet
                tweet = stripped.split('.', 1)[-1].strip() if '.' in stripped[:3] else stripped
                tweet = tweet.split(')', 1)[-1].strip() if ')' in tweet[:3] else tweet
                tweet = tweet.split('/', 1)[-1].strip() if '/' in tweet[:3] else tweet
                if tweet:
                    current_tweet_lines.append(tweet)
            elif stripped and current_tweet_lines:
                # Continue adding to current tweet
                current_tweet_lines.append(stripped)

        # Don't forget the last tweet
        if current_tweet_lines:
            tweet_text = '\n'.join(current_tweet_lines)
            tweets.append(tweet_text)

        if tweets:
            # Apply simplification and validation
            processed_tweets = []
            for tweet in tweets:
                # Simplify corporate speak
                tweet = self.simplify_text(tweet)
                processed_tweets.append(tweet)

            self._save_tweets(topic, processed_tweets)
            self.generated_tweets += len(processed_tweets)

            cprint("\n✅ Generated Tweets:", "green")
            for i, tweet in enumerate(processed_tweets, 1):
                is_valid, issues = self.validate_tweet(tweet)
                cprint(f"\n{i}. {tweet}", "white")
                cprint(f"   [{len(tweet)} chars]", "cyan")
                if is_valid:
                    cprint(f"   ✓ Passes quality check", "green")
                else:
                    cprint(f"   ⚠ Issues: {', '.join(issues)}", "yellow")

            return processed_tweets

        return tweets

    def generate_thread(self, topic: str, length: int = 6, thesis: str = None) -> List[str]:
        """Generate a Twitter thread"""

        if not thesis:
            thesis = f"The system that changes how you play {topic}"

        cprint(f"\n🧵 Generating {length}-tweet thread about: {topic}", "yellow")

        prompt = THREAD_GENERATION_PROMPT.format(
            persona=BRAND_PERSONA,
            topic=topic,
            thesis=thesis,
            length=length,
            length_minus_1=length - 1,
            length_minus_2=length - 2
        )

        response = self._generate(BRAND_PERSONA, prompt)

        # Parse thread - collect multi-line content for each numbered tweet
        thread = []
        current_tweet_lines = []
        lines = response.split('\n')
        thread_prefix_pattern = re.compile(r'^(\d+)[/)\.]')

        for line in lines:
            stripped = line.strip()
            # Check if this is a new thread tweet (e.g., "1/", "2/", "3.")
            match = thread_prefix_pattern.match(stripped)

            if match:
                # Save previous tweet if exists
                if current_tweet_lines:
                    tweet_text = '\n'.join(current_tweet_lines)
                    thread.append(tweet_text)
                    current_tweet_lines = []

                # Remove number prefix and start new tweet
                tweet = stripped[match.end():].strip()
                if tweet:
                    current_tweet_lines.append(tweet)
            elif stripped and current_tweet_lines:
                # Continue adding to current tweet
                current_tweet_lines.append(stripped)

        # Don't forget the last tweet
        if current_tweet_lines:
            tweet_text = '\n'.join(current_tweet_lines)
            thread.append(tweet_text)

        if thread:
            # Apply simplification
            processed_thread = [self.simplify_text(tweet) for tweet in thread]

            self._save_thread(topic, processed_thread)
            self.generated_threads += 1

            cprint("\n✅ Generated Thread:", "green")
            for i, tweet in enumerate(processed_thread, 1):
                is_valid, issues = self.validate_tweet(tweet)
                cprint(f"\n{i}/ {tweet}", "white")
                cprint(f"   [{len(tweet)} chars]", "cyan")
                if is_valid:
                    cprint(f"   ✓ Passes quality check", "green")
                else:
                    cprint(f"   ⚠ Issues: {', '.join(issues)}", "yellow")

            return processed_thread

        return thread

    def generate_reply(self, tweet_text: str) -> Dict[str, str]:
        """Generate reply options for a tweet"""

        cprint(f"\n💬 Generating replies for: {tweet_text[:50]}...", "yellow")

        prompt = ENGAGEMENT_PROMPT.format(
            persona=BRAND_PERSONA,
            tweet=tweet_text
        )

        response = self._generate(BRAND_PERSONA, prompt)

        # Parse replies
        replies = {}
        current_mode = None
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith('EDUCATIONAL:'):
                replies['educational'] = line.replace('EDUCATIONAL:', '').strip()
            elif line.startswith('CONTRARIAN:'):
                replies['contrarian'] = line.replace('CONTRARIAN:', '').strip()
            elif line.startswith('WIT:'):
                replies['wit'] = line.replace('WIT:', '').strip()

        if replies:
            cprint("\n✅ Generated Replies:", "green")
            for mode, reply in replies.items():
                cprint(f"\n[{mode.upper()}]: {reply}", "white")
                cprint(f"   [{len(reply)} chars]", "cyan")

        return replies

    def generate_video_script(self, topic: str) -> str:
        """Generate a faceless video script"""

        cprint(f"\n🎬 Generating video script for: {topic}", "yellow")

        prompt = FACELESS_VIDEO_SCRIPT_PROMPT.format(
            persona=BRAND_PERSONA,
            topic=topic
        )

        response = self._generate(BRAND_PERSONA, prompt)

        # Save script
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = DATA_DIR / f"video_script_{timestamp}.md"
        with open(filename, 'w') as f:
            f.write(f"# Video Script: {topic}\n\n")
            f.write(f"Generated: {datetime.now().isoformat()}\n\n")
            f.write("---\n\n")
            f.write(response)

        cprint(f"\n✅ Script saved to: {filename}", "green")
        cprint("\n" + response, "white")

        return response

    def generate_week_of_content(self) -> Dict:
        """Generate a week's worth of content"""

        cprint("\n📅 Generating Week of Content", "cyan", attrs=["bold"])
        cprint("=" * 50, "cyan")

        content = {
            "threads": [],
            "standalone_tweets": [],
            "video_scripts": []
        }

        # 2 threads for the week
        thread_topics = [
            ("Why card counting works (the math)", "The casino doesn't have a 100% edge. Here's how to flip the script."),
            ("Biggest blackjack mistakes costing you money", "Most players lose not because of bad luck, but bad decisions.")
        ]

        for topic, thesis in thread_topics:
            thread = self.generate_thread(topic, length=7, thesis=thesis)
            content["threads"].append({"topic": topic, "tweets": thread})

        # 14 standalone tweets (2 per day)
        for category in list(TOPIC_BANK.keys())[:3]:
            tweets = self.generate_tweets(category=category, count=5)
            content["standalone_tweets"].extend(tweets)

        # 2 video scripts
        video_topics = [
            "Counting cards in 60 seconds tutorial",
            "Why true count matters more than running count"
        ]

        for topic in video_topics:
            script = self.generate_video_script(topic)
            content["video_scripts"].append({"topic": topic, "script": script})

        # Save content calendar
        timestamp = datetime.now().strftime("%Y%m%d")
        calendar_file = CONTENT_CALENDAR_DIR / f"week_{timestamp}.json"
        with open(calendar_file, 'w') as f:
            json.dump(content, f, indent=2)

        cprint(f"\n✅ Week content saved to: {calendar_file}", "green")

        return content

    def _save_tweets(self, topic: str, tweets: List[str]):
        """Save generated tweets to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = TWEETS_DIR / f"tweets_{timestamp}.json"

        data = {
            "topic": topic,
            "generated_at": datetime.now().isoformat(),
            "tweets": tweets
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        cprint(f"💾 Saved to: {filename}", "cyan")

    def _save_thread(self, topic: str, thread: List[str]):
        """Save generated thread to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = THREADS_DIR / f"thread_{timestamp}.json"

        data = {
            "topic": topic,
            "generated_at": datetime.now().isoformat(),
            "thread": thread
        }

        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)

        cprint(f"💾 Saved to: {filename}", "cyan")

    def interactive_mode(self):
        """Run interactive CLI"""

        while True:
            cprint("\n🎰 BLACKJACK GOD TWITTER ENGINE", "cyan", attrs=["bold"])
            cprint("=" * 50, "cyan")
            cprint("1. Generate Tweets", "white")
            cprint("2. Generate Thread", "white")
            cprint("3. Generate Reply Options", "white")
            cprint("4. Generate Video Script", "white")
            cprint("5. Generate Week of Content", "white")
            cprint("6. Show Topic Bank", "white")
            cprint("7. Stats", "white")
            cprint("0. Exit", "white")

            choice = input("\n> ").strip()

            if choice == "1":
                topic = input("Topic (or press Enter for random): ").strip() or None
                count = input("How many tweets? [5]: ").strip() or "5"
                self.generate_tweets(topic=topic, count=int(count))

            elif choice == "2":
                topic = input("Thread topic: ").strip()
                length = input("Thread length [6]: ").strip() or "6"
                thesis = input("Thesis/angle (optional): ").strip() or None
                self.generate_thread(topic, int(length), thesis)

            elif choice == "3":
                tweet = input("Paste the tweet to reply to: ").strip()
                self.generate_reply(tweet)

            elif choice == "4":
                topic = input("Video topic: ").strip()
                self.generate_video_script(topic)

            elif choice == "5":
                self.generate_week_of_content()

            elif choice == "6":
                cprint("\n📚 Topic Bank:", "cyan")
                for category, topics in TOPIC_BANK.items():
                    cprint(f"\n[{category.upper()}]", "yellow")
                    for topic in topics:
                        cprint(f"  • {topic}", "white")

            elif choice == "7":
                cprint(f"\n📊 Stats:", "cyan")
                cprint(f"  Tweets Generated: {self.generated_tweets}", "white")
                cprint(f"  Threads Generated: {self.generated_threads}", "white")

            elif choice == "0":
                cprint("\n👋 See you at the tables!", "cyan")
                break


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Blackjack God Twitter Engine")
    parser.add_argument("--tweets", type=int, help="Generate N tweets")
    parser.add_argument("--thread", type=str, help="Generate thread on topic")
    parser.add_argument("--week", action="store_true", help="Generate week of content")
    parser.add_argument("--topic", type=str, help="Specific topic for generation")

    args = parser.parse_args()

    agent = BlackjackTwitterAgent()

    if args.tweets:
        agent.generate_tweets(topic=args.topic, count=args.tweets)
    elif args.thread:
        agent.generate_thread(args.thread)
    elif args.week:
        agent.generate_week_of_content()
    else:
        agent.interactive_mode()


if __name__ == "__main__":
    main()
