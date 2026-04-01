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
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
import threading
import time
from collections import deque

import httpx
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks, WebSocket, WebSocketDisconnect, Query, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, validator
from jose import JWTError, jwt
from passlib.context import CryptContext
from supabase import create_client, Client
from dotenv import load_dotenv

# SendGrid imports
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment
from sendgrid.helpers.mail import Mail as SendGridMail

load_dotenv()

# ==================== CONFIGURATION ====================

class Settings:
    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    
    # SendGrid
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")
    SENDGRID_FROM_NAME = os.getenv("SENDGRID_FROM_NAME")
    
    # Discord OAuth
    DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
    DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
    DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
    
    # Payment Gateways
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
    PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
    PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID")
    
    # CashApp
    CASHAPP_CASHTAG = os.getenv("CASHAPP_CASHTAG", "$XStore")
    
    # Roblox
    ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
    
    # Frontend
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    
    # Exchange Rates
    ROBUX_TO_XCOIN_RATE = int(os.getenv("ROBUX_TO_XCOIN_RATE", 10))
    XCOIN_TO_USD_RATE = int(os.getenv("XCOIN_TO_USD_RATE", 100))
    ROBUX_TO_USD_RATE = int(os.getenv("ROBUX_TO_USD_RATE", 80))
    
    # Affiliate
    AFFILIATE_COMMISSION_PERCENT = int(os.getenv("AFFILIATE_COMMISSION_PERCENT", 10))
    AFFILIATE_COOKIE_DAYS = int(os.getenv("AFFILIATE_COOKIE_DAYS", 30))
    
    # Admin
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24 * 7))
    
    # Supported Languages
    SUPPORTED_LANGUAGES = ["en", "es", "fr", "de", "ja", "zh", "ru", "pt", "ar", "hi"]
    DEFAULT_LANGUAGE = "en"
    
    # Welcome Bonus
    WELCOME_BONUS_XCOIN = int(os.getenv("WELCOME_BONUS_XCOIN", 100))

settings = Settings()

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== SUPABASE CLIENT ====================

supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# ==================== AUTH SETUP ====================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Verification sessions storage
verification_sessions: Dict[str, dict] = {}
websocket_connections: Dict[str, List[WebSocket]] = []

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

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not credentials:
        return None
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        user_response = supabase.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            return None
        
        user = user_response.data[0]
        if user.get("is_banned"):
            return None
        
        return user
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

# ==================== SENDGRID EMAIL SERVICE ====================

