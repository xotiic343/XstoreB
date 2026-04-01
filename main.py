"""
Xstore - Complete Digital Marketplace
Single-file FastAPI backend with Supabase integration
"""

import os
import asyncio
import httpx
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Depends, status, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from jose import JWTError, jwt
from passlib.context import CryptContext
from supabase import create_client, Client

load_dotenv()

# ==================== CONFIGURATION ====================

class Settings:
    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    
    # Payment Gateways
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
    PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    
    # Email
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    
    # Roblox
    ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
    
    # Frontend
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    
    # Exchange Rates
    ROBUX_TO_XCOIN_RATE = int(os.getenv("ROBUX_TO_XCOIN_RATE", 10))
    XCOIN_TO_USD_RATE = int(os.getenv("XCOIN_TO_USD_RATE", 100))
    ROBUX_TO_USD_RATE = int(os.getenv("ROBUX_TO_USD_RATE", 80))
    
    # Admin
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@xstore.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    
    # Render
    RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
    
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))

settings = Settings()

# ==================== SUPABASE CLIENT ====================

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# ==================== AUTH SETUP ====================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
verification_sessions: Dict[str, dict] = {}

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        
        user_response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(status_code=401, detail="User not found")
        
        user = user_response.data[0]
        if user.get("is_banned"):
            raise HTTPException(status_code=403, detail="User is banned")
        
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication")

async def get_current_owner(current_user = Depends(get_current_user)):
    if not current_user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# ==================== PYDANTIC SCHEMAS ====================

class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class LinkRoblox(BaseModel):
    roblox_id: str
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

class BuyXCoinRequest(BaseModel):
    robux_amount: int
    game_pass_ids: List[str]

class XCoinAdjustment(BaseModel):
    user_id: str
    amount: int
    reason: str

class RefundOrder(BaseModel):
    order_id: int
    reason: str

# ==================== ROBLOX VERIFICATION ====================

async def verify_roblox_game_pass(roblox_id: str, game_pass_id: str) -> bool:
    try:
        url = f"https://inventory.roblox.com/v1/users/{roblox_id}/items/GamePass/{game_pass_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return data.get('data') and len(data['data']) > 0
            return False
    except Exception:
        return False

async def verify_multiple_passes(roblox_id: str, game_pass_ids: List[str]) -> Dict[str, bool]:
    results = {}
    for pass_id in game_pass_ids:
        results[pass_id] = await verify_roblox_game_pass(roblox_id, pass_id)
    return results

