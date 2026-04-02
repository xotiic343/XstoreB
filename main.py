"""
XStore - Complete Digital Marketplace with Discord Bot Integration
Matte Black & Red Edition - Production Ready
"""

import os
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import string
import uuid
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from decimal import Decimal

import httpx
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, validator
from jose import JWTError, jwt
from passlib.context import CryptContext
from supabase import create_client, Client
from dotenv import load_dotenv

# Discord webhook
import aiohttp

load_dotenv()

# ==================== CONFIGURATION ====================

class Settings:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    
    # Discord Webhook
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
    DISCORD_ORDER_CHANNEL_ID = os.getenv("DISCORD_ORDER_CHANNEL_ID")
    DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
    
    # SendGrid
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
    
    # Payment Gateways
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
    PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
    
    CASHAPP_CASHTAG = os.getenv("CASHAPP_CASHTAG", "$XStore")
    
    ROBUX_TO_XCOIN_RATE = int(os.getenv("ROBUX_TO_XCOIN_RATE", 10))
    XCOIN_TO_USD_RATE = int(os.getenv("XCOIN_TO_USD_RATE", 100))
    ROBUX_TO_USD_RATE = int(os.getenv("ROBUX_TO_USD_RATE", 80))
    
    FRONTEND_URL = os.getenv("FRONTEND_URL")
    
    AFFILIATE_COMMISSION_PERCENT = int(os.getenv("AFFILIATE_COMMISSION_PERCENT", 10))
    AFFILIATE_COOKIE_DAYS = int(os.getenv("AFFILIATE_COOKIE_DAYS", 30))
    
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@xstore.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 10080))
    
    WELCOME_BONUS_XCOIN = int(os.getenv("WELCOME_BONUS_XCOIN", 100))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

settings = Settings()

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== SUPABASE CLIENT ====================

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# ==================== AUTH SETUP ====================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

verification_sessions: Dict[str, dict] = {}
websocket_connections: Dict[str, List[WebSocket]] = []

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            return None
        user_response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data or user_response.data[0].get("is_banned"):
            return None
        return user_response.data[0]
    except JWTError:
        return None

