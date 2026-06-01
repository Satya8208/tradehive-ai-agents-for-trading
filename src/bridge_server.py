"""
🌉 TradeHive's Bridge Server
Built with love by TradeHive 🚀

Relays AI prompts from agents to your subscription AI (Claude Code / Kimi).
Run this in one terminal, then run your agent in another terminal.

Usage:
    python src/bridge_server.py

Then in another terminal:
    BLACKJACK_TWITTER_MODEL=bridge python src/agents/blackjack/blackjack_twitter_agent.py
"""
from flask import Flask, request, jsonify
from datetime import datetime
from termcolor import cprint
import sys

app = Flask(__name__)
request_count = 0


def format_prompt_display(data):
    """Format the prompt for beautiful terminal display"""
    global request_count

    cprint("\n" + "=" * 70, "cyan")
    cprint(f"  🎯 REQUEST #{request_count} - {datetime.now().strftime('%H:%M:%S')}", "yellow", attrs=["bold"])
    cprint("=" * 70, "cyan")

    # System prompt
    cprint("\n📝 SYSTEM PROMPT:", "green", attrs=["bold"])
    cprint("-" * 50, "green")
    system_prompt = data.get("system_prompt", "")
    if len(system_prompt) > 800:
        print(system_prompt[:800])
        cprint(f"\n... [{len(system_prompt)} chars total - truncated for display]", "yellow")
    else:
        print(system_prompt)

    # User content
    cprint("\n💬 USER CONTENT:", "blue", attrs=["bold"])
    cprint("-" * 50, "blue")
    user_content = data.get("user_content", "")
    print(user_content)

    # Check for image
    if "[IMAGE ATTACHED" in user_content:
        cprint("\n🖼️  IMAGE ATTACHED - Check the path above!", "red", attrs=["bold"])

    # Parameters
    cprint("\n⚙️  PARAMS:", "magenta")
    print(f"   Temperature: {data.get('temperature', 0.7)}")
    print(f"   Max tokens: {data.get('max_tokens', 2000)}")

    cprint("\n" + "=" * 70, "cyan")
    cprint("  📋 Copy SYSTEM PROMPT + USER CONTENT to Claude Code or Kimi", "white")
    cprint("  ✍️  Paste the AI response below, then press Enter TWICE to submit", "yellow")
    cprint("=" * 70 + "\n", "cyan")


def get_multiline_input():
    """Get multi-line input, submit on double Enter"""
    lines = []
    empty_line_count = 0

    cprint("🎯 Enter response (press Enter twice when done):\n", "green")

    while True:
        try:
            line = input()
            if line == "":
                empty_line_count += 1
                if empty_line_count >= 2:
                    break
                lines.append(line)
            else:
                empty_line_count = 0
                lines.append(line)
        except EOFError:
            break
        except KeyboardInterrupt:
            cprint("\n⚠️  Cancelled - returning empty response", "yellow")
            return ""

    return "\n".join(lines).strip()


@app.route('/generate', methods=['POST'])
def generate():
    """Handle AI generation request from agent"""
    global request_count
    request_count += 1

    data = request.json
    format_prompt_display(data)

    response_content = get_multiline_input()

    if response_content:
        cprint(f"\n✅ Response captured ({len(response_content)} chars)", "green")
    else:
        cprint(f"\n⚠️  Empty response returned", "yellow")

    return jsonify({
        "content": response_content,
        "model": "subscription-ai",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0}
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "requests_handled": request_count})


def print_banner():
    """Print startup banner"""
    cprint("\n" + "=" * 60, "cyan", attrs=["bold"])
    cprint("  🌉 TRADEHIVE BRIDGE SERVER", "cyan", attrs=["bold"])
    cprint("=" * 60, "cyan", attrs=["bold"])
    cprint("\nThis server relays AI prompts from your agents", "white")
    cprint("to your subscription AI (Claude Code / Kimi)", "white")
    cprint("\n📋 WORKFLOW:", "yellow", attrs=["bold"])
    cprint("  1. Keep this terminal open", "white")
    cprint("  2. Run agent in another terminal with bridge model", "white")
    cprint("  3. Prompts appear here - copy to Claude/Kimi", "white")
    cprint("  4. Paste response back, press Enter twice", "white")
    cprint("  5. Agent continues automatically", "white")
    cprint("\n💡 QUICK START:", "green", attrs=["bold"])
    cprint("  Terminal 2: BLACKJACK_TWITTER_MODEL=bridge python src/agents/blackjack/blackjack_twitter_agent.py", "white")
    cprint("\n" + "=" * 60, "cyan", attrs=["bold"])
    cprint(f"  🚀 Server starting on http://localhost:9999", "green", attrs=["bold"])
    cprint("=" * 60 + "\n", "cyan", attrs=["bold"])


if __name__ == "__main__":
    print_banner()

    # Disable Flask's default logging for cleaner output
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    try:
        app.run(host='localhost', port=9999, debug=False, threaded=True)
    except KeyboardInterrupt:
        cprint("\n\n👋 Bridge server stopped", "cyan")
        sys.exit(0)