class SendGridEmailService:
    """Professional email service using SendGrid"""
    
    def __init__(self, api_key: str, from_email: str, from_name: str):
        self.client = sendgrid.SendGridAPIClient(api_key=api_key)
        self.from_email = from_email
        self.from_name = from_name
        self.sent_count = 0
        self.failed_count = 0
        
    def send_email(self, to_email: str, to_name: str, subject: str, html_content: str, 
                   plain_text: str = None, attachments: List[Dict] = None) -> bool:
        """Send a single email via SendGrid"""
        try:
            message = Mail(
                from_email=Email(self.from_email, self.from_name),
                to_emails=To(to_email, to_name),
                subject=subject,
                html_content=html_content
            )
            
            if plain_text:
                message.plain_text_content = plain_text
            
            if attachments:
                for attachment in attachments:
                    encoded = base64.b64encode(attachment['content'].encode()).decode()
                    message.attachment = Attachment(
                        file_content=encoded,
                        file_name=attachment['filename'],
                        file_type=attachment.get('type', 'application/octet-stream'),
                        disposition='attachment'
                    )
            
            response = self.client.send(message)
            
            if response.status_code in [202, 200]:
                self.sent_count += 1
                logger.info(f"Email sent to {to_email}: {subject}")
                return True
            else:
                self.failed_count += 1
                logger.error(f"SendGrid error {response.status_code}: {response.body}")
                return False
                
        except Exception as e:
            self.failed_count += 1
            logger.error(f"Failed to send email: {e}")
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Get email statistics"""
        return {
            'total_sent': self.sent_count,
            'total_failed': self.failed_count
        }

# ==================== EMAIL TEMPLATES ====================

class EmailTemplates:
    """HTML email templates for different use cases"""
    
    @staticmethod
    def welcome_email(username: str, xcoin_bonus: int, dashboard_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
                    line-height: 1.6;
                    color: #333;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }}
                .content {{
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.1);
                }}
                .logo {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo h1 {{
                    font-size: 36px;
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    margin: 0;
                }}
                .welcome-badge {{
                    background: linear-gradient(135deg, #f59e0b, #fbbf24);
                    color: white;
                    padding: 20px;
                    border-radius: 12px;
                    text-align: center;
                    margin: 30px 0;
                }}
                .welcome-badge .xcoin-amount {{
                    font-size: 48px;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 30px;
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    margin-top: 20px;
                    font-weight: 600;
                }}
                .features {{
                    margin: 30px 0;
                    padding: 0;
                    list-style: none;
                }}
                .features li {{
                    padding: 10px 0;
                    border-bottom: 1px solid #eee;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    font-size: 12px;
                    color: #999;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="content">
                    <div class="logo">
                        <h1>✨ XSTORE ✨</h1>
                    </div>
                    
                    <h2>Welcome {username}!</h2>
                    
                    <p>Thank you for joining XStore! We're excited to have you as part of our digital marketplace community.</p>
                    
                    <div class="welcome-badge">
                        🎁 <strong>Welcome Gift</strong>
                        <div class="xcoin-amount">⚡ +{xcoin_bonus} X Coin</div>
                        <div>Added to your account!</div>
                    </div>
                    
                    <h3>What you can do:</h3>
                    <ul class="features">
                        <li>🛍️ Browse thousands of digital products</li>
                        <li>⚡ Earn X Coin with every purchase</li>
                        <li>🎮 Link your Roblox account for instant purchases</li>
                        <li>💸 Earn affiliate commissions by referring friends</li>
                        <li>🎫 Use discount codes for extra savings</li>
                    </ul>
                    
                    <center>
                        <a href="{dashboard_url}" class="button">Start Shopping →</a>
                    </center>
                    
                    <div class="footer">
                        <p>Need help? Contact us at support@xstore.com</p>
                        <p>© 2024 XStore. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def order_confirmation(username: str, order_id: int, items_html: str, total_usd: float, 
                          payment_method: str, status: str, dashboard_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    border-bottom: 2px solid #667eea;
                    padding-bottom: 20px;
                    margin-bottom: 30px;
                }}
                .order-details {{
                    background: #f8f9fa;
                    border-radius: 12px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .item {{
                    padding: 10px 0;
                    border-bottom: 1px solid #e0e0e0;
                }}
                .total {{
                    font-size: 20px;
                    font-weight: bold;
                    color: #667eea;
                    margin-top: 15px;
                    text-align: right;
                }}
                .status-badge {{
                    display: inline-block;
                    padding: 4px 12px;
                    background: #10b981;
                    color: white;
                    border-radius: 20px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    margin-top: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>✅ Order Confirmed!</h2>
                    <p>Order #{order_id}</p>
                    <span class="status-badge">{status}</span>
                </div>
                
                <p>Hello {username},</p>
                <p>Your order has been confirmed and is being processed.</p>
                
                <div class="order-details">
                    <h3>Order Items:</h3>
                    {items_html}
                    <div class="total">Total: ${total_usd:.2f}</div>
                    <div>Payment Method: {payment_method}</div>
                </div>
                
                <center>
                    <a href="{dashboard_url}" class="button">View Order Details →</a>
                </center>
                
                <p style="margin-top: 30px; font-size: 12px; color: #999; text-align: center;">
                    Thank you for shopping with XStore!
                </p>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def xcoin_purchase(username: str, xcoin_amount: int, new_balance: int, 
                       purchase_method: str, dashboard_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                }}
                .xcoin-card {{
                    background: linear-gradient(135deg, #f59e0b, #fbbf24);
                    border-radius: 16px;
                    padding: 30px;
                    text-align: center;
                    color: white;
                    margin: 30px 0;
                }}
                .xcoin-amount {{
                    font-size: 64px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .balance {{
                    background: #f8f9fa;
                    border-radius: 12px;
                    padding: 15px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>⚡ X Coin Added!</h2>
                <p>Hello {username},</p>
                
                <div class="xcoin-card">
                    <div>You received:</div>
                    <div class="xcoin-amount">+{xcoin_amount:,} X Coin</div>
                    <div>via {purchase_method}</div>
                </div>
                
                <div class="balance">
                    <strong>New Balance:</strong> {new_balance:,} X Coin
                </div>
                
                <center>
                    <a href="{dashboard_url}" class="button">View Balance →</a>
                </center>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def affiliate_commission(username: str, commission_amount: float, 
                            referral_link: str, dashboard_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                }}
                .commission-card {{
                    background: linear-gradient(135deg, #10b981, #34d399);
                    border-radius: 16px;
                    padding: 30px;
                    text-align: center;
                    color: white;
                    margin: 30px 0;
                }}
                .commission-amount {{
                    font-size: 48px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .referral-link {{
                    background: #f8f9fa;
                    border-radius: 12px;
                    padding: 15px;
                    word-break: break-all;
                    margin: 20px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>💰 New Affiliate Commission!</h2>
                <p>Hello {username},</p>
                
                <div class="commission-card">
                    <div>You earned:</div>
                    <div class="commission-amount">${commission_amount:.2f}</div>
                    <div>from a referral purchase</div>
                </div>
                
                <div class="referral-link">
                    <strong>Your Referral Link:</strong><br>
                    {referral_link}
                </div>
                
                <center>
                    <a href="{dashboard_url}" class="button">View Earnings →</a>
                </center>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def password_reset(username: str, reset_code: str, reset_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                }}
                .reset-code {{
                    background: #f8f9fa;
                    font-size: 36px;
                    font-weight: bold;
                    letter-spacing: 5px;
                    text-align: center;
                    padding: 20px;
                    border-radius: 12px;
                    margin: 30px 0;
                    font-family: monospace;
                }}
                .warning {{
                    background: #fee2e2;
                    border-left: 4px solid #ef4444;
                    padding: 15px;
                    margin: 20px 0;
                    font-size: 14px;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>🔐 Password Reset Request</h2>
                <p>Hello {username},</p>
                <p>We received a request to reset your password. Use the code below:</p>
                
                <div class="reset-code">{reset_code}</div>
                
                <p>Or click the button below:</p>
                <center>
                    <a href="{reset_url}" class="button">Reset Password →</a>
                </center>
                
                <div class="warning">
                    ⚠️ This code expires in 15 minutes. Never share this code with anyone.
                </div>
                
                <p style="font-size: 12px; color: #999; margin-top: 30px;">
                    If you didn't request this, you can safely ignore this email.
                </p>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def coupon_email(username: str, coupon_code: str, discount_value: float, 
                    discount_type: str, expiry_days: int, shop_url: str) -> str:
        expiry_text = f"Expires in {expiry_days} days!" if expiry_days else "Limited time offer!"
        discount_text = f"{discount_value}%" if discount_type == "percentage" else f"${discount_value}"
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                }}
                .coupon-card {{
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    border-radius: 16px;
                    padding: 30px;
                    text-align: center;
                    color: white;
                    margin: 30px 0;
                }}
                .coupon-code {{
                    font-size: 32px;
                    font-weight: bold;
                    letter-spacing: 4px;
                    background: white;
                    color: #667eea;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                    font-family: monospace;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #667eea;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>🎫 You've Got a Coupon!</h2>
                <p>Hello {username},</p>
                
                <div class="coupon-card">
                    <div>Special Offer Just for You!</div>
                    <div class="coupon-code">{coupon_code}</div>
                    <div style="font-size: 24px; margin: 10px 0;">{discount_text} OFF</div>
                    <div>{expiry_text}</div>
                </div>
                
                <center>
                    <a href="{shop_url}" class="button">Shop Now →</a>
                </center>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def low_stock_alert(product_name: str, current_stock: int, sales_today: int, admin_url: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background: white;
                    border-radius: 16px;
                    padding: 40px;
                }}
                .alert-card {{
                    background: #fee2e2;
                    border-left: 4px solid #ef4444;
                    border-radius: 12px;
                    padding: 20px;
                    margin: 20px 0;
                }}
                .stats {{
                    background: #f8f9fa;
                    border-radius: 12px;
                    padding: 15px;
                    margin: 20px 0;
                }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: #ef4444;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>⚠️ Low Stock Alert</h2>
                
                <div class="alert-card">
                    <strong>{product_name}</strong> is running low on stock!
                </div>
                
                <div class="stats">
                    <div>📦 Current Stock: <strong>{current_stock}</strong> units</div>
                    <div>📈 Sold Today: <strong>{sales_today}</strong> units</div>
                    <div>⚠️ Action Needed: Restock immediately</div>
                </div>
                
                <center>
                    <a href="{admin_url}" class="button">Manage Products →</a>
                </center>
            </div>
        </body>
        </html>
        """

# ==================== PYDANTIC SCHEMAS ====================

class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8)
    language: str = settings.DEFAULT_LANGUAGE
    
    @validator('language')
    def validate_language(cls, v):
        if v not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(f'Language must be one of {settings.SUPPORTED_LANGUAGES}')
        return v

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
    coupon_code: Optional[str] = None
    cashapp_tag: Optional[str] = None

class CouponCreate(BaseModel):
    code: str
    discount_type: str
    discount_value: float
    min_purchase: Optional[float] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None
    user_id: Optional[str] = None

class ReviewCreate(BaseModel):
    product_id: int
    rating: int = Field(ge=1, le=5)
    comment: str
    images: Optional[List[str]] = None

class XCoinAdjustment(BaseModel):
    user_id: str
    amount: int
    reason: str

class RefundOrder(BaseModel):
    order_id: int
    reason: str

class NotificationPreferences(BaseModel):
    email_order_updates: bool = True
    email_promotions: bool = False
    email_reviews: bool = True
    discord_dm_notifications: bool = False

class LanguageUpdate(BaseModel):
    language: str

class UpdateCreate(BaseModel):
    title: str
    content: str

class RobuxTierCreate(BaseModel):
    robux_cost: int
    xcoin_amount: int
    game_pass_id: str
    game_pass_url: str
    display_name: str

class RobuxTierUpdate(BaseModel):
    robux_cost: Optional[int] = None
    xcoin_amount: Optional[int] = None
    game_pass_id: Optional[str] = None
    game_pass_url: Optional[str] = None
    display_name: Optional[str] = None
    is_active: Optional[bool] = None

class ExchangeRatesUpdate(BaseModel):
    robux_to_xcoin: int
    xcoin_to_usd: int
    robux_to_usd: int

# ==================== SENDGRID INITIALIZATION ====================

email_service = None

if settings.SENDGRID_API_KEY and settings.SENDGRID_FROM_EMAIL:
    email_service = SendGridEmailService(
        api_key=settings.SENDGRID_API_KEY,
        from_email=settings.SENDGRID_FROM_EMAIL,
        from_name=settings.SENDGRID_FROM_NAME
    )
    logger.info("SendGrid email service initialized")
else:
    logger.warning("SendGrid not configured - email notifications disabled")

# ==================== TRANSLATIONS ====================