async def require_user(user = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_owner(user = Depends(require_user)):
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ==================== DISCORD WEBHOOK SERVICE ====================

class DiscordWebhookService:
    """Send notifications to Discord channel"""
    
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
        self.channel_id = settings.DISCORD_ORDER_CHANNEL_ID
    
    async def send_order_notification(self, order: dict, user: dict, items: List[dict]):
        """Send order notification to Discord"""
        if not self.webhook_url:
            logger.warning("Discord webhook not configured")
            return
        
        embed = {
            "title": "🛒 NEW ORDER",
            "color": 0xdc2626,  # Red color
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {
                    "name": "Order ID",
                    "value": f"`#{order['id']}`",
                    "inline": True
                },
                {
                    "name": "Customer",
                    "value": f"{user.get('username', 'Unknown')}\n`{user.get('email', 'No email')}`",
                    "inline": True
                },
                {
                    "name": "Total",
                    "value": f"**${order['total_usd']:.2f}**",
                    "inline": True
                },
                {
                    "name": "Payment Method",
                    "value": order['payment_method'].upper(),
                    "inline": True
                },
                {
                    "name": "Status",
                    "value": order['status'].upper(),
                    "inline": True
                },
                {
                    "name": "Items",
                    "value": "\n".join([f"• {item['product_title']} x{item['quantity']} - ${item['price_usd']:.2f}" for item in items[:5]]) + ("\n..." if len(items) > 5 else ""),
                    "inline": False
                }
            ],
            "footer": {
                "text": "XStore Marketplace",
                "icon_url": "https://cdn.discordapp.com/embed/avatars/0.png"
            }
        }
        
        # Add X Coin info if used
        if order.get('x_coin_used', 0) > 0:
            embed["fields"].append({
                "name": "X Coin Used",
                "value": f"{order['x_coin_used']} XC",
                "inline": True
            })
        
        # Add coupon info if used
        if order.get('coupon_code'):
            embed["fields"].append({
                "name": "Coupon",
                "value": order['coupon_code'],
                "inline": True
            })
        
        payload = {
            "embeds": [embed],
            "username": "XStore Orders",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status != 204:
                        logger.error(f"Discord webhook failed: {resp.status}")
        except Exception as e:
            logger.error(f"Discord webhook error: {e}")
    
    async def send_user_notification(self, user_id: str, title: str, message: str):
        """Send DM to user via Discord bot"""
        if not settings.DISCORD_BOT_TOKEN:
            return
        
        try:
            # Get user's Discord ID from database
            user = supabase.table("users").select("discord_id").eq("id", user_id).execute()
            if not user.data or not user.data[0].get("discord_id"):
                return
            
            discord_id = user.data[0]["discord_id"]
            
            # Send DM via Discord API
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"}
                # Create DM channel
                async with session.post(f"https://discord.com/api/v10/users/@me/channels", 
                                       json={"recipient_id": discord_id}, headers=headers) as dm_resp:
                    if dm_resp.status == 200:
                        dm_data = await dm_resp.json()
                        channel_id = dm_data["id"]
                        # Send message
                        async with session.post(f"https://discord.com/api/v10/channels/{channel_id}/messages",
                                               json={"content": f"**{title}**\n{message}"},
                                               headers=headers) as msg_resp:
                            if msg_resp.status != 200:
                                logger.error(f"Failed to send DM: {msg_resp.status}")
        except Exception as e:
            logger.error(f"Discord DM error: {e}")
    
    async def send_admin_alert(self, alert_type: str, data: dict):
        """Send admin alerts to Discord"""
        if not self.webhook_url:
            return
        
        colors = {
            "low_stock": 0xf59e0b,
            "new_user": 0x10b981,
            "error": 0xef4444,
            "refund": 0xdc2626
        }
        
        embed = {
            "title": f"⚠️ {alert_type.upper()} ALERT",
            "color": colors.get(alert_type, 0xdc2626),
            "timestamp": datetime.utcnow().isoformat(),
            "fields": [
                {"name": k, "value": str(v), "inline": True} for k, v in data.items()
            ]
        }
        
        payload = {
            "embeds": [embed],
            "username": "XStore Admin Alerts"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status != 204:
                        logger.error(f"Admin alert failed: {resp.status}")
        except Exception as e:
            logger.error(f"Admin alert error: {e}")

discord_service = DiscordWebhookService()

# ==================== PRODUCT TEMPLATES ====================

PRODUCT_TEMPLATES = {
    "discord_bot": {
        "title": "Premium Discord Bot",
        "description": "Full-featured moderation bot with auto-mod, logs, and admin commands. Perfect for large Discord servers.",
        "category": "Discord Bots",
        "price_usd": 25.99,
        "image_url": "https://via.placeholder.com/300x200?text=Discord+Bot"
    },
    "roblox_admin": {
        "title": "Roblox Admin Game Pass",
        "description": "Get admin commands in our Roblox game! Fly, teleport, give items, ban users, and more.",
        "category": "Roblox Items",
        "price_usd": 15.99,
        "image_url": "https://via.placeholder.com/300x200?text=Roblox+Admin"
    },
    "netflix_account": {
        "title": "Netflix Premium Account",
        "description": "1 Year Netflix Premium Account. Works worldwide, 4K streaming supported, 4 screens.",
        "category": "Accounts",
        "price_usd": 45.99,
        "image_url": "https://via.placeholder.com/300x200?text=Netflix"
    },
    "photoshop_license": {
        "title": "Adobe Photoshop 2024 License",
        "description": "Adobe Photoshop 2024 lifetime license. Includes all updates and creative cloud access.",
        "category": "Apps & Code",
        "price_usd": 89.99,
        "image_url": "https://via.placeholder.com/300x200?text=Photoshop"
    },
    "steam_giftcard": {
        "title": "Steam Gift Card $50",
        "description": "$50 Steam Wallet Gift Card. Instant delivery, works worldwide.",
        "category": "Game Keys",
        "price_usd": 45.00,
        "image_url": "https://via.placeholder.com/300x200?text=Steam"
    },
    "video_editor_pack": {
        "title": "Video Editor Pro Pack",
        "description": "10 Premiere Pro templates + 20 transitions + SFX pack. Professional quality video assets.",
        "category": "Edits",
        "price_usd": 29.99,
        "image_url": "https://via.placeholder.com/300x200?text=Editor+Pack"
    },
    "discord_nitro": {
        "title": "Discord Nitro (1 Month)",
        "description": "Discord Nitro subscription for 1 month. Global emotes, HD streaming, larger uploads.",
        "category": "Discord Bots",
        "price_usd": 9.99,
        "image_url": "https://via.placeholder.com/300x200?text=Discord+Nitro"
    },
    "roblox_limited": {
        "title": "Roblox Limited Item Bundle",
        "description": "Rare limited items bundle. Includes 3 limited accessories and 10,000 Robux.",
        "category": "Roblox Items",
        "price_usd": 49.99,
        "image_url": "https://via.placeholder.com/300x200?text=Roblox+Limited"
    },
    "spotify_premium": {
        "title": "Spotify Premium (12 Months)",
        "description": "Spotify Premium account for 12 months. Ad-free music, offline listening.",
        "category": "Accounts",
        "price_usd": 35.99,
        "image_url": "https://via.placeholder.com/300x200?text=Spotify"
    },
    "windows_key": {
        "title": "Windows 11 Pro License Key",
        "description": "Genuine Windows 11 Pro license key. Lifetime activation, worldwide.",
        "category": "Apps & Code",
        "price_usd": 19.99,
        "image_url": "https://via.placeholder.com/300x200?text=Windows+11"
    },
    "minecraft_account": {
        "title": "Minecraft Java + Bedrock Account",
        "description": "Minecraft Java Edition + Bedrock Edition account. Full access, email included.",
        "category": "Accounts",
        "price_usd": 24.99,
        "image_url": "https://via.placeholder.com/300x200?text=Minecraft"
    },
    "capcut_pro": {
        "title": "CapCut Pro (1 Year)",
        "description": "CapCut Pro subscription for 1 year. All premium features unlocked.",
        "category": "Edits",
        "price_usd": 49.99,
        "image_url": "https://via.placeholder.com/300x200?text=CapCut+Pro"
    }
}

# ==================== PYDANTIC SCHEMAS ====================

class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6)
    discord_id: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class LinkRoblox(BaseModel):
    roblox_username: str

class ProductCreate(BaseModel):
    title: str
    description: str
    category: str
    price_usd: float
    stock: int
    image_url: Optional[str] = None

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price_usd: Optional[float] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None

class OrderItem(BaseModel):
    product_id: int
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItem]
    payment_method: str
    x_coin_amount: int = 0
    coupon_code: Optional[str] = None
    cashapp_tag: Optional[str] = None

