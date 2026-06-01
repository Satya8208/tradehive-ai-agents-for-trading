"""
Stripe Payments Module for Blackjack God SaaS
Handles subscriptions, checkout, and webhooks
Built with love by TradeHive
"""

import os
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request
from dotenv import load_dotenv

load_dotenv()

# Stripe configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Price IDs - Create these in Stripe Dashboard
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_PREMIUM_PRICE_ID = os.getenv("STRIPE_PREMIUM_PRICE_ID", "")

# Pricing
PRICES = {
    "pro": {
        "price_id": STRIPE_PRO_PRICE_ID,
        "amount": 1500,  # $15.00
        "name": "Pro",
        "interval": "month"
    },
    "premium": {
        "price_id": STRIPE_PREMIUM_PRICE_ID,
        "amount": 2500,  # $25.00
        "name": "Premium",
        "interval": "month"
    }
}

# Initialize Stripe lazily
_stripe = None

def get_stripe():
    """Get Stripe client"""
    global _stripe
    if _stripe is None:
        try:
            import stripe
            if STRIPE_SECRET_KEY:
                stripe.api_key = STRIPE_SECRET_KEY
                _stripe = stripe
            else:
                print("⚠️ Stripe not configured - running in demo mode")
                return None
        except ImportError:
            print("⚠️ Stripe library not installed - pip install stripe")
            return None
    return _stripe


async def create_checkout_session(
    user_id: str,
    user_email: str,
    tier: str,
    success_url: str,
    cancel_url: str
) -> Optional[str]:
    """
    Create a Stripe Checkout session for subscription.
    Returns the checkout URL.
    """
    stripe = get_stripe()

    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Payment system not configured"
        )

    if tier not in PRICES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier: {tier}"
        )

    price_info = PRICES[tier]

    if not price_info["price_id"]:
        raise HTTPException(
            status_code=503,
            detail="Stripe price not configured for this tier"
        )

    try:
        # Create checkout session
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{
                "price": price_info["price_id"],
                "quantity": 1
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=user_email,
            metadata={
                "user_id": user_id,
                "tier": tier
            },
            subscription_data={
                "metadata": {
                    "user_id": user_id,
                    "tier": tier
                }
            }
        )

        return session.url

    except Exception as e:
        print(f"Stripe error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create checkout session"
        )


async def create_portal_session(
    customer_id: str,
    return_url: str
) -> Optional[str]:
    """
    Create a Stripe Customer Portal session for managing subscription.
    Returns the portal URL.
    """
    stripe = get_stripe()

    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Payment system not configured"
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url
        )
        return session.url

    except Exception as e:
        print(f"Stripe portal error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create portal session"
        )


async def handle_webhook(request: Request) -> Dict[str, Any]:
    """
    Handle Stripe webhooks for subscription events.
    Returns event data for processing.
    """
    stripe = get_stripe()

    if stripe is None:
        raise HTTPException(
            status_code=503,
            detail="Payment system not configured"
        )

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return event


def get_tier_from_price(price_id: str) -> str:
    """Get tier name from Stripe price ID"""
    for tier, info in PRICES.items():
        if info["price_id"] == price_id:
            return tier
    return "free"


async def process_subscription_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process subscription webhook events.
    Returns user_id and new tier for database update.
    """
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    result = {
        "event_type": event_type,
        "processed": False,
        "user_id": None,
        "new_tier": None,
        "customer_id": None
    }

    if event_type == "checkout.session.completed":
        # User completed checkout
        metadata = data.get("metadata", {})
        result["user_id"] = metadata.get("user_id")
        result["new_tier"] = metadata.get("tier")
        result["customer_id"] = data.get("customer")
        result["processed"] = True

    elif event_type == "customer.subscription.updated":
        # Subscription changed (upgrade/downgrade)
        metadata = data.get("metadata", {})
        result["user_id"] = metadata.get("user_id")

        # Get tier from price
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
            result["new_tier"] = get_tier_from_price(price_id)

        result["customer_id"] = data.get("customer")
        result["processed"] = True

    elif event_type == "customer.subscription.deleted":
        # Subscription cancelled
        metadata = data.get("metadata", {})
        result["user_id"] = metadata.get("user_id")
        result["new_tier"] = "free"
        result["customer_id"] = data.get("customer")
        result["processed"] = True

    return result


# Pricing display helper
def get_pricing_display() -> Dict[str, Any]:
    """Get pricing information for display"""
    return {
        "tiers": [
            {
                "name": "Free",
                "price": 0,
                "interval": "forever",
                "features": [
                    "Basic strategy lookup",
                    "Hi-Lo counting practice (10/day)",
                    "Limited advisor mode"
                ],
                "cta": "Get Started",
                "popular": False
            },
            {
                "name": "Pro",
                "price": 15,
                "interval": "month",
                "price_id": STRIPE_PRO_PRICE_ID,
                "features": [
                    "Everything in Free",
                    "Unlimited counting practice",
                    "Full advisor mode",
                    "Session tracking",
                    "Count-based deviations"
                ],
                "cta": "Upgrade to Pro",
                "popular": True
            },
            {
                "name": "Premium",
                "price": 25,
                "interval": "month",
                "price_id": STRIPE_PREMIUM_PRICE_ID,
                "features": [
                    "Everything in Pro",
                    "Omega II & Wong Halves systems",
                    "Advanced analytics",
                    "Progress tracking",
                    "Priority support"
                ],
                "cta": "Go Premium",
                "popular": False
            }
        ],
        "currency": "USD",
        "stripe_key": STRIPE_PUBLISHABLE_KEY
    }