TRANSLATIONS = {
    "en": {
        "welcome": "Welcome to XStore!",
        "order_confirmed": "Order #{} confirmed!",
        "affiliate_earnings": "You earned ${} from affiliate commission!",
        "coupon_applied": "Coupon applied! You saved ${}",
        "low_stock": "Product '{}' is running low on stock!",
        "order_pending_robux": "Order #{} is pending Robux verification",
    },
    "es": {
        "welcome": "¡Bienvenido a XStore!",
        "order_confirmed": "¡Pedido #{} confirmado!",
        "affiliate_earnings": "¡Ganaste ${} por comisión de afiliado!",
        "coupon_applied": "¡Cupón aplicado! Ahorraste ${}",
        "low_stock": "¡El producto '{}' se está quedando sin stock!",
        "order_pending_robux": "El pedido #{} está pendiente de verificación de Robux",
    },
}

def translate(key: str, lang: str, **kwargs):
    translations = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    text = translations.get(key, key)
    return text.format(**kwargs)

# ==================== COUPON VALIDATION ====================

async def validate_coupon(code: str, user_id: str, total_usd: float) -> Optional[dict]:
    response = supabase.table("coupons").select("*").eq("code", code.upper()).execute()
    if not response.data:
        return None
    
    coupon = response.data[0]
    
    if coupon.get("expires_at"):
        expires = datetime.fromisoformat(coupon["expires_at"])
        if expires < datetime.utcnow():
            return None
    
    if coupon.get("max_uses"):
        uses = supabase.table("orders").select("id").eq("coupon_code", code).execute()
        if len(uses.data) >= coupon["max_uses"]:
            return None
    
    if coupon.get("user_id") and coupon["user_id"] != user_id:
        return None
    
    if coupon.get("min_purchase") and total_usd < coupon["min_purchase"]:
        return None
    
    if coupon["discount_type"] == "percentage":
        discount = total_usd * (coupon["discount_value"] / 100)
    else:
        discount = coupon["discount_value"]
    
    return {
        "coupon": coupon,
        "discount": min(discount, total_usd)
    }

# ==================== NOTIFICATION SERVICE ====================

