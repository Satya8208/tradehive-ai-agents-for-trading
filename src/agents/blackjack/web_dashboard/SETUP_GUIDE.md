# Blackjack God SaaS - Setup Guide

## Prerequisites

Before you can run the SaaS features, you need:
1. **Supabase account** (free tier works)
2. **Stripe account** (test mode for development)
3. **Python packages**: `pip install supabase stripe`

---

## Step 1: Set Up Supabase

### 1.1 Create a Supabase Project
1. Go to [supabase.com](https://supabase.com) and create an account
2. Click "New Project"
3. Name it "blackjack-god" or similar
4. Choose a password and region
5. Wait for project to initialize (~2 minutes)

### 1.2 Get Your API Keys
1. Go to **Settings → API**
2. Copy the **Project URL** (e.g., `https://xxx.supabase.co`)
3. Copy the **anon/public key** (for frontend)
4. Copy the **service_role key** (for backend - keep secret!)

### 1.3 Create Database Tables
1. Go to **SQL Editor**
2. Run this SQL:

```sql
-- User profiles (linked to Supabase Auth)
CREATE TABLE profiles (
    id UUID REFERENCES auth.users PRIMARY KEY,
    email TEXT,
    tier TEXT DEFAULT 'free',  -- 'free', 'pro', 'premium'
    stripe_customer_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Training progress
CREATE TABLE training_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id),
    basic_strategy_accuracy FLOAT DEFAULT 0,
    counting_speed_seconds FLOAT,
    true_count_accuracy FLOAT DEFAULT 0,
    total_hands_practiced INT DEFAULT 0,
    streak_days INT DEFAULT 0,
    last_practice TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Session history
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id),
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    hands_played INT DEFAULT 0,
    decisions_correct INT DEFAULT 0,
    counting_errors INT DEFAULT 0,
    profit_loss FLOAT DEFAULT 0
);

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (new.id, new.email);
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
```

### 1.4 Enable Google OAuth (Optional)
1. Go to **Authentication → Providers**
2. Enable Google
3. Add your Google OAuth credentials

---

## Step 2: Set Up Stripe

### 2.1 Create Stripe Account
1. Go to [stripe.com](https://stripe.com) and create an account
2. Toggle to **Test Mode** (top right)

### 2.2 Create Products and Prices
1. Go to **Products → Add Product**
2. Create "Pro" subscription:
   - Name: Blackjack God Pro
   - Price: $15/month (recurring)
   - Copy the **Price ID** (starts with `price_`)
3. Create "Premium" subscription:
   - Name: Blackjack God Premium
   - Price: $25/month (recurring)
   - Copy the **Price ID**

### 2.3 Get API Keys
1. Go to **Developers → API Keys**
2. Copy **Publishable key** (`pk_test_...`)
3. Copy **Secret key** (`sk_test_...`)

### 2.4 Set Up Webhooks (for production)
1. Go to **Developers → Webhooks**
2. Click **Add endpoint**
3. URL: `https://your-domain.com/api/webhooks/stripe`
4. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Copy the **Webhook signing secret** (`whsec_...`)

---

## Step 3: Configure Environment

Create a `.env` file in the project root:

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key

# Stripe
STRIPE_SECRET_KEY=your_stripe_secret_key_here
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key_here
STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret_here
STRIPE_PRO_PRICE_ID=your_stripe_pro_price_id_here
STRIPE_PREMIUM_PRICE_ID=your_stripe_premium_price_id_here

# App
APP_URL=http://localhost:8000
```

---

## Step 4: Install Dependencies

```bash
pip install supabase stripe python-dotenv
```

---

## Step 5: Run the App

```bash
cd src/agents/blackjack/web_dashboard
python run_dashboard.py
```

Then open:
- Dashboard: http://localhost:8000
- Login: http://localhost:8000/auth
- Pricing: http://localhost:8000/pricing

---

## Demo Mode

If Supabase/Stripe aren't configured, the app runs in **demo mode**:
- All features unlocked
- No login required
- Perfect for testing and development

---

## Deployment Options

### Vercel (Recommended for Frontend)
Good for serving static pages. Backend needs separate hosting.

### Railway
1. Connect GitHub repo
2. Add environment variables
3. Deploy

### Render
1. Create new Web Service
2. Connect GitHub repo
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `uvicorn api:app --host 0.0.0.0 --port $PORT`
5. Add environment variables

---

## Testing Checklist

- [ ] Supabase project created
- [ ] Database tables created
- [ ] Stripe products created ($15 Pro, $25 Premium)
- [ ] Environment variables set
- [ ] App starts without errors
- [ ] Login page works
- [ ] Pricing page shows correctly
- [ ] Stripe checkout opens (test mode)