async def verification_worker(session_id: str, user_id: str, roblox_id: str, game_pass_ids: List[str], total_robux: int):
    session = verification_sessions.get(session_id)
    if not session:
        return
    
    start_time = datetime.utcnow()
    expiry_time = start_time + timedelta(minutes=2)
    
    while datetime.utcnow() < expiry_time:
        if session.get("cancelled"):
            session["status"] = "cancelled"
            session["message"] = "Verification cancelled by user"
            return
        
        verification_results = await verify_multiple_passes(roblox_id, game_pass_ids)
        all_verified = all(verification_results.values())
        
        if all_verified:
            xcoin_amount = total_robux * settings.ROBUX_TO_XCOIN_RATE
            
            user_response = supabase.table("users").select("x_coin_balance").eq("id", user_id).execute()
            current_balance = user_response.data[0]["x_coin_balance"]
            new_balance = current_balance + xcoin_amount
            
            supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", user_id).execute()
            supabase.table("xcoin_transactions").insert({
                "user_id": user_id, "amount": xcoin_amount,
                "reason": f"Purchased with {total_robux} Robux", "created_at": datetime.utcnow().isoformat()
            }).execute()
            supabase.table("logs").insert({
                "user_id": user_id, "action": "xcoin_purchased",
                "details": f"Bought {xcoin_amount} X Coin with {total_robux} Robux",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            
            session["status"] = "verified"
            session["xcoin_amount"] = xcoin_amount
            session["new_balance"] = new_balance
            session["message"] = "Verification successful!"
            return
        
        session["status"] = "pending"
        session["verification_results"] = verification_results
        await asyncio.sleep(3)
    
    session["status"] = "expired"
    session["message"] = "Verification timeout"

# ==================== FASTAPI APP ====================

app = FastAPI(title="Xstore API", version="1.0.0")

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
        "email": user_data.email, "password": user_data.password,
        "options": {"data": {"username": user_data.username}}
    })
    
    is_owner = user_data.email == settings.ADMIN_EMAIL
    supabase.table("users").insert({
        "id": auth_response.user.id, "email": user_data.email, "username": user_data.username,
        "x_coin_balance": 0, "is_owner": is_owner, "is_banned": False,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    access_token = create_access_token({"sub": auth_response.user.id})
    return {"access_token": access_token, "token_type": "bearer",
            "user": {"id": auth_response.user.id, "email": user_data.email, "username": user_data.username,
                     "x_coin_balance": 0, "is_owner": is_owner}}

@app.post("/api/auth/login")
async def login(login_data: UserLogin):
    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": login_data.email, "password": login_data.password
        })
        user_response = supabase.table("users").select("*").eq("id", auth_response.user.id).execute()
        if not user_response.data:
            raise HTTPException(404, "User not found")
        user = user_response.data[0]
        if user.get("is_banned"):
            raise HTTPException(403, "User is banned")
        
        access_token = create_access_token({"sub": auth_response.user.id})
        return {"access_token": access_token, "token_type": "bearer",
                "user": {"id": user["id"], "email": user["email"], "username": user["username"],
                         "x_coin_balance": user["x_coin_balance"], "is_owner": user["is_owner"],
                         "roblox_id": user.get("roblox_id"), "roblox_username": user.get("roblox_username")}}
    except Exception:
        raise HTTPException(401, "Invalid credentials")

@app.get("/api/auth/me")
async def get_me(current_user = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "username": current_user["username"],
            "x_coin_balance": current_user["x_coin_balance"], "is_owner": current_user["is_owner"],
            "roblox_id": current_user.get("roblox_id"), "roblox_username": current_user.get("roblox_username")}

@app.post("/api/auth/link-roblox")
async def link_roblox(data: LinkRoblox, current_user = Depends(get_current_user)):
    supabase.table("users").update({"roblox_id": data.roblox_id, "roblox_username": data.roblox_username}).eq("id", current_user["id"]).execute()
    return {"message": "Roblox account linked"}

# ==================== PRODUCT ROUTES ====================

@app.get("/api/products")
async def get_products(search: Optional[str] = None, category: Optional[str] = None,
                       min_price: Optional[float] = None, max_price: Optional[float] = None,
                       in_stock: Optional[bool] = None, limit: int = 50, offset: int = 0):
    query = supabase.table("products").select("*")
    if search: query = query.ilike("title", f"%{search}%")
    if category: query = query.eq("category", category)
    if min_price: query = query.gte("price_usd", min_price)
    if max_price: query = query.lte("price_usd", max_price)
    if in_stock: query = query.gt("stock", 0)
    query = query.range(offset, offset + limit - 1).order("created_at", desc=True)
    return query.execute().data

@app.get("/api/products/categories")
async def get_categories():
    response = supabase.table("products").select("category").execute()
    return list(set([item["category"] for item in response.data]))

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    response = supabase.table("products").select("*").eq("id", product_id).execute()
    if not response.data:
        raise HTTPException(404, "Product not found")
    return response.data[0]

@app.post("/api/products", dependencies=[Depends(get_current_owner)])
async def create_product(product: ProductCreate):
    response = supabase.table("products").insert(product.dict()).execute()
    return response.data[0]

