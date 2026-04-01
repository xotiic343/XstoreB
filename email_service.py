"""
Email Service Library (ESL) for XStore
Handles all email communications with templates, queuing, and rate limiting
"""

import os
import smtplib
import asyncio
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from pathlib import Path
import json
import hashlib
from collections import deque
import threading
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmailTemplate:
    """Email template manager with HTML templates"""
    
    TEMPLATES = {
        'welcome': {
            'subject': '🎉 Welcome to XStore, {username}!',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
                    .content { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                    .header { text-align: center; margin-bottom: 30px; }
                    .logo { font-size: 32px; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
                    .button { display: inline-block; padding: 12px 24px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
                    .footer { text-align: center; margin-top: 30px; font-size: 12px; color: #999; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <div class="header">
                            <div class="logo">✨ XSTORE ✨</div>
                        </div>
                        <h2>Welcome {username}!</h2>
                        <p>Thank you for joining XStore! We're excited to have you as part of our community.</p>
                        <p>Your account is ready to go. Here's what you can do:</p>
                        <ul>
                            <li>🛍️ Browse our digital products</li>
                            <li>⚡ Earn X Coin with every purchase</li>
                            <li>🎮 Link your Roblox account for instant purchases</li>
                            <li>💸 Get affiliate commissions by referring friends</li>
                        </ul>
                        <center><a href="{dashboard_url}" class="button">Start Shopping →</a></center>
                        <p style="margin-top: 20px;">You start with <strong>⚡ {xcoin_bonus} X Coin</strong> as a welcome gift!</p>
                        <div class="footer">
                            <p>Need help? Contact us at support@xstore.com</p>
                            <p>© 2024 XStore. All rights reserved.</p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'order_confirmation': {
            'subject': '✅ Order Confirmation #{order_id} - XStore',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; }
                    .order-details { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }
                    .item { padding: 10px 0; border-bottom: 1px solid #eee; }
                    .total { font-size: 20px; font-weight: bold; color: #667eea; margin-top: 15px; }
                    .status { display: inline-block; padding: 5px 10px; background: #10b981; color: white; border-radius: 5px; font-size: 12px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>Order Confirmed! 🎉</h2>
                        <p>Hello {username},</p>
                        <p>Your order <strong>#{order_id}</strong> has been confirmed and is being processed.</p>
                        
                        <div class="order-details">
                            <h3>Order Details:</h3>
                            {items_list}
                            <div class="total">Total: ${total_usd}</div>
                            <div>Payment Method: {payment_method}</div>
                            <div>Status: <span class="status">{status}</span></div>
                        </div>
                        
                        <p>You can track your order status in your dashboard.</p>
                        <center><a href="{dashboard_url}" class="button">View Order →</a></center>
                        
                        <p style="margin-top: 20px;">Thank you for shopping with XStore!</p>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'order_shipped': {
            'subject': '📦 Order #{order_id} Has Been Shipped!',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; }
                    .tracking { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; text-align: center; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>Your Order is on the Way! 🚚</h2>
                        <p>Hello {username},</p>
                        <p>Great news! Your order <strong>#{order_id}</strong> has been shipped.</p>
                        
                        <div class="tracking">
                            <strong>Tracking Number:</strong> {tracking_number}<br>
                            <strong>Estimated Delivery:</strong> {estimated_delivery}
                        </div>
                        
                        <center><a href="{tracking_url}" class="button">Track Package →</a></center>
                        <p>Thank you for choosing XStore!</p>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'xcoin_purchase': {
            'subject': '⚡ X Coin Added to Your Account!',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; text-align: center; }
                    .xcoin-amount { font-size: 48px; font-weight: bold; color: #f59e0b; margin: 20px 0; }
                    .balance { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>X Coin Added! ⚡</h2>
                        <p>Hello {username},</p>
                        <div class="xcoin-amount">+{xcoin_amount} X Coin</div>
                        <div class="balance">
                            <strong>New Balance:</strong> {new_balance} X Coin
                        </div>
                        <p>You purchased this through: {purchase_method}</p>
                        <center><a href="{dashboard_url}" class="button">View Balance →</a></center>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'affiliate_commission': {
            'subject': '💰 You Earned ${commission_amount} from Affiliate Sale!',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; text-align: center; }
                    .commission { font-size: 48px; font-weight: bold; color: #10b981; margin: 20px 0; }
                    .referral-link { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; word-break: break-all; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>New Affiliate Commission! 🎉</h2>
                        <p>Hello {username},</p>
                        <div class="commission">+${commission_amount}</div>
                        <p>You earned this commission from a referral purchase!</p>
                        <div class="referral-link">
                            <strong>Your Referral Link:</strong><br>
                            {referral_link}
                        </div>
                        <center><a href="{dashboard_url}" class="button">View Earnings →</a></center>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'coupon_created': {
            'subject': '🎫 Your Coupon Code: {coupon_code}',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; text-align: center; }
                    .coupon-code { font-size: 32px; font-weight: bold; letter-spacing: 2px; background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; font-family: monospace; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>You've Got a Coupon! 🎫</h2>
                        <p>Hello {username},</p>
                        <div class="coupon-code">{coupon_code}</div>
                        <p><strong>{discount_value} {discount_type}</strong> off your next purchase!</p>
                        {expiry_message}
                        <center><a href="{shop_url}" class="button">Shop Now →</a></center>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'low_stock_alert': {
            'subject': '⚠️ Low Stock Alert: {product_name}',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; }
                    .alert { background: #fee2e2; border-left: 4px solid #ef4444; padding: 15px; margin: 20px 0; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>⚠️ Low Stock Alert</h2>
                        <div class="alert">
                            <strong>{product_name}</strong> is running low!<br>
                            Current stock: <strong>{current_stock}</strong> units<br>
                            Sold today: <strong>{sales_today}</strong> units
                        </div>
                        <p>Action needed: Restock this product soon to avoid missing sales.</p>
                        <center><a href="{admin_url}" class="button">Manage Products →</a></center>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'review_reply': {
            'subject': '💬 A Merchant Replied to Your Review',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; }
                    .review-box { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 3px solid #667eea; }
                    .reply-box { background: #e8f0fe; padding: 15px; border-radius: 5px; margin: 20px 0; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>Someone Replied to Your Review! 💬</h2>
                        <p>Hello {username},</p>
                        
                        <div class="review-box">
                            <strong>Your Review for {product_name}:</strong><br>
                            "{your_comment}"
                        </div>
                        
                        <div class="reply-box">
                            <strong>Reply from XStore Team:</strong><br>
                            "{reply}"
                        </div>
                        
                        <center><a href="{product_url}" class="button">View Review →</a></center>
                    </div>
                </div>
            </body>
            </html>
            """
        },
        
        'password_reset': {
            'subject': '🔐 Password Reset Request - XStore',
            'html': """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body { font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; }
                    .container { max-width: 600px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
                    .content { background: white; padding: 30px; border-radius: 10px; text-align: center; }
                    .reset-code { font-size: 36px; font-weight: bold; letter-spacing: 5px; background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; font-family: monospace; }
                    .warning { font-size: 12px; color: #999; margin-top: 20px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="content">
                        <h2>Password Reset Request</h2>
                        <p>Hello {username},</p>
                        <p>We received a request to reset your password. Use the code below:</p>
                        <div class="reset-code">{reset_code}</div>
                        <p>This code expires in <strong>15 minutes</strong>.</p>
                        <p>If you didn't request this, you can safely ignore this email.</p>
                        <div class="warning">
                            For security, never share this code with anyone.
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
        }
    }
    
    @classmethod
    def render(cls, template_name: str, data: Dict[str, Any]) -> Dict[str, str]:
        """Render email template with data"""
        template = cls.TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")
        
        # Fill in the template
        html_content = template['html']
        subject = template['subject']
        
        for key, value in data.items():
            html_content = html_content.replace(f"{{{key}}}", str(value))
            subject = subject.replace(f"{{{key}}}", str(value))
        
        # Add base styles and tracking pixel (optional)
        tracking_pixel = f'<img src="{data.get("tracking_url", "")}" width="1" height="1" style="display:none;">'
        html_content = html_content.replace('</body>', f'{tracking_pixel}</body>')
        
        return {
            'subject': subject,
            'html': html_content,
            'text': cls._html_to_text(html_content)  # Plain text version
        }
    
    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text (simplified)"""
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


class EmailQueue:
    """Email queue with rate limiting and retry logic"""
    
    def __init__(self, max_queue_size: int = 1000, rate_limit: int = 10):
        self.queue = deque(maxlen=max_queue_size)
        self.rate_limit = rate_limit  # emails per second
        self.last_sent_times = deque(maxlen=rate_limit)
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
    def add(self, email_data: Dict[str, Any]):
        """Add email to queue"""
        with self.lock:
            self.queue.append({
                **email_data,
                'retry_count': 0,
                'added_at': datetime.now()
            })
    
    def start(self):
        """Start the email processing thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._process_queue, daemon=True)
            self.thread.start()
            logger.info("Email queue processor started")
    
    def stop(self):
        """Stop the email processing thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
            logger.info("Email queue processor stopped")
    
    def _process_queue(self):
        """Process emails from queue with rate limiting"""
        while self.running:
            try:
                with self.lock:
                    if not self.queue:
                        time.sleep(0.1)
                        continue
                    
                    # Rate limiting
                    now = time.time()
                    self.last_sent_times = [t for t in self.last_sent_times if now - t < 1]
                    
                    if len(self.last_sent_times) >= self.rate_limit:
                        time.sleep(0.1)
                        continue
                    
                    email = self.queue.popleft()
                    self.last_sent_times.append(now)
                
                # Send email
                success = self._send_email(email)
                
                if not success and email['retry_count'] < 3:
                    # Retry with backoff
                    email['retry_count'] += 1
                    time.sleep(2 ** email['retry_count'])
                    with self.lock:
                        self.queue.append(email)
                elif not success:
                    logger.error(f"Failed to send email after 3 retries: {email.get('to')}")
                    
            except Exception as e:
                logger.error(f"Error in email queue processor: {e}")
                time.sleep(1)
    
    def _send_email(self, email: Dict[str, Any]) -> bool:
        """Actually send the email via SMTP"""
        try:
            settings = email.get('settings', {})
            
            msg = MIMEMultipart("alternative")
            msg["Subject"] = email['subject']
            msg["From"] = settings.get('smtp_user', email.get('from_email'))
            msg["To"] = email['to']
            
            # Attach HTML and plain text
            msg.attach(MIMEText(email.get('text', ''), "plain"))
            msg.attach(MIMEText(email['html'], "html"))
            
            with smtplib.SMTP(
                settings.get('smtp_host', 'smtp.gmail.com'),
                settings.get('smtp_port', 587)
            ) as server:
                server.starttls()
                server.login(
                    settings.get('smtp_user'),
                    settings.get('smtp_pass')
                )
                server.send_message(msg)
            
            logger.info(f"Email sent to {email['to']}: {email['subject']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


class EmailService:
    """Main Email Service with templates, queue, and analytics"""
    
    def __init__(self, smtp_config: Dict[str, str]):
        self.smtp_config = smtp_config
        self.queue = EmailQueue()
        self.queue.start()
        self.sent_count = 0
        self.failed_count = 0
        self.tracking_data = {}
        
    def send_email(self, to: str, template_name: str, data: Dict[str, Any]) -> bool:
        """Send email using template"""
        try:
            # Prepare template data
            template_data = {
                **data,
                'dashboard_url': self.smtp_config.get('dashboard_url', 'https://xstore.com/dashboard'),
                'shop_url': self.smtp_config.get('shop_url', 'https://xstore.com/shop'),
                'admin_url': self.smtp_config.get('admin_url', 'https://xstore.com/admin'),
                'tracking_url': self._generate_tracking_url(to, template_name)
            }
            
            # Render template
            rendered = EmailTemplate.render(template_name, template_data)
            
            # Prepare email
            email_data = {
                'to': to,
                'subject': rendered['subject'],
                'html': rendered['html'],
                'text': rendered.get('text', ''),
                'from_email': self.smtp_config.get('smtp_user'),
                'settings': self.smtp_config,
                'template': template_name,
                'data': template_data
            }
            
            # Add to queue
            self.queue.add(email_data)
            self.sent_count += 1
            
            # Track analytics
            self._track_email(to, template_name)
            
            return True
            
        except Exception as e:
            logger.error(f"Error preparing email: {e}")
            self.failed_count += 1
            return False
    
    def send_welcome_email(self, to: str, username: str, xcoin_bonus: int = 100):
        """Send welcome email to new users"""
        return self.send_email(to, 'welcome', {
            'username': username,
            'xcoin_bonus': xcoin_bonus
        })
    
    def send_order_confirmation(self, to: str, username: str, order_id: int, 
                                items: List[Dict], total_usd: float, 
                                payment_method: str, status: str):
        """Send order confirmation email"""
        items_html = ""
        for item in items:
            items_html += f"""
            <div class="item">
                <strong>{item['product_title']}</strong> x {item['quantity']}<br>
                ${item['price']} each
            </div>
            """
        
        return self.send_email(to, 'order_confirmation', {
            'username': username,
            'order_id': order_id,
            'items_list': items_html,
            'total_usd': total_usd,
            'payment_method': payment_method,
            'status': status
        })
    
    def send_xcoin_purchase(self, to: str, username: str, xcoin_amount: int, 
                           new_balance: int, purchase_method: str):
        """Send X Coin purchase confirmation"""
        return self.send_email(to, 'xcoin_purchase', {
            'username': username,
            'xcoin_amount': xcoin_amount,
            'new_balance': new_balance,
            'purchase_method': purchase_method
        })
    
    def send_affiliate_commission(self, to: str, username: str, commission_amount: float, referral_link: str):
        """Send affiliate commission notification"""
        return self.send_email(to, 'affiliate_commission', {
            'username': username,
            'commission_amount': commission_amount,
            'referral_link': referral_link
        })
    
    def send_coupon_email(self, to: str, username: str, coupon_code: str,
                         discount_value: str, discount_type: str, expiry_days: int = 7):
        """Send coupon code email"""
        expiry_message = f"<p>Expires in {expiry_days} days!</p>" if expiry_days else ""
        
        return self.send_email(to, 'coupon_created', {
            'username': username,
            'coupon_code': coupon_code,
            'discount_value': discount_value,
            'discount_type': discount_type,
            'expiry_message': expiry_message
        })
    
    def send_low_stock_alert(self, product_name: str, current_stock: int, sales_today: int):
        """Send low stock alert to admin"""
        return self.send_email(self.smtp_config.get('admin_email', 'admin@xstore.com'), 
                              'low_stock_alert', {
            'product_name': product_name,
            'current_stock': current_stock,
            'sales_today': sales_today
        })
    
    def send_review_reply(self, to: str, username: str, product_name: str,
                         your_comment: str, reply: str, product_url: str):
        """Send notification when review gets a reply"""
        return self.send_email(to, 'review_reply', {
            'username': username,
            'product_name': product_name,
            'your_comment': your_comment,
            'reply': reply,
            'product_url': product_url
        })
    
    def send_password_reset(self, to: str, username: str, reset_code: str):
        """Send password reset email"""
        return self.send_email(to, 'password_reset', {
            'username': username,
            'reset_code': reset_code
        })
    
    def _generate_tracking_url(self, email: str, template: str) -> str:
        """Generate tracking pixel URL"""
        tracking_id = hashlib.md5(f"{email}{template}{datetime.now()}".encode()).hexdigest()[:16]
        return f"{self.smtp_config.get('tracking_url', '')}/track/{tracking_id}"
    
    def _track_email(self, to: str, template: str):
        """Track email sent"""
        date_key = datetime.now().strftime('%Y-%m-%d')
        if date_key not in self.tracking_data:
            self.tracking_data[date_key] = {}
        
        if template not in self.tracking_data[date_key]:
            self.tracking_data[date_key][template] = 0
        
        self.tracking_data[date_key][template] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get email service statistics"""
        return {
            'total_sent': self.sent_count,
            'total_failed': self.failed_count,
            'queue_size': len(self.queue.queue),
            'daily_stats': self.tracking_data.get(datetime.now().strftime('%Y-%m-%d'), {}),
            'rate_limit': self.queue.rate_limit
        }
    
    def shutdown(self):
        """Shutdown email service gracefully"""
        self.queue.stop()
        logger.info("Email service shut down")
