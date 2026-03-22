"""
FootballIQ — Pagamentos
=======================
Integração com Stripe (internacional) e Mercado Pago (Brasil).
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from database.connection import get_db, User
from api.auth import get_current_user

router = APIRouter()

STRIPE_SECRET_KEY  = os.getenv("STRIPE_SECRET_KEY",  "")
STRIPE_WEBHOOK_KEY = os.getenv("STRIPE_WEBHOOK_KEY", "")
MP_ACCESS_TOKEN    = os.getenv("MP_ACCESS_TOKEN",    "")

# Planos e preços (IDs do Stripe — configure no dashboard do Stripe)
PLANS = {
    "pro": {
        "nome":        "Pro",
        "preco_brl":   29.90,
        "preco_usd":   5.99,
        "stripe_price_id": os.getenv("STRIPE_PRO_PRICE_ID", "price_xxx"),
        "features":    ["50 análises/dia", "Value bets em tempo real", "Histórico 90 dias"],
    },
    "premium": {
        "nome":        "Premium",
        "preco_brl":   79.90,
        "preco_usd":   14.99,
        "stripe_price_id": os.getenv("STRIPE_PREMIUM_PRICE_ID", "price_yyy"),
        "features":    ["Análises ilimitadas", "Todas as ligas", "API access", "Suporte prioritário"],
    },
}


class CheckoutRequest(BaseModel):
    plan: str
    gateway: str = "stripe"  # stripe | mercadopago


@router.get("/plans")
def get_plans():
    """Lista os planos disponíveis."""
    return PLANS


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cria sessão de pagamento.
    Retorna URL para redirecionar o usuário.
    """
    if body.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Plano inválido")

    plan_info = PLANS[body.plan]

    if body.gateway == "stripe":
        return await _stripe_checkout(user, body.plan, plan_info)
    elif body.gateway == "mercadopago":
        return await _mp_checkout(user, body.plan, plan_info)
    else:
        raise HTTPException(status_code=400, detail="Gateway inválido. Use: stripe | mercadopago")


async def _stripe_checkout(user: User, plan: str, plan_info: dict) -> dict:
    """Cria sessão Stripe Checkout."""
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        session = stripe.checkout.Session.create(
            customer_email = user.email,
            payment_method_types = ["card"],
            line_items = [{
                "price":    plan_info["stripe_price_id"],
                "quantity": 1,
            }],
            mode = "subscription",
            success_url = f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/success?plan={plan}",
            cancel_url  = f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/pricing",
            metadata    = {"user_id": str(user.id), "plan": plan},
        )
        return {"checkout_url": session.url, "gateway": "stripe"}
    except ImportError:
        raise HTTPException(status_code=500, detail="Stripe não instalado. Execute: pip install stripe")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro Stripe: {str(e)}")


async def _mp_checkout(user: User, plan: str, plan_info: dict) -> dict:
    """Cria preferência Mercado Pago."""
    try:
        import mercadopago
        sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

        preference = sdk.preference().create({
            "items": [{
                "title":      f"FootballIQ {plan_info['nome']}",
                "quantity":   1,
                "unit_price": plan_info["preco_brl"],
                "currency_id": "BRL",
            }],
            "payer": {"email": user.email},
            "back_urls": {
                "success": f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/success?plan={plan}",
                "failure": f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/pricing",
            },
            "auto_return": "approved",
            "external_reference": f"{user.id}:{plan}",
        })
        return {
            "checkout_url": preference["response"]["init_point"],
            "gateway": "mercadopago",
        }
    except ImportError:
        raise HTTPException(status_code=500, detail="MercadoPago não instalado. Execute: pip install mercadopago")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro MercadoPago: {str(e)}")


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Recebe eventos do Stripe (pagamento confirmado, cancelamento, etc.)
    Configure a URL no dashboard do Stripe:
    https://dashboard.stripe.com/webhooks → https://seusite.com/payments/webhook/stripe
    """
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        payload    = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_KEY)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = int(session["metadata"]["user_id"])
        plan    = session["metadata"]["plan"]
        result  = await db.execute(select(User).where(User.id == user_id))
        user    = result.scalar_one_or_none()
        if user:
            user.plan      = plan
            user.stripe_id = session.get("customer")
            await db.commit()

    elif event["type"] == "customer.subscription.deleted":
        # Assinatura cancelada → volta para free
        customer_id = event["data"]["object"]["customer"]
        result = await db.execute(select(User).where(User.stripe_id == customer_id))
        user   = result.scalar_one_or_none()
        if user:
            user.plan = "free"
            await db.commit()

    return {"received": True}