@app.put("/api/products/{product_id}", dependencies=[Depends(get_current_owner)])
async def update_product(product_id: int, product: ProductUpdate):
    update_data = {k: v for k, v in product.dict().items() if v is not None}
    response = supabase.table("products").update(update_data).eq("id", product_id).execute()
    if not response.data:
        raise HTTPException(404, "Product not found")
    return response.data[0]

@app.delete("/api/products/{product_id}", dependencies=[Depends(get_current_owner)])
async def delete_product(product_id: int):
    supabase.table("products").delete().eq("id", product_id).execute()
    return {"message": "Product deleted"}

# ==================== ORDER ROUTES ====================

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, current_user = Depends(get_current_user)):
    products = []
    total_usd = 0
    
    for item in order_data.items:
        product_response = supabase.table("products").select("*").eq("id", item.product_id).execute()
        if not product_response.data:
            raise HTTPException(404, f"Product {item.product_id} not found")
        product = product_response.data[0]
        if product["stock"] < item.quantity:
            raise HTTPException(400, f"Insufficient stock for {product['title']}")
        products.append({**product, "quantity": item.quantity})
        total_usd += product["price_usd"] * item.quantity
    
    total_xcoin = int(total_usd * settings.XCOIN_TO_USD_RATE)
    x_coin_used = 0
    remaining_usd = total_usd
    
    if order_data.payment_method == "xcoin":
        if order_data.x_coin_amount > current_user["x_coin_balance"]:
            raise HTTPException(400, "Insufficient X Coin balance")
        x_coin_used = order_data.x_coin_amount
        remaining_usd = total_usd - (x_coin_used / settings.XCOIN_TO_USD_RATE)
        if remaining_usd < 0:
            remaining_usd = 0
    
    order = {
        "user_id": current_user["id"], "total_usd": total_usd, "total_xcoin": total_xcoin,
        "x_coin_used": x_coin_used, "remaining_usd": remaining_usd,
        "payment_method": order_data.payment_method, "status": "completed" if remaining_usd == 0 else "pending_payment",
        "created_at": datetime.utcnow().isoformat()
    }
    
    order_response = supabase.table("orders").insert(order).execute()
    order_id = order_response.data[0]["id"]
    
    for product in products:
        supabase.table("order_items").insert({
            "order_id": order_id, "product_id": product["id"], "quantity": product["quantity"],
            "price_usd_at_time": product["price_usd"],
            "price_xcoin_at_time": int(product["price_usd"] * settings.XCOIN_TO_USD_RATE)
        }).execute()
    
    if x_coin_used > 0:
        new_balance = current_user["x_coin_balance"] - x_coin_used
        supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", current_user["id"]).execute()
        supabase.table("xcoin_transactions").insert({
            "user_id": current_user["id"], "order_id": order_id, "amount": -x_coin_used,
            "reason": f"Used for order #{order_id}", "created_at": datetime.utcnow().isoformat()
        }).execute()
    
    for product in products:
        new_stock = product["stock"] - product["quantity"]
        supabase.table("products").update({"stock": new_stock}).eq("id", product["id"]).execute()
    
    return {"order_id": order_id, "status": order["status"], "total_usd": total_usd,
            "x_coin_used": x_coin_used, "remaining_usd": remaining_usd}

@app.get("/api/orders")
async def get_my_orders(current_user = Depends(get_current_user)):
    response = supabase.table("orders").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).execute()
    orders = []
    for order in response.data:
        items = supabase.table("order_items").select("*, product:products(*)").eq("order_id", order["id"]).execute()
        order["items"] = items.data
        orders.append(order)
    return orders

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int, current_user = Depends(get_current_user)):
    response = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not response.data:
        raise HTTPException(404, "Order not found")
    order = response.data[0]
    if order["user_id"] != current_user["id"] and not current_user.get("is_owner"):
        raise HTTPException(403, "Access denied")
    items = supabase.table("order_items").select("*, product:products(*)").eq("order_id", order_id).execute()
    order["items"] = items.data
    return order