class CouponCreate(BaseModel):
    code: str
    discount_type: str
    discount_value: float
    min_purchase: Optional[float] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

class ReviewCreate(BaseModel):
    product_id: int
    rating: int = Field(ge=1, le=5)
    comment: str

class XCoinAdjustment(BaseModel):
    user_id: str
    amount: int
    reason: str

class RefundOrder(BaseModel):
    order_id: int
    reason: str

class RobuxTierCreate(BaseModel):
    robux_cost: int
    xcoin_amount: int
    game_pass_id: str
    game_pass_url: str
    display_name: str

class UpdateCreate(BaseModel):
    title: str
    content: str

# ==================== DATABASE FUNCTIONS ====================

async def validate_coupon(code: str, user_id: str, total_usd: float):
    response = supabase.table("coupons").select("*").eq("code", code.upper()).execute()
    if not response.data:
        return None
    coupon = response.data[0]
    if coupon.get("expires_at"):
        if datetime.fromisoformat(coupon["expires_at"]) < datetime.utcnow():
            return None
    if coupon.get("max_uses"):
        uses = supabase.table("orders").select("id").eq("coupon_code", code).execute()
        if len(uses.data) >= coupon["max_uses"]:
            return None
    if coupon.get("min_purchase") and total_usd < coupon["min_purchase"]:
        return None
    discount = total_usd * (coupon["discount_value"] / 100) if coupon["discount_type"] == "percentage" else coupon["discount_value"]
    return {"coupon": coupon, "discount": min(discount, total_usd)}

async def send_notification(user_id: str, title: str, message: str, notification_type: str = "info"):
    if user_id in websocket_connections:
        for ws in websocket_connections[user_id]:
            try:
                await ws.send_json({"type": notification_type, "title": title, "message": message, "timestamp": datetime.utcnow().isoformat()})
            except:
                pass
    # Also send Discord DM if user has Discord linked
    await discord_service.send_user_notification(user_id, title, message)

async def update_product_rating(product_id: int):
    reviews = supabase.table("reviews").select("rating").eq("product_id", product_id).execute()
    if reviews.data:
        avg = sum(r["rating"] for r in reviews.data) / len(reviews.data)
        supabase.table("products").update({"average_rating": round(avg, 2), "review_count": len(reviews.data)}).eq("id", product_id).execute()

async def verify_roblox_game_pass(roblox_id: str, game_pass_id: str) -> bool:
    try:
        url = f"https://inventory.roblox.com/v1/users/{roblox_id}/items/GamePass/{game_pass_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return response.status_code == 200 and response.json().get('data')
    except:
        return False

def generate_affiliate_code(user_id: str) -> str:
    return f"{user_id[:6]}_{str(uuid.uuid4())[:8]}".upper()

# ==================== FASTAPI APP ====================