async def send_notification(user_id: str, title: str, message: str, notification_type: str = "info", 
                           email_data: Dict[str, Any] = None):
    """Send notification via WebSocket and optionally email"""
    user = supabase.table("users").select("email, username, language, notification_preferences, x_coin_balance").eq("id", user_id).execute()
    if not user.data:
        return
    user_data = user.data[0]
    prefs = user_data.get("notification_preferences", {})
    
    # Send WebSocket notification
    if user_id in websocket_connections:
        for ws in websocket_connections[user_id]:
            try:
                await ws.send_json({
                    "type": notification_type,
                    "title": title,
                    "message": message,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except:
                pass
    
    # Send email if enabled and we have email_data
    if email_service and email_data and prefs.get("email_order_updates", True):
        try:
            email_service.send_email(
                to_email=user_data["email"],
                to_name=user_data["username"],
                subject=email_data.get("subject", title),
                html_content=email_data.get("html_content", message)
            )
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")

# ==================== AFFILIATE FUNCTIONS ====================

def generate_affiliate_code(user_id: str) -> str:
    unique = str(uuid.uuid4())[:8]
    return f"{user_id[:6]}_{unique}".upper()

async def track_affiliate_click(affiliate_code: str, ip: str, user_agent: str):
    response = supabase.table("affiliates").select("*").eq("code", affiliate_code).execute()
    if not response.data:
        return None
    
    affiliate = response.data[0]
    
    supabase.table("affiliate_clicks").insert({
        "affiliate_id": affiliate["id"],
        "ip": ip,
        "user_agent": user_agent,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return affiliate

async def process_affiliate_commission(order_id: int, user_id: str, total_usd: float, affiliate_id: int):
    click_response = supabase.table("affiliate_clicks").select("*").eq("affiliate_id", affiliate_id).order("created_at", desc=True).limit(1).execute()
    if not click_response.data:
        return
    
    latest_click = click_response.data[0]
    click_time = datetime.fromisoformat(latest_click["created_at"])
    
    if (datetime.utcnow() - click_time).days > settings.AFFILIATE_COOKIE_DAYS:
        return
    
    commission = total_usd * (settings.AFFILIATE_COMMISSION_PERCENT / 100)
    
    supabase.table("affiliate_commissions").insert({
        "affiliate_id": affiliate_id,
        "order_id": order_id,
        "amount_usd": commission,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    affiliate_user = supabase.table("affiliates").select("user_id").eq("id", affiliate_id).execute()
    if affiliate_user.data:
        affiliate_data = supabase.table("affiliates").select("*").eq("user_id", affiliate_user.data[0]["user_id"]).execute()
        referral_link = f"{settings.FRONTEND_URL}/?ref={affiliate_data.data[0]['code']}" if affiliate_data.data else ""
        
        await send_notification(
            affiliate_user.data[0]["user_id"], 
            "Affiliate Commission", 
            translate("affiliate_earnings", "en", amount=commission),
            "earnings",
            {
                "subject": f"You Earned ${commission:.2f} from XStore!",
                "html_content": EmailTemplates.affiliate_commission(
                    username=affiliate_user.data[0]["user_id"],
                    commission_amount=commission,
                    referral_link=referral_link,
                    dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
                )
            }
        )

# ==================== REVIEW SYSTEM ====================

async def update_product_rating(product_id: int):
    reviews = supabase.table("reviews").select("rating").eq("product_id", product_id).execute()
    if not reviews.data:
        return
    
    avg_rating = sum(r["rating"] for r in reviews.data) / len(reviews.data)
    
    supabase.table("products").update({
        "average_rating": round(avg_rating, 2),
        "review_count": len(reviews.data)
    }).eq("id", product_id).execute()

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

# ==================== FASTAPI APP ====================

app = FastAPI(title="XStore API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== HEALTH & ROOT ====================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "email_service": "configured" if email_service else "disabled"
    }

@app.get("/")
async def root():
    return {
        "message": "XStore API",
        "version": "2.0.0",
        "features": [
            "Discord OAuth",
            "Affiliate Program",
            "Discount Coupons",
            "Product Reviews",
            "Wishlist",
            "WebSocket Notifications",
            "Multi-language",
            "PayPal",
            "CashApp",
            "Robux Payments",
            "SendGrid Email"
        ]
    }

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
        "options": {"data": {"username": user_data.username, "language": user_data.language}}
    })
    
    is_owner = user_data.email == settings.ADMIN_EMAIL
    
    supabase.table("users").insert({
        "id": auth_response.user.id,
        "email": user_data.email,
        "username": user_data.username,
        "language": user_data.language,
        "x_coin_balance": settings.WELCOME_BONUS_XCOIN,
        "is_owner": is_owner,
        "is_banned": False,
        "notification_preferences": {
            "email_order_updates": True,
            "email_promotions": False,
            "email_reviews": True,
            "discord_dm_notifications": False
        },
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("affiliates").insert({
        "user_id": auth_response.user.id,
        "code": generate_affiliate_code(auth_response.user.id),
        "commission_rate": settings.AFFILIATE_COMMISSION_PERCENT,
        "total_earnings": 0,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("logs").insert({
        "user_id": auth_response.user.id,
        "action": "user_register",
        "details": f"New user registered: {user_data.username}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    # Send welcome email
    if email_service:
        try:
            email_service.send_email(
                to_email=user_data.email,
                to_name=user_data.username,
                subject="🎉 Welcome to XStore!",
                html_content=EmailTemplates.welcome_email(
                    username=user_data.username,
                    xcoin_bonus=settings.WELCOME_BONUS_XCOIN,
                    dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
                )
            )
            logger.info(f"Welcome email sent to {user_data.email}")
        except Exception as e:
            logger.error(f"Failed to send welcome email: {e}")
    
    access_token = create_access_token({"sub": auth_response.user.id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": auth_response.user.id,
            "email": user_data.email,
            "username": user_data.username,
            "language": user_data.language,
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
        
        supabase.table("logs").insert({
            "user_id": auth_response.user.id,
            "action": "user_login",
            "details": "User logged in",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "username": user["username"],
                "language": user.get("language", settings.DEFAULT_LANGUAGE),
                "x_coin_balance": user["x_coin_balance"],
                "is_owner": user["is_owner"],
                "roblox_id": user.get("roblox_id"),
                "roblox_username": user.get("roblox_username")
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
        "language": current_user.get("language", settings.DEFAULT_LANGUAGE),
        "x_coin_balance": current_user["x_coin_balance"],
        "is_owner": current_user["is_owner"],
        "roblox_id": current_user.get("roblox_id"),
        "roblox_username": current_user.get("roblox_username"),
        "notification_preferences": current_user.get("notification_preferences", {}),
        "created_at": current_user.get("created_at")
    }

@app.post("/api/auth/link-roblox")
async def link_roblox(data: LinkRoblox, current_user = Depends(require_user)):
    supabase.table("users").update({
        "roblox_id": data.roblox_id,
        "roblox_username": data.roblox_username
    }).eq("id", current_user["id"]).execute()
    
    supabase.table("logs").insert({
        "user_id": current_user["id"],
        "action": "link_roblox",
        "details": f"Linked Roblox: {data.roblox_username}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": "Roblox account linked"}

@app.put("/api/auth/language")
async def update_language(data: LanguageUpdate, current_user = Depends(require_user)):
    if data.language not in settings.SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Language must be one of {settings.SUPPORTED_LANGUAGES}")
    
    supabase.table("users").update({"language": data.language}).eq("id", current_user["id"]).execute()
    
    return {"message": "Language updated", "language": data.language}

@app.post("/api/auth/forgot-password")
async def forgot_password(email: str):
    user = supabase.table("users").select("id, username").eq("email", email).execute()
    if not user.data:
        return {"message": "If that email exists, we've sent a reset code"}
    
    reset_code = ''.join(random.choices(string.digits, k=6))
    
    supabase.table("password_resets").insert({
        "user_id": user.data[0]["id"],
        "code": reset_code,
        "expires_at": datetime.utcnow() + timedelta(minutes=15),
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    if email_service:
        reset_url = f"{settings.FRONTEND_URL}/reset-password?code={reset_code}&email={email}"
        
        email_service.send_email(
            to_email=email,
            to_name=user.data[0]["username"],
            subject="🔐 Password Reset - XStore",
            html_content=EmailTemplates.password_reset(
                username=user.data[0]["username"],
                reset_code=reset_code,
                reset_url=reset_url
            )
        )
    
    return {"message": "If that email exists, we've sent a reset code"}

# ==================== DISCORD OAUTH ====================

@app.get("/api/auth/discord")
async def discord_login():
    auth_url = f"https://discord.com/api/oauth2/authorize?client_id={settings.DISCORD_CLIENT_ID}&redirect_uri={settings.DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20email"
    return {"auth_url": auth_url}

@app.get("/api/auth/discord/callback")
async def discord_callback(code: str):
    if not code:
        raise HTTPException(400, "No code provided")
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.DISCORD_REDIRECT_URI
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if token_response.status_code != 200:
            raise HTTPException(400, "Failed to get Discord token")
        
        token_data = token_response.json()
        
        user_response = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
        
        if user_response.status_code != 200:
            raise HTTPException(400, "Failed to get Discord user")
        
        discord_user = user_response.json()
    
    existing = supabase.table("users").select("*").eq("discord_id", discord_user["id"]).execute()
    
    if existing.data:
        user = existing.data[0]
        access_token = create_access_token({"sub": user["id"]})
        return {"access_token": access_token, "token_type": "bearer", "user": user}
    
    username = discord_user.get("global_name") or discord_user["username"]
    email = discord_user.get("email", f"{discord_user['id']}@discord.user")
    
    auth_response = supabase.auth.sign_up({
        "email": email,
        "password": f"discord_{discord_user['id']}_{secrets.token_urlsafe(16)}",
        "options": {"data": {"username": username, "discord_id": discord_user["id"]}}
    })
    
    supabase.table("users").insert({
        "id": auth_response.user.id,
        "email": email,
        "username": username,
        "discord_id": discord_user["id"],
        "discord_avatar": discord_user.get("avatar"),
        "language": settings.DEFAULT_LANGUAGE,
        "x_coin_balance": settings.WELCOME_BONUS_XCOIN,
        "is_owner": False,
        "is_banned": False,
        "notification_preferences": {
            "email_order_updates": True,
            "email_promotions": False,
            "email_reviews": True,
            "discord_dm_notifications": True
        },
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("affiliates").insert({
        "user_id": auth_response.user.id,
        "code": generate_affiliate_code(auth_response.user.id),
        "commission_rate": settings.AFFILIATE_COMMISSION_PERCENT,
        "total_earnings": 0,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    if email_service:
        email_service.send_email(
            to_email=email,
            to_name=username,
            subject="🎉 Welcome to XStore!",
            html_content=EmailTemplates.welcome_email(
                username=username,
                xcoin_bonus=settings.WELCOME_BONUS_XCOIN,
                dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
            )
        )
    
    access_token = create_access_token({"sub": auth_response.user.id})
    
    return {"access_token": access_token, "token_type": "bearer", "user": {
        "id": auth_response.user.id,
        "email": email,
        "username": username,
        "language": settings.DEFAULT_LANGUAGE,
        "x_coin_balance": settings.WELCOME_BONUS_XCOIN,
        "is_owner": False
    }}

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
    
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    products = query.execute().data
    
    return products

@app.get("/api/products/{product_id}")
async def get_product(product_id: int):
    response = supabase.table("products").select("*").eq("id", product_id).execute()
    if not response.data:
        raise HTTPException(404, "Product not found")
    
    product = response.data[0]
    
    reviews = supabase.table("reviews").select("*, user:users(username)").eq("product_id", product_id).order("created_at", desc=True).execute()
    product["reviews"] = reviews.data
    
    return product

@app.post("/api/products", dependencies=[Depends(require_owner)])
async def create_product(product: ProductCreate):
    response = supabase.table("products").insert({
        "title": product.title,
        "description": product.description,
        "category": product.category,
        "price_usd": product.price_usd,
        "stock": product.stock,
        "image_url": product.image_url,
        "average_rating": 0,
        "review_count": 0,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("logs").insert({
        "action": "product_create",
        "details": f"Created product: {product.title}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.put("/api/products/{product_id}", dependencies=[Depends(require_owner)])
async def update_product(product_id: int, product: ProductUpdate):
    update_data = {k: v for k, v in product.dict().items() if v is not None}
    response = supabase.table("products").update(update_data).eq("id", product_id).execute()
    if not response.data:
        raise HTTPException(404, "Product not found")
    
    supabase.table("logs").insert({
        "action": "product_update",
        "details": f"Updated product #{product_id}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.delete("/api/products/{product_id}", dependencies=[Depends(require_owner)])
async def delete_product(product_id: int):
    supabase.table("products").update({"is_active": False}).eq("id", product_id).execute()
    
    supabase.table("logs").insert({
        "action": "product_delete",
        "details": f"Deleted product #{product_id}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": "Product deleted"}

# ==================== REVIEW ROUTES ====================

@app.post("/api/reviews")
async def create_review(review: ReviewCreate, current_user = Depends(require_user)):
    orders = supabase.table("orders").select("id").eq("user_id", current_user["id"]).execute()
    if not orders.data:
        raise HTTPException(400, "You must purchase a product before reviewing")
    
    order_items = supabase.table("order_items").select("order_id").eq("product_id", review.product_id).execute()
    if not order_items.data:
        raise HTTPException(400, "You haven't purchased this product")
    
    existing = supabase.table("reviews").select("id").eq("user_id", current_user["id"]).eq("product_id", review.product_id).execute()
    if existing.data:
        raise HTTPException(400, "You have already reviewed this product")
    
    response = supabase.table("reviews").insert({
        "user_id": current_user["id"],
        "product_id": review.product_id,
        "rating": review.rating,
        "comment": review.comment,
        "images": review.images,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    await update_product_rating(review.product_id)
    
    supabase.table("logs").insert({
        "user_id": current_user["id"],
        "action": "review_create",
        "details": f"Reviewed product #{review.product_id} with {review.rating} stars",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.get("/api/reviews/product/{product_id}")
async def get_product_reviews(product_id: int, limit: int = 20, offset: int = 0):
    reviews = supabase.table("reviews").select("*, user:users(username)").eq("product_id", product_id).order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return reviews.data

@app.post("/api/reviews/{review_id}/reply", dependencies=[Depends(require_owner)])
async def reply_to_review(review_id: int, reply: str):
    supabase.table("reviews").update({"reply": reply, "replied_at": datetime.utcnow().isoformat()}).eq("id", review_id).execute()
    
    review = supabase.table("reviews").select("user_id, product:products(title)").eq("id", review_id).execute()
    if review.data:
        await send_notification(
            review.data[0]["user_id"], 
            "Review Reply", 
            f"A merchant replied to your review on {review.data[0]['product']['title']}",
            "review"
        )
    
    return {"message": "Reply added"}

# ==================== WISHLIST ROUTES ====================

@app.post("/api/wishlist/{product_id}")
async def add_to_wishlist(product_id: int, current_user = Depends(require_user)):
    existing = supabase.table("wishlist").select("id").eq("user_id", current_user["id"]).eq("product_id", product_id).execute()
    if existing.data:
        return {"message": "Already in wishlist"}
    
    supabase.table("wishlist").insert({
        "user_id": current_user["id"],
        "product_id": product_id,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": "Added to wishlist"}

@app.delete("/api/wishlist/{product_id}")
async def remove_from_wishlist(product_id: int, current_user = Depends(require_user)):
    supabase.table("wishlist").delete().eq("user_id", current_user["id"]).eq("product_id", product_id).execute()
    return {"message": "Removed from wishlist"}

@app.get("/api/wishlist")
async def get_wishlist(current_user = Depends(require_user)):
    items = supabase.table("wishlist").select("*, product:products(*)").eq("user_id", current_user["id"]).execute()
    return items.data

# ==================== COUPON ROUTES ====================

@app.get("/api/coupons/validate")
async def validate_coupon_route(code: str, total_usd: float, current_user = Depends(require_user)):
    result = await validate_coupon(code, current_user["id"], total_usd)
    if not result:
        raise HTTPException(404, "Invalid or expired coupon")
    
    return {
        "valid": True,
        "discount": round(result["discount"], 2),
        "new_total": round(total_usd - result["discount"], 2),
        "coupon": result["coupon"]
    }

@app.post("/api/coupons", dependencies=[Depends(require_owner)])
async def create_coupon(coupon: CouponCreate):
    response = supabase.table("coupons").insert({
        "code": coupon.code.upper(),
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "min_purchase": coupon.min_purchase,
        "max_uses": coupon.max_uses,
        "expires_at": coupon.expires_at.isoformat() if coupon.expires_at else None,
        "user_id": coupon.user_id,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("logs").insert({
        "action": "coupon_create",
        "details": f"Created coupon: {coupon.code}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    if coupon.user_id and email_service:
        user = supabase.table("users").select("email, username").eq("id", coupon.user_id).execute()
        if user.data:
            expiry_days = 7
            if coupon.expires_at:
                expiry_days = (coupon.expires_at - datetime.utcnow()).days
            
            email_service.send_email(
                to_email=user.data[0]["email"],
                to_name=user.data[0]["username"],
                subject=f"🎫 Your XStore Coupon: {coupon.code}",
                html_content=EmailTemplates.coupon_email(
                    username=user.data[0]["username"],
                    coupon_code=coupon.code,
                    discount_value=coupon.discount_value,
                    discount_type=coupon.discount_type,
                    expiry_days=expiry_days,
                    shop_url=f"{settings.FRONTEND_URL}/shop"
                )
            )
    
    return response.data[0]

@app.get("/api/coupons", dependencies=[Depends(require_owner)])
async def get_coupons():
    return supabase.table("coupons").select("*").order("created_at", desc=True).execute().data

@app.delete("/api/coupons/{coupon_id}", dependencies=[Depends(require_owner)])
async def delete_coupon(coupon_id: int):
    supabase.table("coupons").delete().eq("id", coupon_id).execute()
    return {"message": "Coupon deleted"}

# ==================== AFFILIATE ROUTES ====================

@app.get("/api/affiliate/info")
async def get_affiliate_info(current_user = Depends(require_user)):
    affiliate = supabase.table("affiliates").select("*").eq("user_id", current_user["id"]).execute()
    if not affiliate.data:
        raise HTTPException(404, "Affiliate not found")
    
    commissions = supabase.table("affiliate_commissions").select("*").eq("affiliate_id", affiliate.data[0]["id"]).execute()
    clicks = supabase.table("affiliate_clicks").select("*").eq("affiliate_id", affiliate.data[0]["id"]).execute()
    
    return {
        "affiliate": affiliate.data[0],
        "total_commissions": sum(c["amount_usd"] for c in commissions.data),
        "pending_commissions": sum(c["amount_usd"] for c in commissions.data if c["status"] == "pending"),
        "paid_commissions": sum(c["amount_usd"] for c in commissions.data if c["status"] == "paid"),
        "total_clicks": len(clicks.data),
        "referral_link": f"{settings.FRONTEND_URL}/?ref={affiliate.data[0]['code']}"
    }

@app.get("/api/affiliate/track/{code}")
async def track_affiliate_click_route(code: str, request: Request):
    affiliate = await track_affiliate_click(code, request.client.host, request.headers.get("user-agent", ""))
    
    response = JSONResponse({"message": "Affiliate tracked"})
    response.set_cookie(
        key="affiliate_code",
        value=code,
        max_age=settings.AFFILIATE_COOKIE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=True
    )
    
    return response

# ==================== ORDER ROUTES ====================

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, request: Request, current_user = Depends(require_user)):
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
    
    coupon_discount = 0
    if order_data.coupon_code:
        coupon_result = await validate_coupon(order_data.coupon_code, current_user["id"], total_usd)
        if coupon_result:
            coupon_discount = coupon_result["discount"]
            total_usd -= coupon_discount
    
    x_coin_used = 0
    remaining_usd = total_usd
    
    if order_data.payment_method in ["x_coin", "split"] and order_data.x_coin_amount > 0:
        if order_data.x_coin_amount > current_user["x_coin_balance"]:
            raise HTTPException(400, "Insufficient X Coin balance")
        x_coin_used = order_data.x_coin_amount
        remaining_usd = total_usd - (x_coin_used / settings.XCOIN_TO_USD_RATE)
        if remaining_usd < 0:
            remaining_usd = 0
    
    order = {
        "user_id": current_user["id"],
        "total_usd": round(total_usd, 2),
        "original_total_usd": round(total_usd + coupon_discount, 2),
        "total_xcoin": int(total_usd * settings.XCOIN_TO_USD_RATE),
        "x_coin_used": x_coin_used,
        "remaining_usd": round(remaining_usd, 2),
        "payment_method": order_data.payment_method,
        "coupon_code": order_data.coupon_code,
        "discount_amount": coupon_discount,
        "status": "pending",
        "cashapp_tag": order_data.cashapp_tag,
        "created_at": datetime.utcnow().isoformat()
    }
    
    if remaining_usd == 0:
        order["status"] = "completed"
    elif order_data.payment_method == "paypal":
        order["status"] = "awaiting_payment"
    elif order_data.payment_method == "cashapp":
        order["status"] = "awaiting_verification"
    elif order_data.payment_method == "robux":
        order["status"] = "awaiting_robux"
    
    order_response = supabase.table("orders").insert(order).execute()
    order_id = order_response.data[0]["id"]
    
    for product in products:
        supabase.table("order_items").insert({
            "order_id": order_id,
            "product_id": product["id"],
            "quantity": product["quantity"],
            "price_usd_at_time": product["price_usd"],
            "price_xcoin_at_time": int(product["price_usd"] * settings.XCOIN_TO_USD_RATE)
        }).execute()
    
    if x_coin_used > 0:
        new_balance = current_user["x_coin_balance"] - x_coin_used
        supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", current_user["id"]).execute()
        supabase.table("xcoin_transactions").insert({
            "user_id": current_user["id"],
            "order_id": order_id,
            "amount": -x_coin_used,
            "reason": f"Used for order #{order_id}",
            "created_at": datetime.utcnow().isoformat()
        }).execute()
    
    for product in products:
        new_stock = product["stock"] - product["quantity"]
        supabase.table("products").update({"stock": new_stock}).eq("id", product["id"]).execute()
        
        if new_stock <= 5:
            await send_notification(
                settings.ADMIN_EMAIL, 
                "Low Stock Alert", 
                translate("low_stock", "en", product=product["title"]),
                "alert",
                {
                    "subject": f"⚠️ Low Stock: {product['title']}",
                    "html_content": EmailTemplates.low_stock_alert(
                        product_name=product["title"],
                        current_stock=new_stock,
                        sales_today=1,
                        admin_url=f"{settings.FRONTEND_URL}/admin"
                    )
                }
            )
    
    affiliate_cookie = request.cookies.get("affiliate_code")
    if affiliate_cookie:
        affiliate = supabase.table("affiliates").select("*").eq("code", affiliate_cookie).execute()
        if affiliate.data and affiliate.data[0]["user_id"] != current_user["id"]:
            await process_affiliate_commission(order_id, current_user["id"], total_usd, affiliate.data[0]["id"])
    
    supabase.table("logs").insert({
        "user_id": current_user["id"],
        "action": "order_create",
        "details": f"Created order #{order_id} for ${total_usd}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    if order["status"] == "completed" and email_service:
        items_html = ""
        for product in products:
            items_html += f"""
            <div class="item">
                <strong>{product['title']}</strong> x {product['quantity']}<br>
                ${product['price_usd']:.2f} each
            </div>
            """
        
        email_service.send_email(
            to_email=current_user["email"],
            to_name=current_user["username"],
            subject=f"✅ Order Confirmed #{order_id} - XStore",
            html_content=EmailTemplates.order_confirmation(
                username=current_user["username"],
                order_id=order_id,
                items_html=items_html,
                total_usd=total_usd,
                payment_method=order_data.payment_method,
                status="completed",
                dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
            )
        )
    
    return {
        "order_id": order_id,
        "status": order["status"],
        "total_usd": total_usd,
        "original_total": order["original_total_usd"],
        "discount": coupon_discount,
        "x_coin_used": x_coin_used,
        "remaining_usd": remaining_usd
    }

@app.post("/api/robux/verify/{order_id}")
async def verify_robux_order(order_id: int, current_user = Depends(require_user)):
    session = verification_sessions.get(str(order_id))
    if not session:
        raise HTTPException(404, "Verification session not found")
    if session["user_id"] != current_user["id"]:
        raise HTTPException(403, "Not your order")
    if not current_user.get("roblox_id"):
        raise HTTPException(400, "Please link your Roblox account first")
    
    required_passes = session["required_passes"]
    verification_results = await verify_multiple_passes(current_user["roblox_id"], [p["game_pass_id"] for p in required_passes])
    
    missing_passes = []
    for pass_info in required_passes:
        if not verification_results.get(pass_info["game_pass_id"]):
            missing_passes.append(pass_info)
    
    if missing_passes:
        return {
            "success": False,
            "missing_passes": missing_passes
        }
    
    supabase.table("orders").update({"status": "completed"}).eq("id", order_id).execute()
    
    session["status"] = "completed"
    del verification_sessions[str(order_id)]
    
    await send_notification(
        current_user["id"], 
        "Order Completed", 
        f"Your Robux verification for order #{order_id} was successful!",
        "order"
    )
    
    return {
        "success": True,
        "message": "All game passes verified! Order completed."
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
    
    order = order.data[0]
    if order["user_id"] != current_user["id"] and not current_user.get("is_owner"):
        raise HTTPException(403, "Access denied")
    
    items = supabase.table("order_items").select("*, product:products(*)").eq("order_id", order_id).execute()
    order["items"] = items.data
    
    return order

# ==================== NOTIFICATION ROUTES ====================

@app.put("/api/notifications/preferences")
async def update_notification_preferences(prefs: NotificationPreferences, current_user = Depends(require_user)):
    supabase.table("users").update({
        "notification_preferences": prefs.dict()
    }).eq("id", current_user["id"]).execute()
    
    return {"message": "Preferences updated"}

# ==================== X COIN ROUTES ====================

@app.get("/api/xcoin/balance")
async def get_xcoin_balance(current_user = Depends(require_user)):
    return {
        "balance": current_user["x_coin_balance"],
        "robux_to_xcoin_rate": settings.ROBUX_TO_XCOIN_RATE,
        "xcoin_to_usd_rate": settings.XCOIN_TO_USD_RATE
    }

@app.get("/api/xcoin/tiers")
async def get_xcoin_tiers():
    tiers = supabase.table("robux_tiers").select("*").eq("is_active", True).order("robux_cost").execute()
    
    result = []
    for tier in tiers.data:
        expected_xcoin = tier["robux_cost"] * settings.ROBUX_TO_XCOIN_RATE
        bonus_percentage = round((tier["xcoin_amount"] / expected_xcoin - 1) * 100, 1) if expected_xcoin > 0 else 0
        
        result.append({
            "id": tier["id"],
            "robux_cost": tier["robux_cost"],
            "usd_value": round(tier["robux_cost"] / settings.ROBUX_TO_USD_RATE, 2),
            "xcoin_amount": tier["xcoin_amount"],
            "game_pass_id": tier["game_pass_id"],
            "game_pass_url": tier["game_pass_url"],
            "display_name": tier.get("display_name", f"{tier['robux_cost']} Robux Pack"),
            "bonus_percentage": bonus_percentage
        })
    
    return result

@app.post("/api/xcoin/buy/tier")
async def buy_xcoin_with_tier(request: Request, current_user = Depends(require_user)):
    data = await request.json()
    tier_id = data.get("tier_id")
    
    if not current_user.get("roblox_id"):
        raise HTTPException(400, "Please link your Roblox account first")
    
    tier_response = supabase.table("robux_tiers").select("*").eq("id", tier_id).execute()
    if not tier_response.data:
        raise HTTPException(404, "Tier not found")
    
    tier = tier_response.data[0]
    
    session_id = f"{current_user['id']}_{datetime.utcnow().timestamp()}"
    verification_sessions[session_id] = {
        "type": "xcoin_purchase",
        "status": "pending",
        "user_id": current_user["id"],
        "roblox_id": current_user["roblox_id"],
        "game_pass_id": tier["game_pass_id"],
        "robux_cost": tier["robux_cost"],
        "xcoin_amount": tier["xcoin_amount"],
        "tier_name": tier.get("display_name", f"{tier['robux_cost']} Robux"),
        "created_at": datetime.utcnow().isoformat()
    }
    
    return {
        "session_id": session_id,
        "status": "pending",
        "tier": {
            "display_name": tier.get("display_name"),
            "robux_cost": tier["robux_cost"],
            "usd_value": round(tier["robux_cost"] / settings.ROBUX_TO_USD_RATE, 2),
            "xcoin_amount": tier["xcoin_amount"],
            "game_pass_url": tier["game_pass_url"]
        },
        "expires_in": 120
    }

@app.post("/api/xcoin/verify/purchase")
async def verify_xcoin_purchase(request: Request, current_user = Depends(require_user)):
    data = await request.json()
    session_id = data.get("session_id")
    
    session = verification_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Verification session not found")
    
    if session["user_id"] != current_user["id"]:
        raise HTTPException(403, "Not your purchase")
    
    if not current_user.get("roblox_id"):
        raise HTTPException(400, "Roblox account not linked")
    
    has_pass = await verify_roblox_game_pass(current_user["roblox_id"], session["game_pass_id"])
    
    if not has_pass:
        return {
            "success": False,
            "message": "You haven't purchased this game pass yet. Buy it on Roblox first!"
        }
    
    existing = supabase.table("xcoin_transactions").select("id").eq("user_id", current_user["id"]).eq("reason", f"Robux purchase: {session['game_pass_id']}").execute()
    if existing.data:
        return {
            "success": False,
            "message": "You've already claimed X Coin for this game pass!"
        }
    
    new_balance = current_user["x_coin_balance"] + session["xcoin_amount"]
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", current_user["id"]).execute()
    
    supabase.table("xcoin_transactions").insert({
        "user_id": current_user["id"],
        "amount": session["xcoin_amount"],
        "reason": f"Robux purchase: {session['tier_name']} ({session['robux_cost']} Robux)",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    del verification_sessions[session_id]
    
    await send_notification(
        current_user["id"], 
        "X Coin Purchased! 🎉", 
        f"You received {session['xcoin_amount']:,} X Coin! New balance: {new_balance:,}",
        "xcoin",
        {
            "subject": f"⚡ You Received {session['xcoin_amount']:,} X Coin!",
            "html_content": EmailTemplates.xcoin_purchase(
                username=current_user["username"],
                xcoin_amount=session["xcoin_amount"],
                new_balance=new_balance,
                purchase_method=session['tier_name'],
                dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
            )
        }
    )
    
    return {
        "success": True,
        "xcoin_amount": session["xcoin_amount"],
        "new_balance": new_balance,
        "message": f"Successfully added {session['xcoin_amount']:,} X Coin to your account!"
    }

@app.get("/api/xcoin/transactions")
async def get_xcoin_transactions(current_user = Depends(require_user)):
    transactions = supabase.table("xcoin_transactions").select("*").eq("user_id", current_user["id"]).order("created_at", desc=True).limit(50).execute()
    return transactions.data

# ==================== EXCHANGE RATES ====================

@app.get("/api/rates")
async def get_rates():
    return {
        "robux_to_xcoin": settings.ROBUX_TO_XCOIN_RATE,
        "xcoin_to_usd": settings.XCOIN_TO_USD_RATE,
        "robux_to_usd": settings.ROBUX_TO_USD_RATE
    }

# ==================== UPDATES ROUTES ====================

@app.get("/api/updates")
async def get_updates(limit: int = 10):
    updates = supabase.table("updates").select("*").order("created_at", desc=True).limit(limit).execute()
    return updates.data

@app.post("/api/admin/updates", dependencies=[Depends(require_owner)])
async def create_update(update: UpdateCreate):
    response = supabase.table("updates").insert({
        "title": update.title,
        "content": update.content,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("logs").insert({
        "action": "update_create",
        "details": f"Created update: {update.title}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.delete("/api/admin/updates/{update_id}", dependencies=[Depends(require_owner)])
async def delete_update(update_id: int):
    supabase.table("updates").delete().eq("id", update_id).execute()
    return {"message": "Update deleted"}

# ==================== ADMIN ROUTES ====================

@app.get("/api/admin/products", dependencies=[Depends(require_owner)])
async def admin_get_products():
    return supabase.table("products").select("*").order("created_at", desc=True).execute().data

@app.get("/api/admin/analytics", dependencies=[Depends(require_owner)])
async def admin_get_analytics():
    sales = supabase.table("orders").select("total_usd, status, created_at").execute()
    completed_orders = [o for o in sales.data if o["status"] == "completed"]
    total_sales = sum(o["total_usd"] for o in completed_orders)
    
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    recent_sales = [o for o in completed_orders if o["created_at"] > thirty_days_ago]
    recent_sales_total = sum(o["total_usd"] for o in recent_sales)
    
    items = supabase.table("order_items").select("product_id, quantity").execute()
    product_sales = {}
    for item in items.data:
        product_sales[item["product_id"]] = product_sales.get(item["product_id"], 0) + item["quantity"]
    
    top_products = []
    for pid, qty in sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]:
        prod = supabase.table("products").select("title").eq("id", pid).execute()
        if prod.data:
            top_products.append({
                "title": prod.data[0]["title"],
                "quantity_sold": qty
            })
    
    users = supabase.table("users").select("x_coin_balance").execute()
    total_xcoin = sum(u["x_coin_balance"] for u in users.data)
    avg_xcoin = total_xcoin / len(users.data) if users.data else 0
    
    new_users_30d = supabase.table("users").select("id").gte("created_at", thirty_days_ago).execute()
    
    return {
        "sales": {
            "total": round(total_sales, 2),
            "last_30_days": round(recent_sales_total, 2),
            "order_count": len(completed_orders)
        },
        "top_products": top_products,
        "xcoin": {
            "total_in_circulation": total_xcoin,
            "average_balance": round(avg_xcoin, 2)
        },
        "users": {
            "total": len(users.data),
            "new_last_30_days": len(new_users_30d.data)
        },
        "orders": {
            "total": len(completed_orders)
        }
    }

@app.get("/api/admin/orders", dependencies=[Depends(require_owner)])
async def admin_get_orders(status: Optional[str] = None):
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
    
    await send_notification(
        order.data[0]["user_id"], 
        "Order Completed", 
        f"Order #{order_id} has been completed!",
        "order"
    )
    
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
        "reason": f"Refund for order #{order['id']}: {refund_data.reason}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("orders").update({"status": "refunded"}).eq("id", refund_data.order_id).execute()
    
    await send_notification(
        order["user_id"], 
        "Order Refunded", 
        f"Order #{order['id']} has been refunded. You received {refund_x_coin} X Coin.",
        "refund",
        {
            "subject": f"🔄 Order #{order['id']} Refunded",
            "html_content": f"<h2>Order Refunded</h2><p>You received {refund_x_coin} X Coin.</p>"
        }
    )
    
    supabase.table("logs").insert({
        "action": "order_refund",
        "details": f"Refunded order #{refund_data.order_id}: {refund_data.reason}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": f"Refunded {refund_x_coin} X Coin"}

@app.get("/api/admin/users", dependencies=[Depends(require_owner)])
async def admin_get_users():
    return supabase.table("users").select("*").order("created_at", desc=True).execute().data

@app.post("/api/admin/users/xcoin", dependencies=[Depends(require_owner)])
async def admin_adjust_xcoin(adjustment: XCoinAdjustment):
    user = supabase.table("users").select("x_coin_balance, email, username, language").eq("id", adjustment.user_id).execute()
    if not user.data:
        raise HTTPException(404, "User not found")
    
    new_balance = user.data[0]["x_coin_balance"] + adjustment.amount
    if new_balance < 0:
        raise HTTPException(400, "Balance cannot be negative")
    
    supabase.table("users").update({"x_coin_balance": new_balance}).eq("id", adjustment.user_id).execute()
    supabase.table("xcoin_transactions").insert({
        "user_id": adjustment.user_id,
        "amount": adjustment.amount,
        "reason": f"Admin adjustment: {adjustment.reason}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    await send_notification(
        adjustment.user_id, 
        "X Coin Adjustment", 
        f"Your X Coin balance has been adjusted by {adjustment.amount}. New balance: {new_balance}",
        "xcoin",
        {
            "subject": "⚡ X Coin Balance Updated",
            "html_content": EmailTemplates.xcoin_purchase(
                username=user.data[0]["username"],
                xcoin_amount=adjustment.amount,
                new_balance=new_balance,
                purchase_method="Admin Adjustment",
                dashboard_url=f"{settings.FRONTEND_URL}/dashboard"
            )
        }
    )
    
    return {"message": f"Balance updated to {new_balance}"}

@app.post("/api/admin/users/{user_id}/ban", dependencies=[Depends(require_owner)])
async def admin_ban_user(user_id: str):
    user = supabase.table("users").select("is_banned").eq("id", user_id).execute()
    if not user.data:
        raise HTTPException(404, "User not found")
    
    new_status = not user.data[0]["is_banned"]
    supabase.table("users").update({"is_banned": new_status}).eq("id", user_id).execute()
    
    return {"message": f"User ban status set to {new_status}"}

@app.get("/api/admin/robux-tiers", dependencies=[Depends(require_owner)])
async def admin_get_robux_tiers():
    tiers = supabase.table("robux_tiers").select("*").order("robux_cost").execute()
    
    for tier in tiers.data:
        tier["usd_value"] = round(tier["robux_cost"] / settings.ROBUX_TO_USD_RATE, 2)
        expected_xcoin = tier["robux_cost"] * settings.ROBUX_TO_XCOIN_RATE
        tier["bonus_percentage"] = round((tier["xcoin_amount"] / expected_xcoin - 1) * 100, 1) if expected_xcoin > 0 else 0
    
    return tiers.data

@app.post("/api/admin/robux-tiers", dependencies=[Depends(require_owner)])
async def admin_create_robux_tier(tier: RobuxTierCreate):
    if tier.robux_cost <= 0:
        raise HTTPException(400, "Robux cost must be positive")
    
    if tier.xcoin_amount <= 0:
        raise HTTPException(400, "X Coin amount must be positive")
    
    existing = supabase.table("robux_tiers").select("*").eq("robux_cost", tier.robux_cost).execute()
    if existing.data:
        raise HTTPException(400, f"Tier with {tier.robux_cost} Robux already exists")
    
    response = supabase.table("robux_tiers").insert({
        "robux_cost": tier.robux_cost,
        "xcoin_amount": tier.xcoin_amount,
        "game_pass_id": tier.game_pass_id,
        "game_pass_url": tier.game_pass_url,
        "display_name": tier.display_name,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    supabase.table("logs").insert({
        "action": "robux_tier_create",
        "details": f"Created Robux tier: {tier.robux_cost} Robux -> {tier.xcoin_amount} X Coin - {tier.display_name}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.put("/api/admin/robux-tiers/{tier_id}", dependencies=[Depends(require_owner)])
async def admin_update_robux_tier(tier_id: int, tier: RobuxTierUpdate):
    existing = supabase.table("robux_tiers").select("*").eq("id", tier_id).execute()
    if not existing.data:
        raise HTTPException(404, "Tier not found")
    
    update_data = {}
    if tier.robux_cost is not None:
        if tier.robux_cost <= 0:
            raise HTTPException(400, "Robux cost must be positive")
        update_data["robux_cost"] = tier.robux_cost
        
        duplicate = supabase.table("robux_tiers").select("*").eq("robux_cost", tier.robux_cost).neq("id", tier_id).execute()
        if duplicate.data:
            raise HTTPException(400, f"Another tier with {tier.robux_cost} Robux already exists")
    
    if tier.xcoin_amount is not None:
        if tier.xcoin_amount <= 0:
            raise HTTPException(400, "X Coin amount must be positive")
        update_data["xcoin_amount"] = tier.xcoin_amount
    
    if tier.game_pass_id is not None:
        update_data["game_pass_id"] = tier.game_pass_id
    
    if tier.game_pass_url is not None:
        update_data["game_pass_url"] = tier.game_pass_url
    
    if tier.display_name is not None:
        update_data["display_name"] = tier.display_name
    
    if tier.is_active is not None:
        update_data["is_active"] = tier.is_active
    
    if not update_data:
        raise HTTPException(400, "No fields to update")
    
    response = supabase.table("robux_tiers").update(update_data).eq("id", tier_id).execute()
    
    supabase.table("logs").insert({
        "action": "robux_tier_update",
        "details": f"Updated Robux tier #{tier_id}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return response.data[0]

@app.delete("/api/admin/robux-tiers/{tier_id}", dependencies=[Depends(require_owner)])
async def admin_delete_robux_tier(tier_id: int):
    supabase.table("robux_tiers").update({"is_active": False}).eq("id", tier_id).execute()
    
    supabase.table("logs").insert({
        "action": "robux_tier_delete",
        "details": f"Deleted Robux tier #{tier_id}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": "Tier deleted"}

@app.get("/api/admin/exchange-rates", dependencies=[Depends(require_owner)])
async def admin_get_exchange_rates():
    return {
        "robux_to_xcoin": settings.ROBUX_TO_XCOIN_RATE,
        "xcoin_to_usd": settings.XCOIN_TO_USD_RATE,
        "robux_to_usd": settings.ROBUX_TO_USD_RATE
    }

@app.put("/api/admin/exchange-rates", dependencies=[Depends(require_owner)])
async def admin_update_exchange_rates(rates: ExchangeRatesUpdate):
    settings.ROBUX_TO_XCOIN_RATE = rates.robux_to_xcoin
    settings.XCOIN_TO_USD_RATE = rates.xcoin_to_usd
    settings.ROBUX_TO_USD_RATE = rates.robux_to_usd
    
    tiers = supabase.table("robux_tiers").select("*").execute()
    for tier in tiers.data:
        new_xcoin_amount = tier["robux_cost"] * rates.robux_to_xcoin
        supabase.table("robux_tiers").update({
            "xcoin_amount": new_xcoin_amount
        }).eq("id", tier["id"]).execute()
        
        if tier.get("display_name") and "→" in tier["display_name"]:
            new_display_name = tier["display_name"].split("→")[0] + f"→ {new_xcoin_amount:,} XC"
            supabase.table("robux_tiers").update({
                "display_name": new_display_name
            }).eq("id", tier["id"]).execute()
    
    supabase.table("logs").insert({
        "action": "rates_update",
        "details": f"Updated exchange rates: {rates.dict()}",
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    return {"message": "Rates updated successfully"}

@app.get("/api/admin/email-stats", dependencies=[Depends(require_owner)])
async def admin_get_email_stats():
    if not email_service:
        return {"error": "Email service not configured"}
    return email_service.get_stats()

@app.get("/api/admin/logs", dependencies=[Depends(require_owner)])
async def admin_get_logs(limit: int = 100, offset: int = 0):
    response = supabase.table("logs").select("*, user:users(username)").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return response.data

# ==================== WEBSOCKET NOTIFICATIONS ====================

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
    
    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
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
    except:
        await websocket.close(code=1008)
        return
    
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
