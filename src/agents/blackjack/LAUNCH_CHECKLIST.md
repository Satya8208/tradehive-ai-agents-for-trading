# Blackjack God - Launch Checklist

## Pre-Launch (Complete These First)

### Technical Setup
- [ ] **Stripe Configuration**
  - [ ] Create Stripe account (or use existing)
  - [ ] Switch to test mode for initial testing
  - [ ] Create product: "Blackjack God E-Book" - $27
  - [ ] Create product: "E-Book + AI Tool" - $47
  - [ ] Create product: "Complete Bundle" - $97
  - [ ] Create subscription: "Pro" - $15/month
  - [ ] Create subscription: "Premium" - $25/month
  - [ ] Copy Price IDs to .env file
  - [ ] Set up webhook endpoint: `https://yourdomain.com/api/webhooks/stripe`
  - [ ] Test checkout flow in test mode
  - [ ] Switch to live mode when ready

- [ ] **Supabase Setup**
  - [ ] Verify tables are created (profiles, training_progress, sessions)
  - [ ] Test authentication flow
  - [ ] Verify email confirmations work

- [ ] **ConvertKit Setup**
  - [ ] Create form: "Card Counting Cheat Sheet"
  - [ ] Upload cheat sheet PDF as incentive email
  - [ ] Create 5-email welcome sequence
  - [ ] Copy form embed code to landing.html
  - [ ] Test email signup flow

- [ ] **Domain & Hosting**
  - [ ] Purchase domain (blackjackgod.com or similar)
  - [ ] Deploy to hosting (Vercel, Railway, or Render)
  - [ ] Configure SSL certificate
  - [ ] Set up custom domain
  - [ ] Update APP_URL in .env

### Content Preparation
- [ ] **Cheat Sheet PDF**
  - [ ] Export CHEAT_SHEET.html to PDF
  - [ ] Upload to ConvertKit as lead magnet
  - [ ] Test download link

- [ ] **E-Book**
  - [ ] Compile all chapters into single PDF
  - [ ] Create cover design
  - [ ] Set up delivery method (email or download page)

- [ ] **Twitter Profile**
  - [ ] Create/optimize @BlackjackGod account
  - [ ] Write bio with landing page link
  - [ ] Create pinned tweet with CTA
  - [ ] Upload profile picture (logo)
  - [ ] Upload banner image

---

## Week 1 Launch Sequence

### Day 1: Soft Launch
- [ ] Post announcement tweet: "Something's coming..."
- [ ] Generate 5 tweets using Twitter dashboard
- [ ] Schedule for optimal times (8 AM, 12 PM, 5 PM EST)
- [ ] Engage with 10 gambling/poker accounts

### Day 2: Value First
- [ ] Post educational thread (use Thread template)
- [ ] Include CTA to free cheat sheet
- [ ] Reply to comments within 1 hour
- [ ] Find and engage with 3 viral gambling tweets

### Day 3: Build Authority
- [ ] Share a myth-busting single tweet
- [ ] Post poll about blackjack struggles
- [ ] DM 5 smaller accounts for potential collaboration
- [ ] Check email signups - respond to any replies

### Day 4: Social Proof
- [ ] Share any early feedback/testimonials
- [ ] Post a "behind the scenes" tweet about building this
- [ ] Create urgency: "First 50 signups get [bonus]"

### Day 5: Full Promotion
- [ ] Post major thread about card counting
- [ ] Include multiple CTAs throughout
- [ ] Cross-post to Reddit (r/blackjack) if allowed
- [ ] Email list: Send first value email

### Day 6-7: Analyze & Adjust
- [ ] Review Twitter analytics
- [ ] Check email signup conversion rate
- [ ] Identify best-performing content
- [ ] Plan next week based on data

---

## Daily Operations Checklist

### Morning (15 min)
- [ ] Check overnight engagement
- [ ] Reply to all comments/DMs
- [ ] Post first scheduled tweet
- [ ] Quick scroll through gambling hashtags

### Midday (15 min)
- [ ] Post second scheduled tweet
- [ ] Engage with 5 relevant accounts
- [ ] Check email signups
- [ ] Share/RT valuable content from others

### Evening (15 min)
- [ ] Post final scheduled tweet
- [ ] Reply to afternoon engagement
- [ ] Plan tomorrow's content
- [ ] Generate new content using Twitter dashboard if needed

### Weekly (1 hour)
- [ ] Review analytics (followers, impressions, clicks)
- [ ] Check email list growth
- [ ] Check revenue/conversions
- [ ] Plan next week's content themes
- [ ] Generate batch of tweets/threads

---

## Content Generation Workflow

### Using the Twitter Dashboard

1. Navigate to `http://localhost:8000/twitter`
2. Select content type:
   - **Tweets**: Quick standalone posts
   - **Thread**: Deep-dive educational content
   - **Video Script**: For YouTube Shorts/TikTok

3. Choose category or enter custom topic:
   - `counting_systems` - Card counting techniques
   - `strategy_systems` - Basic strategy content
   - `money_systems` - Bankroll management
   - `myth_busting` - Debunking misconceptions
   - `casino_tactics` - Beating casino countermeasures

4. Generate and review:
   - Check quality badges (green = good)
   - Edit if needed
   - Copy to clipboard

5. Post or schedule:
   - Direct post to Twitter
   - Or use scheduling tool (Buffer, Typefully)

### Content Batching Strategy

**Weekly batch session (1 hour):**
- Generate 10-15 tweets
- Generate 2-3 threads
- Review and edit all
- Schedule for the week
- Keep 5 "evergreen" tweets as backup

---

## Troubleshooting

### Common Issues

**Email signups not working:**
1. Check ConvertKit form ID is correct in landing.html
2. Verify form is published in ConvertKit
3. Test with a different email address
4. Check browser console for errors

**Stripe checkout failing:**
1. Verify Price IDs are correct in .env
2. Check Stripe dashboard for error logs
3. Ensure webhook endpoint is accessible
4. Test in Stripe test mode first

**Twitter dashboard not generating:**
1. Check ANTHROPIC_KEY is set in .env
2. Verify API has credits remaining
3. Check browser console for errors
4. Try refreshing and regenerating

**Auth not working:**
1. Verify SUPABASE_URL and keys are correct
2. Check Supabase dashboard for auth settings
3. Ensure email confirmations are configured
4. Test with email/password (not OAuth first)

---

## Key Metrics to Track

### Week 1 Targets
| Metric | Target |
|--------|--------|
| Tweets posted | 14+ |
| Followers gained | 50+ |
| Email signups | 25+ |
| Landing page visits | 200+ |

### Month 1 Targets
| Metric | Target |
|--------|--------|
| Followers | 500+ |
| Email list | 200+ |
| E-book sales | 5+ |
| SaaS signups | 3+ |
| Revenue | $200+ |

---

## Emergency Contacts & Resources

- **Stripe Support:** dashboard.stripe.com/support
- **Supabase Docs:** supabase.com/docs
- **ConvertKit Help:** help.convertkit.com
- **Twitter Ads:** ads.twitter.com

---

## Notes

_Use this space to track learnings, what's working, and adjustments:_

```
Week 1:
-

Week 2:
-

Week 3:
-

Week 4:
-
```
