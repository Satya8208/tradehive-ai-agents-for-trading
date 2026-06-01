---
name: twitter-scraper
description: Scrape tweets from Twitter/X "For You" feed using MCP browser tools, collecting tweet data (handle, text, url, engagement) and saving to JSON
---

# Twitter Scraper Skill

Scrape tweets from Twitter/X "For You" feed using Claude in Chrome MCP tools. Collects tweet data including handle, text, URL, and engagement metrics, opens each tweet in a separate browser tab, and optionally saves to JSON.

## When to Use This Skill

Use this skill when the user mentions:
- "scrape tweets from Twitter"
- "get tweets from Twitter"
- "scrape tweets from X"
- "collect tweets from my feed"
- "scrape my Twitter feed"
- "get tweets from For You"

## Parameters

- **Tweet Count**: Number of tweets to scrape (default: 20, range: 10-50)
  - Parse from user request, e.g., "scrape 25 tweets" → count = 25
  - If not specified, use 20

- **Save to JSON**: Whether to save scraped tweets to a JSON file (default: NO)
  - Enable if user says "and save", "save them", "save to file", "save to JSON"
  - Example: "scrape 15 tweets and save" → saveToJson = true
  - Example: "scrape 20 tweets" → saveToJson = false (just open tabs)

## Output

- **Chrome Tabs**: Each scraped tweet URL opened in a new tab (ALWAYS)
- **JSON File** (optional): `src/data/nirvana_nuts/scraped_tweets_with_urls.json` (only if user requests save)

## Step-by-Step Instructions

### Step 1: Initialize Browser Context

Get the Chrome tab context and find the Twitter/X tab.

```
Use mcp__claude-in-chrome__tabs_context_mcp to get available tabs
```

Look for a tab with URL containing `x.com` or `twitter.com`. If no Twitter tab exists, tell the user to open Twitter first and navigate to the "For You" feed.

### Step 2: Take Initial Screenshot

```
Use mcp__claude-in-chrome__computer with action="screenshot" on the Twitter tab
```

Verify you're on the Twitter "For You" feed. If not, inform the user.

### Step 3: Initialize Tweet Storage

Run this JavaScript to set up the storage object:

```javascript
// Initialize storage for scraped tweets
window.allScrapedTweets = window.allScrapedTweets || {};
window.scrapedTweetCount = Object.keys(window.allScrapedTweets).length;
console.log('[Scraper] Initialized. Current tweet count:', window.scrapedTweetCount);
window.scrapedTweetCount;
```

### Step 4: Scrape Tweets Loop

Repeat until target tweet count is reached:

#### 4a. Extract Tweets from Current View

Run this JavaScript to extract tweets:

```javascript
(() => {
  const MIN_VIEWS = 5000;

  // Helper to parse view counts (handles K, M suffixes)
  const parseViewCount = (viewStr) => {
    if (!viewStr) return 0;
    const cleaned = viewStr.replace(/,/g, '').trim();
    const match = cleaned.match(/^([\d.]+)([KMB]?)$/i);
    if (!match) return 0;
    const num = parseFloat(match[1]);
    const suffix = match[2].toUpperCase();
    if (suffix === 'K') return num * 1000;
    if (suffix === 'M') return num * 1000000;
    if (suffix === 'B') return num * 1000000000;
    return num;
  };

  // Find all tweet articles
  const articles = document.querySelectorAll('article[data-testid="tweet"]');
  let newTweets = 0;

  articles.forEach(article => {
    try {
      // Get the tweet link to extract status ID
      const tweetLink = article.querySelector('a[href*="/status/"]');
      if (!tweetLink) return;

      const href = tweetLink.getAttribute('href');
      const statusMatch = href.match(/\/status\/(\d+)/);
      if (!statusMatch) return;

      const tweetId = statusMatch[1];

      // Skip if already scraped
      if (window.allScrapedTweets[tweetId]) return;

      // Get handle
      const handleEl = article.querySelector('div[data-testid="User-Name"] a[href^="/"]');
      const handle = handleEl ? '@' + handleEl.getAttribute('href').replace('/', '') : '';

      // Get display name
      const nameEl = article.querySelector('div[data-testid="User-Name"] span');
      const displayName = nameEl ? nameEl.textContent : '';

      // Get tweet text
      const textEl = article.querySelector('div[data-testid="tweetText"]');
      const text = textEl ? textEl.textContent : '';

      // Get engagement metrics - look for the analytics link or metric spans
      const analyticsGroup = article.querySelector('div[role="group"]');
      let views = '0', likes = '0', retweets = '0', replies = '0';

      if (analyticsGroup) {
        // Get all metric buttons/links
        const buttons = analyticsGroup.querySelectorAll('button, a');
        buttons.forEach(btn => {
          const ariaLabel = btn.getAttribute('aria-label') || '';
          const text = btn.textContent || '';

          if (ariaLabel.includes('replies') || ariaLabel.includes('Reply')) {
            replies = text.trim() || '0';
          } else if (ariaLabel.includes('Repost') || ariaLabel.includes('repost')) {
            retweets = text.trim() || '0';
          } else if (ariaLabel.includes('Like') || ariaLabel.includes('like')) {
            likes = text.trim() || '0';
          } else if (ariaLabel.includes('views') || ariaLabel.includes('View')) {
            views = text.trim() || '0';
          }
        });

        // Alternative: look for views in analytics link
        const viewsLink = analyticsGroup.querySelector('a[href*="/analytics"]');
        if (viewsLink) {
          const viewText = viewsLink.textContent.trim();
          if (viewText) views = viewText;
        }
      }

      // Parse view count and filter
      const viewCount = parseViewCount(views);
      if (viewCount < MIN_VIEWS) {
        console.log('[Scraper] Skipping low-engagement tweet:', tweetId, 'views:', views);
        return;
      }

      // Build tweet URL
      const userHandle = handle.replace('@', '');
      const tweetUrl = `https://x.com/${userHandle}/status/${tweetId}`;

      // Store the tweet
      window.allScrapedTweets[tweetId] = {
        id: tweetId,
        handle: handle,
        displayName: displayName,
        text: text.substring(0, 500), // Truncate long tweets
        url: tweetUrl,
        views: views,
        likes: likes,
        retweets: retweets,
        replies: replies
      };

      newTweets++;
      console.log('[Scraper] Added tweet:', tweetId, 'views:', views);

    } catch (e) {
      console.log('[Scraper] Error processing tweet:', e.message);
    }
  });

  window.scrapedTweetCount = Object.keys(window.allScrapedTweets).length;

  return {
    newTweets: newTweets,
    totalTweets: window.scrapedTweetCount,
    tweets: window.allScrapedTweets
  };
})();
```

#### 4b. Check Progress

After extraction, check if target count reached. The JavaScript returns `totalTweets`.

If `totalTweets >= targetCount`, proceed to Step 5.

#### 4c. Scroll Down

If more tweets needed, scroll to load more:

```
Use mcp__claude-in-chrome__computer with:
- action: "scroll"
- scroll_direction: "down"
- scroll_amount: 5
- coordinate: [640, 400] (center of page)
```

#### 4d. Wait for Content Load

```
Use mcp__claude-in-chrome__computer with:
- action: "wait"
- duration: 2
```

#### 4e. Repeat

Go back to Step 4a. Continue until target count reached.

**Important**: Twitter virtualizes DOM - tweets disappear when scrolled past. That's why we store in `window.allScrapedTweets` by ID to avoid duplicates and preserve data.

### Step 5: Get Final Tweet Data

Run this JavaScript to get the final data:

```javascript
(() => {
  const tweets = Object.values(window.allScrapedTweets);
  const result = {
    scraped_at: new Date().toISOString().split('T')[0],
    total_tweets: tweets.length,
    tweets: tweets
  };
  return JSON.stringify(result, null, 2);
})();
```

### Step 6: Save to JSON File (OPTIONAL - only if user requested)

**Skip this step unless the user explicitly asked to save (e.g., "scrape and save", "save to file").**

If saving is requested, use the Write tool to save the JSON data to:
`src/data/nirvana_nuts/scraped_tweets_with_urls.json`

The JSON format:
```json
{
  "scraped_at": "2026-01-22",
  "total_tweets": 25,
  "tweets": [
    {
      "id": "2013928578464002392",
      "handle": "@ExampleUser",
      "displayName": "Example User",
      "text": "Tweet content...",
      "url": "https://x.com/ExampleUser/status/2013928578464002392",
      "views": "15.2K",
      "likes": "3.5K",
      "retweets": "495",
      "replies": "76"
    }
  ]
}
```

### Step 7: Open Tweets in New Tabs

For each tweet in the scraped data:

1. Create a new tab:
   ```
   Use mcp__claude-in-chrome__tabs_create_mcp
   ```

2. Navigate to the tweet URL:
   ```
   Use mcp__claude-in-chrome__navigate with:
   - url: tweet.url
   - tabId: (new tab ID)
   ```

3. Brief wait between tabs to avoid overwhelming:
   ```
   Use mcp__claude-in-chrome__computer with action="wait", duration=0.5
   ```

### Step 8: Report Results

Tell the user:
- How many tweets were scraped
- How many tabs were opened
- Note that only tweets with 5,000+ views were included
- If JSON was saved, mention the file path

## Error Handling

- **No Twitter tab**: Tell user to open Twitter/X and navigate to "For You" feed
- **Not on For You feed**: Tell user to navigate to the "For You" tab
- **Rate limiting**: If scrolling stops loading new tweets, wait longer between scrolls
- **Low engagement tweets**: Tweets under 5K views are automatically filtered out

## Example Invocations

**User**: "Scrape 15 tweets from Twitter"
**Action**: Scrape 15 tweets with 5K+ views, open 15 tabs (NO JSON save)

**User**: "Get tweets from X"
**Action**: Scrape 20 tweets (default), open 20 tabs (NO JSON save)

**User**: "Scrape 25 tweets and save"
**Action**: Scrape 25 tweets with 5K+ views, open 25 tabs, SAVE to JSON

**User**: "Scrape tweets from my feed and save them to file"
**Action**: Scrape 20 tweets (default), open 20 tabs, SAVE to JSON

## Notes

- The 5,000 view minimum filter ensures only high-engagement tweets are collected
- Twitter's DOM virtualization means tweets disappear when scrolled past - the window storage handles this
- JSON saving is OPTIONAL - only save when user explicitly requests it
- If saving, each scrape overwrites the previous JSON file
- Tabs open in the same MCP tab group for easy management