app = FastAPI(title="XStore API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== AUTH ROUTES ====================

@app.post("/api/auth/register")
async def register(user_data: UserRegister):
    existing = supabase.table("users").select("*").eq("email", user_data.email).execute()
    if existing.data:
        raise HTTPException(400, "Email already registered")
    
    existing_username = supabase.table("users").select("*").eq("username", user_data.username).execute()
    if existing_username.data:
        raise HTTPException(400, "Username already taken")
    
    auth_response = supabase.auth.sign_up({
        "email": user_data.email,
        "password": user_data.password,
        "options": {"data": {"username": user_data.username}}
    })
    
    is_owner = user_data.email == settings.ADMIN_EMAIL
    
    supabase.table("users").insert({
        "id": auth_response.user.id,
        "email": user_data.email,
        "username": user_data.username,
        "discord_id": user_data.discord_id,
        "x_coin_balance": settings.WELCOME_BONUS_XCOIN,
        "is_owner": is_owner,
        "is_banned": False,
        "notification_preferences": {"email_order_updates": True, "email_promotions": False},
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("affiliates").insert({
        "user_id": auth_response.user.id,
        "code": generate_affiliate_code(auth_response.user.id),
        "commission_rate": settings.AFFILIATE_COMMISSION_PERCENT,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    access_token = create_access_token({"sub": auth_response.user.id})
    
    # Send welcome Discord DM if Discord ID provided
    if user_data.discord_id:
        await discord_service.send_user_notification(auth_response.user.id, "Welcome to XStore!", f"Welcome {user_data.username}! You received {settings.WELCOME_BONUS_XCOIN} X Coin as a welcome gift.")
    
    return {
        "access_token": access_token,
        "user": {
            "id": auth_response.user.id,
            "email": user_data.email,
            "username": user_data.username,
            "x_coin_balance": settings.WELCOME_BONUS_XCOIN,
            "is_owner": is_owner
        }
    }

@app.post("/api/auth/login")
async def login(login_data: UserLogin):
    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": login_data.email,
            "password": login_data.password
        })
        
        user_response = supabase.table("users").select("*").eq("id", auth_response.user.id).execute()
        if not user_response.data:
            raise HTTPException(404, "User not found")
        
        user = user_response.data[0]
        if user.get("is_banned"):
            raise HTTPException(403, "User is banned")
        
        access_token = create_access_token({"sub": auth_response.user.id})
        
        return {
            "access_token": access_token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "username": user["username"],
                "x_coin_balance": user["x_coin_balance"],
                "is_owner": user["is_owner"],
                "roblox_id": user.get("roblox_id"),
                "roblox_username": user.get("roblox_username"),
                "discord_id": user.get("discord_id")
            }
        }
    except Exception as e:
        raise HTTPException(401, "Invalid credentials")

@app.get("/api/auth/me")
async def get_me(current_user = Depends(require_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "username": current_user["username"],
        "x_coin_balance": current_user["x_coin_balance"],
        "is_owner": current_user["is_owner"],
        "roblox_id": current_user.get("roblox_id"),
        "roblox_username": current_user.get("roblox_username"),
        "discord_id": current_user.get("discord_id")
    }

@app.post("/api/auth/link-roblox")
async def link_roblox(data: LinkRoblox, current_user = Depends(require_user)):
    # Get Roblox user ID from username
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.roblox.com/users/get-by-username?username={data.roblox_username}")
            if response.status_code == 200:
                roblox_data = response.json()
                roblox_id = str(roblox_data.get("Id"))
            else:
                raise HTTPException(400, "Roblox username not found")
    except:
        raise HTTPException(400, "Failed to fetch Roblox user")
    
    supabase.table("users").update({
        "roblox_id": roblox_id,
        "roblox_username": data.roblox_username
    }).eq("id", current_user["id"]).execute()
    
    return {"message": "Roblox account linked", "roblox_id": roblox_id}

@app.post("/api/auth/link-discord")
async def link_discord(discord_id: str, current_user = Depends(require_user)):
    supabase.table("users").update({"discord_id": discord_id}).eq("id", current_user["id"]).execute()
    return {"message": "Discord account linked"}

# ==================== PRODUCT TEMPLATES ROUTES ====================

@app.get("/api/product-templates")
async def get_product_templates(current_user = Depends(require_owner)):
    """Get all product templates for admin"""
    return list(PRODUCT_TEMPLATES.keys())

@app.get("/api/product-templates/{template_id}")
async def get_product_template(template_id: str, current_user = Depends(require_owner)):
    """Get a specific product template"""
    if template_id not in PRODUCT_TEMPLATES:
        raise HTTPException(404, "Template not found")
    return PRODUCT_TEMPLATES[template_id]

@app.post("/api/products/from-template")
async def create_product_from_template(template_id: str, current_user = Depends(require_owner)):
    """Create a product from a template"""
    if template_id not in PRODUCT_TEMPLATES:
        raise HTTPException(404, "Template not found")
    
    template = PRODUCT_TEMPLATES[template_id]
    response = supabase.table("products").insert({
        "title": template["title"],
        "description": template["description"],
        "category": template["category"],
        "price_usd": template["price_usd"],
        "stock": 100,  # Default stock for templates
        "image_url": template["image_url"],
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

# ==================== PRODUCT ROUTES ====================

@app.get("/api/products")
async def get_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
):
    query = supabase.table("products").select("*").eq("is_active", True)
    if search: query = query.ilike("title", f"%{search}%")
    if category: query = query.eq("category", category)
    if min_price: query = query.gte("price_usd", min_price)
    if max_price: query = query.lte("price_usd", max_price)
    if in_stock: query = query.gt("stock", 0)
    return query.order("created_at", desc=True).range(offset, offset + limit - 1).execute().data

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    product = supabase.table("products").select("*").eq("id", product_id).execute()
    if not product.data:
        raise HTTPException(404, "Product not found")
    reviews = supabase.table("reviews").select("*, user:users(username)").eq("product_id", product_id).order("created_at", desc=True).execute()
    product.data[0]["reviews"] = reviews.data
    return product.data[0]

@app.post("/api/products", dependencies=[Depends(require_owner)])
async def create_product(product: ProductCreate):
    response = supabase.table("products").insert({
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "price_usd": product.price_usd,
        "stock": product.stock,
        "image_url": product.image_url,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    return response.data[0]

@app.put("/api/products/{product_id}", dependencies=[Depends(require_owner)])
async def update_product(product_id: int, product: ProductUpdate):
    update_data = {k: v for k, v in product.dict().items() if v is not None}
    response = supabase.table("products").update(update_data).eq("id", product_id).execute()
    return response.data[0] if response.data else {"message": "Product not found"}

@app.delete("/api/products/{product_id}", dependencies=[Depends(require_owner)])
async def delete_product(product_id: int):
    supabase.table("products").update({"is_active": False}).eq("id", product_id).execute()
    return {"message": "Product deleted"}

# ==================== REVIEW ROUTES ====================

@app.post("/api/reviews")
async def create_review(review: ReviewCreate, current_user = Depends(require_user)):
    existing = supabase.table("reviews").select("id").eq("user_id", current_user["id"]).eq("product_id", review.product_id).execute()
    if existing.data:
        raise HTTPException(400, "Already reviewed this product")
    
    response = supabase.table("reviews").insert({
        "user_id": current_user["id"],
        "product_id": review.product_id,
        "rating": review.rating,
        "comment": review.comment,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    await update_product_rating(review.product_id)
    return response.data[0]

@app.get("/api/reviews/product/{product_id}")
async def get_product_reviews(product_id: int):
    return supabase.table("reviews").select("*, user:users(username)").eq("product_id", product_id).order("created_at", desc=True).execute().data

# ==================== WISHLIST ====================

@app.post("/api/wishlist/{product_id}")
async def add_to_wishlist(product_id: int, current_user = Depends(require_user)):
    supabase.table("wishlist").insert({"user_id": current_user["id"], "product_id": product_id}).execute()
    return {"message": "Added to wishlist"}

@app.delete("/api/wishlist/{product_id}")
async def remove_from_wishlist(product_id: int, current_user = Depends(require_user)):
    supabase.table("wishlist").delete().eq("user_id", current_user["id"]).eq("product_id", product_id).execute()
    return {"message": "Removed"}

@app.get("/api/wishlist")
async def get_wishlist(current_user = Depends(require_user)):
    return supabase.table("wishlist").select("*, product:products(*)").eq("user_id", current_user["id"]).execute().data

# ==================== COUPONS ====================

@app.get("/api/coupons/validate")
async def validate_coupon_route(code: str, total_usd: float, current_user = Depends(require_user)):
    result = await validate_coupon(code, current_user["id"], total_usd)
    if not result:
        raise HTTPException(404, "Invalid coupon")
    return {"valid": True, "discount": round(result["discount"], 2), "new_total": round(total_usd - result["discount"], 2), "coupon": result["coupon"]}

@app.post("/api/coupons", dependencies=[Depends(require_owner)])
async def create_coupon(coupon: CouponCreate):
    return supabase.table("coupons").insert({
        "code": coupon.code.upper(),
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "min_purchase": coupon.min_purchase,
        "max_uses": coupon.max_uses,
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        "created_at": datetime.utcnow().isoformat()
    }).execute().data[0]

@app.get("/api/coupons", dependencies=[Depends(require_owner)])
async def get_coupons():
    return supabase.table("coupons").select("*").order("created_at", desc=True).execute().data

@app.delete("/api/coupons/{coupon_id}", dependencies=[Depends(require_owner)])
async def delete_coupon(coupon_id: int):
    supabase.table("coupons").delete().eq("id", coupon_id).execute()
    return {"message": "Deleted"}

# ==================== ORDERS ====================

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, request: Request, current_user = Depends(require_user)):
    products = []
    total_usd = 0
    
    for item in order_data.items:
        product = supabase.table("products").select("*").eq("id", item.product_id).execute()
        if not product.data or product.data[0]["stock"] < item.quantity:
            raise HTTPException(400, f"Product {item.product_id} unavailable")
        p = product.data[0]
        products.append({**p, "quantity": item.quantity})
        total_usd += p["price_usd"] * item.quantity
    
    coupon_discount = 0
    if order_data.coupon_code:
        coupon_result = await validate_coupon(order_data.coupon_code, current_user["id"], total_usd)
        if coupon_result:
            coupon_discount = coupon_result["discount"]
            total_usd -= coupon_discount
    
    x_coin_used = 0
    if order_data.payment_method == "x_coin" and order_data.x_coin_amount > 0:
        if order_data.x_coin_amount > current_user["x_coin_balance"]:
            raise HTTPException(400, "Insufficient X Coin")
        x_coin_used = order_data.x_coin_amount
        total_usd -= x_coin_used / settings.XCOIN_TO_USD_RATE
    
    order = {
        "user_id": current_user["id"],
        "total_usd": round(max(total_usd, 0), 2),
        "x_coin_used": x_coin_used,
        "payment_method": order_data.payment_method,
        "coupon_code": order_data.coupon_code,
        "discount_amount": coupon_discount,
        "cashapp_tag": order_data.cashapp_tag,
        "status": "completed" if total_usd <= 0 else "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    
    order_response = supabase.table("orders").insert(order).execute()
    order_id = order_response.data[0]["id"]
    
    order_items_list = []
    for product in products:
        supabase.table("order_items").insert({
            "order_id": order_id,
            "product_id": product["id"],
            "quantity": product["quantity"],
            "price_usd_at_time": product["price_usd"]
        }).execute()
        supabase.table("products").update({"stock": product["stock"] - product["quantity"]}).eq("id", product["id"]).execute()
        
        order_items_list.append({
            "product_title": product["title"],
            "quantity": product["quantity"],
            "price_usd": product["price_usd"]
        })
        
        # Check low stock
        new_stock = product["stock"] - product["quantity"]
        if new_stock <= 5:
            await discord_service.send_admin_alert("low_stock", {
                "Product": product["title"],
                "Remaining": new_stock,
                "Sold": product["quantity"]
            })
    
    if x_coin_used > 0:
        new_balance = current_user["x_coin_balance"] - x_coin_used
        supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", current_user["id"]).execute()
        supabase.table("xcoin_transactions").insert({
            "user_id": current_user["id"],
            "order_id": order_id,
            "amount": -x_coin_used,
            "reason": f"Order #{order_id}"
        }).execute()
    
    # Send Discord notification
    await discord_service.send_order_notification(order, current_user, order_items_list)
    
    await send_notification(current_user["id"], "Order Confirmed", f"Order #{order_id} confirmed")
    
    return {
        "order_id": order_id,
        "status": order["status"],
        "total_usd": order["total_usd"],
        "x_coin_used": x_coin_used
    }

@app.get("/api/orders")
async def get_my_orders(current_user = Depends(require_user)):
    orders = supabase.table("orders").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    for order in orders.data:
        items = supabase.table("order_items").select("*, product:products(*)").eq("order_id", order["id"]).execute()
        order["items"] = items.data
    return orders.data

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int, current_user = Depends(require_user)):
    order = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order.data:
        raise HTTPException(404, "Order not found")
    if order.data[0]["user_id"] != current_user["id"] and not current_user.get("is_owner"):
        raise HTTPException(403, "Access denied")
    items = supabase.table("order_items").select("*, product:products(*)").eq("order_id", order_id).execute()
    order.data[0]["items"] = items.data
    return order.data[0]

# ==================== X COIN ====================

@app.get("/api/xcoin/balance")
async def get_xcoin_balance(current_user = Depends(require_user)):
    return {"balance": current_user["x_coin_balance"]}

@app.get("/api/xcoin/tiers")
async def get_xcoin_tiers():
    tiers = supabase.table("robux_tiers").select("*").eq("is_active", True).order("robux_cost").execute()
    for tier in tiers.data:
        tier["usd_value"] = round(tier["robux_cost"] / settings.ROBUX_TO_USD_RATE, 2)
        tier["bonus_percentage"] = round((tier["xcoin_amount"] / (tier["robux_cost"] * settings.ROBUX_TO_XCOIN_RATE) - 1) * 100, 1)
    return tiers.data

@app.post("/api/xcoin/buy")
async def buy_xcoin_tier(request: Request, current_user = Depends(require_user)):
    data = await request.json()
    tier_id = data.get("tier_id")
    
    if not current_user.get("roblox_id"):
        raise HTTPException(400, "Link Roblox account first")
    
    tier = supabase.table("robux_tiers").select("*").eq("id", tier_id).execute()
    if not tier.data:
        raise HTTPException(404, "Tier not found")
    
    session_id = f"{current_user['id']}_{datetime.utcnow().timestamp()}"
    verification_sessions[session_id] = {
        "user_id": current_user["id"],
        "roblox_id": current_user["roblox_id"],
        "game_pass_id": tier.data[0]["game_pass_id"],
        "xcoin_amount": tier.data[0]["xcoin_amount"],
        "tier_name": tier.data[0]["display_name"],
        "created_at": datetime.utcnow().isoformat()
    }
    
    return {"session_id": session_id, "tier": tier.data[0]}

@app.post("/api/xcoin/verify")
async def verify_xcoin(request: Request, current_user = Depends(require_user)):
    data = await request.json()
    session_id = data.get("session_id")
    
    session = verification_sessions.get(session_id)
    if not session or session["user_id"] != current_user["id"]:
        raise HTTPException(404, "Session not found")
    
    verified = await verify_roblox_game_pass(current_user["roblox_id"], session["game_pass_id"])
    if not verified:
        return {"success": False, "message": "Game pass not found"}
    
    new_balance = current_user["x_coin_balance"] + session["xcoin_amount"]
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", current_user["id"]).execute()
    supabase.table("xcoin_transactions").insert({
        "user_id": current_user["id"],
        "amount": session["xcoin_amount"],
        "reason": f"Purchased: {session['tier_name']}"
    }).execute()
    
    del verification_sessions[session_id]
    return {"success": True, "xcoin_amount": session["xcoin_amount"], "new_balance": new_balance}

@app.get("/api/xcoin/transactions")
async def get_xcoin_transactions(current_user = Depends(require_user)):
    return supabase.table("xcoin_transactions").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).limit(50).execute().data

# ==================== RATES ====================

@app.get("/api/rates")
async def get_rates():
    return {"xcoin_per_robux": settings.ROBUX_TO_XCOIN_RATE, "robux_per_usd": settings.ROBUX_TO_USD_RATE, "xcoin_per_usd": settings.XCOIN_TO_USD_RATE}

# ==================== UPDATES ====================

@app.get("/api/updates")
async def get_updates():
    return supabase.table("updates").select("*").order("created_at", desc=True).limit(10).execute().data

@app.post("/api/admin/updates", dependencies=[Depends(require_owner)])
async def create_update(update: UpdateCreate):
    return supabase.table("updates").insert({
        "title": update.title,
        "content": update.content,
        "created_at": datetime.utcnow().isoformat()
    }).execute().data[0]

@app.delete("/api/admin/updates/{update_id}", dependencies=[Depends(require_owner)])
async def delete_update(update_id: int):
    supabase.table("updates").delete().eq("id", update_id).execute()
    return {"message": "Deleted"}

# ==================== ADMIN ROUTES ====================

@app.get("/api/admin/analytics", dependencies=[Depends(require_owner)])
async def admin_analytics():
    orders = supabase.table("orders").select("total_usd, status, created_at").execute()
    completed_orders = [o for o in orders.data if o["status"] == "completed"]
    total_sales = sum(o["total_usd"] for o in completed_orders)
    
    # 30 days
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    recent_sales = sum(o["total_usd"] for o in completed_orders if o["created_at"] > thirty_days_ago)
    
    # 7 days
    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    week_sales = sum(o["total_usd"] for o in completed_orders if o["created_at"] > seven_days_ago)
    
    # Today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0).isoformat()
    today_sales = sum(o["total_usd"] for o in completed_orders if o["created_at"] > today_start)
    
    users = supabase.table("users").select("id").execute()
    products = supabase.table("products").select("id").eq("is_active", True).execute()
    xcoin = supabase.table("users").select("x_coin_balance").execute()
    total_xcoin = sum(x["x_coin_balance"] for x in xcoin.data)
    
    # Top products
    items = supabase.table("order_items").select("product_id, quantity").execute()
    product_sales = {}
    for item in items.data:
        product_sales[item["product_id"]] = product_sales.get(item["product_id"], 0) + item["quantity"]
    
    top_products = []
    for pid, qty in sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]:
        prod = supabase.table("products").select("title").eq("id", pid).execute()
        if prod.data:
            top_products.append({"title": prod.data[0]["title"], "quantity_sold": qty})
    
    return {
        "sales": {
            "today": round(today_sales, 2),
            "week": round(week_sales, 2),
            "month": round(recent_sales, 2),
            "all_time": round(total_sales, 2),
            "order_count": len(completed_orders)
        },
        "users": {"total": len(users.data)},
        "products": {"total": len(products.data)},
        "xcoin": {"total_in_circulation": total_xcoin},
        "top_products": top_products
    }

@app.get("/api/admin/products", dependencies=[Depends(require_owner)])
async def admin_products():
    return supabase.table("products").select("*").order("created_at", desc=True).execute().data

@app.get("/api/admin/orders", dependencies=[Depends(require_owner)])
async def admin_orders(status: Optional[str] = None):
    query = supabase.table("orders").select("*, user:users(username, email)")
    if status:
        query = query.eq("status", status)
    return query.order("created_at", desc=True).execute().data

@app.post("/api/admin/orders/{order_id}/complete", dependencies=[Depends(require_owner)])
async def admin_complete_order(order_id: int):
    order = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not order.data:
        raise HTTPException(404, "Order not found")
    
    supabase.table("orders").update({"status": "completed"}).eq("id", order_id).execute()
    
    await send_notification(order.data[0]["user_id"], "Order Completed", f"Order #{order_id} has been completed!")
    await discord_service.send_admin_alert("order_completed", {"Order": order_id, "User": order.data[0]["user_id"]})
    
    return {"message": "Order completed"}

@app.post("/api/admin/orders/refund", dependencies=[Depends(require_owner)])
async def admin_refund_order(refund_data: RefundOrder):
    order_response = supabase.table("orders").select("*").eq("id", refund_data.order_id).execute()
    if not order_response.data:
        raise HTTPException(404, "Order not found")
    
    order = order_response.data[0]
    if order["status"] == "refunded":
        raise HTTPException(400, "Order already refunded")
    
    refund_x_coin = int(order["total_usd"] * settings.XCOIN_TO_USD_RATE)
    
    user = supabase.table("users").select("x_coin_balance").eq("id", order["user_id"]).execute()
    new_balance = user.data[0]["x_coin_balance"] + refund_x_coin
    
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", order["user_id"]).execute()
    supabase.table("xcoin_transactions").insert({
        "user_id": order["user_id"],
        "order_id": order["id"],
        "amount": refund_x_coin,
        "reason": f"Refund for order #{order['id']}: {refund_data.reason}"
    }).execute()
    
    supabase.table("orders").update({"status": "refunded"}).eq("id", refund_data.order_id).execute()
    
    await send_notification(order["user_id"], "Order Refunded", f"Order #{order['id']} has been refunded. You received {refund_x_coin} X Coin.")
    await discord_service.send_admin_alert("refund", {"Order": refund_data.order_id, "Reason": refund_data.reason, "Amount": refund_x_coin})
    
    return {"message": f"Refunded {refund_x_coin} X Coin", "xcoin_refunded": refund_x_coin}

@app.get("/api/admin/users", dependencies=[Depends(require_owner)])
async def admin_users():
    return supabase.table("users").select("*").order("created_at", desc=True).execute().data

@app.post("/api/admin/users/xcoin", dependencies=[Depends(require_owner)])
async def admin_adjust_xcoin(adj: XCoinAdjustment):
    user = supabase.table("users").select("x_coin_balance").eq("id", adj.user_id).execute()
    if not user.data:
        raise HTTPException(404, "User not found")
    new_balance = user.data[0]["x_coin_balance"] + adj.amount
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", adj.user_id).execute()
    supabase.table("xcoin_transactions").insert({
        "user_id": adj.user_id,
        "amount": adj.amount,
        "reason": f"Admin: {adj.reason}"
    }).execute()
    
    await discord_service.send_admin_alert("xcoin_adjustment", {"User": adj.user_id, "Amount": adj.amount, "Reason": adj.reason})
    return {"new_balance": new_balance}

@app.post("/api/admin/users/{user_id}/ban", dependencies=[Depends(require_owner)])
async def admin_ban_user(user_id: str):
    user = supabase.table("users").select("is_banned").eq("id", user_id).execute()
    if not user.data:
        raise HTTPException(404, "User not found")
    new_status = not user.data[0]["is_banned"]
    supabase.table("users").update({"is_banned": new_status}).eq("id", user_id).execute()
    
    await discord_service.send_admin_alert("user_ban", {"User": user_id, "Banned": new_status})
    return {"banned": new_status}

@app.get("/api/admin/robux-tiers", dependencies=[Depends(require_owner)])
async def admin_robux_tiers():
    return supabase.table("robux_tiers").select("*").order("robux_cost").execute().data

@app.post("/api/admin/robux-tiers", dependencies=[Depends(require_owner)])
async def admin_create_tier(tier: RobuxTierCreate):
    return supabase.table("robux_tiers").insert({
        "robux_cost": tier.robux_cost,
        "xcoin_amount": tier.xcoin_amount,
        "game_pass_id": tier.game_pass_id,
        "game_pass_url": tier.game_pass_url,
        "display_name": tier.display_name,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }).execute().data[0]

@app.put("/api/admin/robux-tiers/{tier_id}", dependencies=[Depends(require_owner)])
async def admin_update_tier(tier_id: int, tier: RobuxTierCreate):
    return supabase.table("robux_tiers").update({
        "robux_cost": tier.robux_cost,
        "xcoin_amount": tier.xcoin_amount,
        "game_pass_id": tier.game_pass_id,
        "game_pass_url": tier.game_pass_url,
        "display_name": tier.display_name
    }).eq("id", tier_id).execute().data[0]

@app.delete("/api/admin/robux-tiers/{tier_id}", dependencies=[Depends(require_owner)])
async def admin_delete_tier(tier_id: int):
    supabase.table("robux_tiers").update({"is_active": False}).eq("id", tier_id).execute()
    return {"message": "Deleted"}

@app.get("/api/admin/exchange-rates", dependencies=[Depends(require_owner)])
async def admin_rates():
    return {"xcoin_per_robux": settings.ROBUX_TO_XCOIN_RATE, "robux_per_usd": settings.ROBUX_TO_USD_RATE}

@app.put("/api/admin/exchange-rates", dependencies=[Depends(require_owner)])
async def admin_update_rates(rates: dict):
    settings.ROBUX_TO_XCOIN_RATE = rates.get("xcoin_per_robux", settings.ROBUX_TO_XCOIN_RATE)
    settings.ROBUX_TO_USD_RATE = rates.get("robux_per_usd", settings.ROBUX_TO_USD_RATE)
    return {"message": "Rates updated"}

@app.get("/api/admin/coupons", dependencies=[Depends(require_owner)])
async def admin_coupons():
    coupons = supabase.table("coupons").select("*").order("created_at", desc=True).execute().data
    for c in coupons:
        uses = supabase.table("orders").select("id").eq("coupon_code", c["code"]).execute()
        c["used_count"] = len(uses.data)
    return coupons

@app.get("/api/admin/logs", dependencies=[Depends(require_owner)])
async def admin_logs(limit: int = 100):
    return supabase.table("logs").select("*, user:users(username)").order("created_at", desc=True).limit(limit).execute().data

# ==================== WEBSOCKET ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            try:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            except ValueError:
                pass
    
    async def send(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send_json(message)
                except:
                    pass

manager = ConnectionManager()

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008)
            return
        await manager.connect(websocket, user_id)
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

# ==================== HEALTH ====================

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ==================== INITIAL DATABASE SETUP ====================

@app.on_event("startup")
async def startup():
    """Initialize database with default data if empty"""
    # Check if products are empty
    products = supabase.table("products").select("id").limit(1).execute()
    if not products.data:
        # Add default products from templates
        for template in PRODUCT_TEMPLATES.values():
            supabase.table("products").insert({
                "title": template["title"],
                "description": template["description"],
                "category": template["category"],
                "price_usd": template["price_usd"],
                "stock": 100,
                "image_url": template["image_url"],
                "is_active": True,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
        logger.info("Default products added")
    
    # Check if robux tiers are empty
    tiers = supabase.table("robux_tiers").select("id").limit(1).execute()
    if not tiers.data:
        default_tiers = [
            {"robux_cost": 80, "xcoin_amount": 800, "game_pass_id": "YOUR_PASS_ID_1", "game_pass_url": "https://www.roblox.com/game-pass/YOUR_PASS_ID_1", "display_name": "$1 Pack (80 Robux → 800 XC)"},
            {"robux_cost": 400, "xcoin_amount": 5000, "game_pass_id": "YOUR_PASS_ID_5", "game_pass_url": "https://www.roblox.com/game-pass/YOUR_PASS_ID_5", "display_name": "$5 Pack (400 Robux → 5,000 XC + Bonus)"},
            {"robux_cost": 800, "xcoin_amount": 11000, "game_pass_id": "YOUR_PASS_ID_10", "game_pass_url": "https://www.roblox.com/game-pass/YOUR_PASS_ID_10", "display_name": "$10 Pack (800 Robux → 11,000 XC + Bonus)"},
            {"robux_cost": 4000, "xcoin_amount": 60000, "game_pass_id": "YOUR_PASS_ID_50", "game_pass_url": "https://www.roblox.com/game-pass/YOUR_PASS_ID_50", "display_name": "$50 Pack (4,000 Robux → 60,000 XC + Bonus)"},
            {"robux_cost": 8000, "xcoin_amount": 120000, "game_pass_id": "YOUR_PASS_ID_100", "game_pass_url": "https://www.roblox.com/game-pass/YOUR_PASS_ID_100", "display_name": "$100 Pack (8,000 Robux → 120,000 XC + Bonus)"}
        ]
        for tier in default_tiers:
            supabase.table("robux_tiers").insert(tier).execute()
        logger.info("Default Robux tiers added")