# ==================== X COIN ROUTES ====================

@app.get("/api/xcoin/balance")
async def get_xcoin_balance(current_user = Depends(get_current_user)):
    return {"balance": current_user["x_coin_balance"], "robux_to_xcoin_rate": settings.ROBUX_TO_XCOIN_RATE,
            "xcoin_to_usd_rate": settings.XCOIN_TO_USD_RATE}

@app.get("/api/xcoin/packages")
async def get_xcoin_packages(current_user = Depends(get_current_user)):
    response = supabase.table("xcoin_packages").select("*").eq("is_active", True).order("display_order").execute()
    for pkg in response.data:
        pkg["usd_equivalent"] = pkg["robux_cost"] / settings.ROBUX_TO_USD_RATE
    return response.data

@app.post("/api/xcoin/buy")
async def buy_xcoin_with_robux(purchase: BuyXCoinRequest, background_tasks: BackgroundTasks,
                                current_user = Depends(get_current_user)):
    if not current_user.get("roblox_id"):
        raise HTTPException(400, "Please link your Roblox account first")
    
    packages_response = supabase.table("xcoin_packages").select("*").execute()
    available_packages = {pkg["game_pass_id"]: pkg for pkg in packages_response.data}
    
    total_robux = 0
    for pass_id in purchase.game_pass_ids:
        if pass_id not in available_packages:
            raise HTTPException(400, f"Invalid game pass ID: {pass_id}")
        total_robux += available_packages[pass_id]["robux_cost"]
    
    if total_robux != purchase.robux_amount:
        raise HTTPException(400, "Robux amount doesn't match selected packages")
    
    session_id = f"{current_user['id']}_{datetime.utcnow().timestamp()}"
    verification_sessions[session_id] = {
        "status": "pending", "user_id": current_user["id"], "roblox_id": current_user["roblox_id"],
        "game_pass_ids": purchase.game_pass_ids, "total_robux": purchase.robux_amount,
        "created_at": datetime.utcnow().isoformat(), "cancelled": False
    }
    
    background_tasks.add_task(verification_worker, session_id, current_user["id"],
                              current_user["roblox_id"], purchase.game_pass_ids, purchase.robux_amount)
    
    return {"session_id": session_id, "status": "pending", "message": "Verification started",
            "game_pass_ids": purchase.game_pass_ids, "total_robux": purchase.robux_amount, "expires_in": 120}

@app.get("/api/xcoin/verify/{session_id}")
async def check_verification_status(session_id: str, current_user = Depends(get_current_user)):
    session = verification_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["user_id"] != current_user["id"]:
        raise HTTPException(403, "Access denied")
    
    created_at = datetime.fromisoformat(session["created_at"])
    remaining_time = max(0, int((created_at + timedelta(minutes=2) - datetime.utcnow()).total_seconds()))
    
    response = {"session_id": session_id, "status": session["status"], "remaining_time": remaining_time,
                "message": session.get("message", "")}
    if session["status"] == "verified":
        response["xcoin_amount"] = session.get("xcoin_amount")
        response["new_balance"] = session.get("new_balance")
    elif session["status"] == "pending":
        response["verification_results"] = session.get("verification_results", {})
        response["game_pass_ids"] = session.get("game_pass_ids", [])
    return response

# ==================== ADMIN ROUTES ====================

@app.get("/api/admin/analytics", dependencies=[Depends(get_current_owner)])
async def admin_get_analytics():
    sales = supabase.table("orders").select("total_usd, status").execute()
    total_usd = sum(o["total_usd"] for o in sales.data if o["status"] == "completed")
    
    items = supabase.table("order_items").select("product_id, quantity").execute()
    product_sales = {}
    for item in items.data:
        product_sales[item["product_id"]] = product_sales.get(item["product_id"], 0) + item["quantity"]
    
    top_products = []
    for pid, qty in sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]:
        prod = supabase.table("products").select("title").eq("id", pid).execute()
        if prod.data:
            top_products.append({"title": prod.data[0]["title"], "quantity_sold": qty})
    
    xcoin = supabase.table("users").select("x_coin_balance").execute()
    total_xcoin = sum(u["x_coin_balance"] for u in xcoin.data)
    avg_xcoin = total_xcoin / len(xcoin.data) if xcoin.data else 0
    
    return {"total_sales_usd": total_usd, "top_products": top_products,
            "x_coin_stats": {"total_in_circulation": total_xcoin, "average_balance": avg_xcoin},
            "refund_count": len([o for o in sales.data if o["status"] == "refunded"]),
            "total_orders": len(sales.data)}

@app.get("/api/admin/orders", dependencies=[Depends(get_current_owner)])
async def admin_get_orders(status: Optional[str] = None):
    query = supabase.table("orders").select("*, user:users(email, username)")
    if status:
        query = query.eq("status", status)
    return query.order("created_at", desc=True).execute().data

@app.post("/api/admin/orders/refund", dependencies=[Depends(get_current_owner)])
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
        "user_id": order["user_id"], "order_id": order["id"], "amount": refund_x_coin,
        "reason": f"Refund for order #{order['id']}: {refund_data.reason}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    supabase.table("orders").update({"status": "refunded"}).eq("id", refund_data.order_id).execute()
    
    return {"message": f"Refunded {refund_x_coin} X Coin"}

@app.get("/api/admin/users", dependencies=[Depends(get_current_owner)])
async def admin_get_users():
    return supabase.table("users").select("*").order("created_at", desc=True).execute().data

@app.post("/api/admin/users/xcoin", dependencies=[Depends(get_current_owner)])
async def admin_adjust_xcoin(adjustment: XCoinAdjustment):
    user = supabase.table("users").select("x_coin_balance").eq("id", adjustment.user_id).execute()
    if not user.data:
        raise HTTPException(404, "User not found")
    
    new_balance = user.data[0]["x_coin_balance"] + adjustment.amount
    if new_balance < 0:
        raise HTTPException(400, "Balance cannot be negative")
    
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", adjustment.user_id).execute()
    supabase.table("xcoin_transactions").insert({
        "user_id": adjustment.user_id, "amount": adjustment.amount,
        "reason": f"Admin adjustment: {adjustment.reason}", "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": f"Balance updated to {new_balance}"}

@app.get("/api/admin/xcoin-packages", dependencies=[Depends(get_current_owner)])
async def admin_get_xcoin_packages():
    return supabase.table("xcoin_packages").select("*").order("display_order").execute().data

@app.post("/api/admin/xcoin-packages", dependencies=[Depends(get_current_owner)])
async def admin_create_xcoin_package(package_data: dict):
    if package_data["robux_cost"] <= 0 or package_data["xcoin_amount"] <= 0:
        raise HTTPException(400, "Values must be positive")
    response = supabase.table("xcoin_packages").insert(package_data).execute()
    return response.data[0]

@app.put("/api/admin/xcoin-packages/{package_id}", dependencies=[Depends(get_current_owner)])
async def admin_update_xcoin_package(package_id: int, package_data: dict):
    response = supabase.table("xcoin_packages").update(package_data).eq("id", package_id).execute()
    if not response.data:
        raise HTTPException(404, "Package not found")
    return response.data[0]

@app.delete("/api/admin/xcoin-packages/{package_id}", dependencies=[Depends(get_current_owner)])
async def admin_delete_xcoin_package(package_id: int):
    supabase.table("xcoin_packages").delete().eq("id", package_id).execute()
    return {"message": "Package deleted"}

@app.get("/api/admin/logs", dependencies=[Depends(get_current_owner)])
async def admin_get_logs(limit: int = 100, offset: int = 0):
    response = supabase.table("logs").select("*, user:users(username)").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return response.data

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {"message": "Xstore API", "version": "1.0.0"}
