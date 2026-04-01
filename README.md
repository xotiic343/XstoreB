# XStore — Digital Marketplace

A production-ready digital marketplace with Robux/X Coin payment integration, built with FastAPI + Supabase backend and a single-file SPA frontend.

---

## Architecture

| Layer | Tech | Host |
|-------|------|------|
| Backend | Python FastAPI (single `main.py`) | Render |
| Frontend | Vanilla HTML/CSS/JS (single `index.html`) | Vercel |
| Database | Supabase (PostgreSQL) | Supabase |
| Auth | Supabase Auth (built-in) | Supabase |

---

## Quick Start

### 1. Supabase Database Setup

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Get your credentials from **Project Settings → API**:
   - `SUPABASE_URL` (Project URL)
   - `SUPABASE_KEY` (anon/public key)
3. Enable email auth in **Authentication → Providers → Email**
4. Tables are auto-created on first API call — no manual SQL needed

---

### 2. Backend Setup (Local)

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create .env file
cp .env.example .env

# Run server
uvicorn main:app --reload --port 8000
```

---

### 3. Frontend Setup (Local)

```bash
cd frontend
python -m http.server 3000
```

Update the `API` constant in `index.html`:
```js
const API = 'http://localhost:8000';  // local
// or
const API = 'https://your-app.onrender.com';  // production
```

---

## Environment Variables

Create `backend/.env`:

```env
# ── SUPABASE (REQUIRED) ──
SUPABASE_URL=your-project-url
SUPABASE_KEY=your-anon-key
SUPABASE_JWT_SECRET=your-jwt-secret  # from Supabase Auth settings

# ── SECURITY ──
SECRET_KEY=your-super-secret-jwt-key-change-this-in-production

# ── ADMIN ACCOUNT ──
ADMIN_EMAIL=admin@xstore.com
ADMIN_PASSWORD=admin123

# ── PAYPAL (Optional) ──
PAYPAL_CLIENT_ID=your_paypal_client_id
PAYPAL_SECRET=your_paypal_secret

# ── STRIPE (Optional) ──
STRIPE_SECRET_KEY=sk_live_...

# ── EMAIL (Optional) ──
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your_app_password

# ── ROBLOX (Optional) ──
ROBLOX_COOKIE=  # .ROBLOSECURITY cookie for authenticated calls

# ── FRONTEND ──
FRONTEND_URL=https://your-app.vercel.app

# ── EXCHANGE RATES ──
ROBUX_TO_XCOIN_RATE=10      # 1 Robux = 10 X Coin
XCOIN_TO_USD_RATE=100       # 100 X Coin = $1 USD
ROBUX_TO_USD_RATE=80        # 80 Robux = $1 USD
```

---

## Deployment

### Backend → Render

1. Create a new **Web Service** on [render.com](https://render.com)
2. Connect your GitHub repo
3. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add all environment variables in Render dashboard
5. Deploy — get your URL: `https://your-app.onrender.com`

### Frontend → Vercel

1. Create a new project on [vercel.com](https://vercel.com)
2. Upload or connect the `frontend/` folder
3. No build config needed (static HTML)
4. Update `API` constant in `index.html` before deploying:
   ```js
   const API = 'https://your-app.onrender.com';
   ```

---

## Product Categories

| Category | Examples |
|----------|---------|
| Discord Bots | Custom bots, MEE6 setups, moderation tools, source code |
| Roblox Items | Limited items, game passes, UGC assets, Robux codes |
| Accounts | Minecraft, Steam, Discord, Spotify, gaming accounts |
| Apps & Code | Bot source code, website templates, scripts, assets |
| 3D Prints | Keychains, phone cases, figurines, custom prints |
| Game Keys | Steam, Xbox, PlayStation, Nintendo codes |
| Edits | Promo videos, thumbnails, animations, overlays |

---

## Payment Methods

| Method | Description |
|--------|-------------|
| **Robux** | Pay with Roblox game passes — automated inventory verification |
| **X Coin** | Store credit — earn via purchases, refunds, or admin adjustments |
| **X Coin + Robux** | Split payment between store credit and Robux |
| **PayPal** | Traditional PayPal checkout (optional) |
| **Stripe** | Credit/debit card payments (optional) |
| **CashApp** | Manual verification payment (admin confirms) |

---

## X Coin System

### How Users Earn X Coin
- **Buy X Coin** — Purchase with real Robux via game passes
- **Refunds** — Admin issues refunds in X Coin (no real money refunds)
- **Admin adjustments** — Promotions, compensation, giveaways

### How Users Spend X Coin
- Any product can be paid with X Coin
- Split payment: X Coin + Robux game passes
- Full X Coin payment if balance covers entire cost

### Exchange Rate Example
```
Rate: 10 XC = 1 Robux, 80 Robux = $1, 100 XC = $1
Product price: $10
→ X Coin: 10 × 100 = 1,000 XC
→ Robux: 1,000 ÷ 10 = 100 R$
```

### Refund Example
```
User bought a $10 item with Robux
Admin refunds → 1,000 X Coin added to balance
User can spend X Coin on any future purchase
```

---

## Roblox Game Pass Configuration

### Step 1: Create Game Passes
1. Go to your Roblox game → **Create Game Pass**
2. Create passes for each tier (e.g., 80, 400, 800, 1700, 4500, 10000 Robux)
3. Copy each **Game Pass ID** from URL: `roblox.com/game-pass/XXXXXXX/name`

### Step 2: Configure in Admin Panel
1. Login as admin → click ⚙️ floating button
2. Go to **Robux Tiers** tab
3. Edit each tier with your real Game Pass IDs
4. Set exchange rates in **Rates** tab

---

## Admin Panel

Access: Login as admin → floating ⚙️ button (bottom-left)

| Tab | Features |
|-----|----------|
| Analytics | Sales overview, top products, X Coin stats |
| Products | Add/edit/delete products, manage stock |
| Orders | View orders, complete, refund, verify CashApp |
| Users | View users, adjust X Coin balance, ban/unban |
| Robux Tiers | Configure game passes for X Coin purchases |
| Rates | Set exchange rates (XC → Robux → USD) |
| Logs | Audit log of all admin actions |

---

## Database Schema

### Tables (auto-created)

| Table | Description |
|-------|-------------|
| `users` | User accounts, balances, Roblox links, roles |
| `products` | Product catalog with categories, pricing, stock |
| `orders` | Order records with status and payment info |
| `order_items` | Individual items within orders |
| `xcoin_transactions` | X Coin balance changes history |
| `xcoin_packages` | Robux tiers for buying X Coin |
| `logs` | Admin action audit trail |

---

## API Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create new account |
| POST | `/api/auth/login` | Login with email/password |
| GET | `/api/auth/me` | Get current user profile |
| POST | `/api/auth/link-roblox` | Link Roblox account |

### Products
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/products` | List products (with filters) |
| GET | `/api/products/categories` | Get all categories |
| GET | `/api/products/{id}` | Get single product |
| POST | `/api/products` | Create product (admin) |
| PUT | `/api/products/{id}` | Update product (admin) |
| DELETE | `/api/products/{id}` | Delete product (admin) |

### Orders
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/orders` | Create new order |
| GET | `/api/orders` | Get user's orders |
| GET | `/api/orders/{id}` | Get single order |

### X Coin
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/xcoin/balance` | Get X Coin balance |
| GET | `/api/xcoin/packages` | Get available Robux tiers |
| POST | `/api/xcoin/buy` | Buy X Coin with Robux |
| GET | `/api/xcoin/verify/{session_id}` | Check verification status |

### Admin (owner only)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/analytics` | Sales and X Coin stats |
| GET | `/api/admin/orders` | All orders with filters |
| POST | `/api/admin/orders/refund` | Refund order in X Coin |
| GET | `/api/admin/users` | All users |
| POST | `/api/admin/users/xcoin` | Adjust user X Coin |
| GET | `/api/admin/xcoin-packages` | List Robux tiers |
| POST | `/api/admin/xcoin-packages` | Create tier |
| PUT | `/api/admin/xcoin-packages/{id}` | Update tier |
| DELETE | `/api/admin/xcoin-packages/{id}` | Delete tier |
| GET | `/api/admin/logs` | Audit logs |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | API info |

---

## Roblox Verification Flow

1. User selects X Coin package(s)
2. System creates verification session
3. User purchases game passes on Roblox
4. Backend continuously checks Roblox inventory API
5. When all passes verified → X Coin credited instantly
6. User can now spend X Coin on any product

---

## Security Notes

- Supabase Auth handles password hashing and JWT tokens
- All admin routes require `is_owner: true`
- X Coin reservations before Robux verification prevents fraud
- Roblox API checks are rate-limited and timeout after 2 minutes
- CORS restricted to your frontend domains
- Input validation via Pydantic on all endpoints

For production, update CORS in `main.py`:
```python
allow_origins=["https://your-app.vercel.app"]
```

---

## Project Structure

```
xstore/
├── backend/
│   ├── main.py          # All FastAPI logic (single file)
│   ├── requirements.txt # Python dependencies
│   └── .env             # Environment variables (not committed)
├── frontend/
│   └── index.html       # Complete SPA (single file)
└── README.md
```

---

## Dependencies

### Backend (`requirements.txt`)
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
supabase==2.5.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
pydantic[email]==2.8.2
python-dotenv==1.0.1
httpx==0.27.2
stripe==10.8.0
```

### Frontend
- GSAP (animations)
- Google Fonts
- No build step — pure HTML/CSS/JS

---

## Default Admin Account

Created automatically on first server start:

- **Email:** `admin@xstore.com` (set via `ADMIN_EMAIL`)
- **Password:** `admin123` (set via `ADMIN_PASSWORD`)

**Change these in production!**

---

## Support

For issues or questions:
1. Check Render logs for backend errors
2. Check Supabase logs for database issues
3. Verify Roblox game passes exist and are active

---


## License

Proprietary — All rights reserved.

This software is confidential and proprietary. Unauthorized copying, distribution, modification, or use of this software, via any medium, is strictly prohibited.

---

## Troubleshooting

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| **Supabase connection error** | Verify `SUPABASE_URL` and `SUPABASE_KEY` are correct. Check if your Supabase project is active. |
| **Auth not working** | Enable Email provider in Supabase Auth settings. Ensure `SUPABASE_JWT_SECRET` matches your project. |
| **Tables not created** | Tables auto-create on first API call. Make a request to `/api/products` first. |
| **Roblox verification fails** | Ensure user has linked Roblox account. Verify game pass IDs are correct and active. |
| **X Coin not updating** | Check `xcoin_transactions` table for failed records. Verify exchange rates are set correctly. |
| **CORS errors** | Update `allow_origins` in `main.py` with your frontend URL. Re-deploy after changes. |
| **PayPal/Stripe not working** | Ensure webhook URLs are configured correctly. Check API keys are valid. |
| **Admin panel not showing** | Verify `is_owner` is set to `true` for your admin user in Supabase `users` table. |

---

## Performance Optimization

### Backend
- Use Supabase connection pooling for better performance
- Enable query caching for frequently accessed data
- Implement pagination for product listings (default: 50 per page)
- Use background tasks for Roblox verification (non-blocking)

### Frontend
- GSAP animations are optimized for 60fps
- Lazy loading for product images
- Local storage cart persistence (no API calls for cart operations)
- Debounced search input (200ms delay)

---

## Monitoring & Logging

### Supabase Logs
- View real-time logs in Supabase Dashboard → Logs
- Monitor auth events, database queries, and errors

### Render Logs
- Access logs via Render Dashboard → your service → Logs
- Set up log streaming to external services (optional)

### Application Logs
- All admin actions are recorded in `logs` table
- X Coin transactions tracked in `xcoin_transactions`
- Order status changes logged automatically

---

## Customization Guide

### Changing the Theme
- Edit CSS variables in `index.html` `:root` section
- Admin theme toggles automatically when admin logs in

### Adding New Product Categories
1. Add category to category chips in HTML
2. Add to category list in admin product form
3. No database changes needed — category is a text field

### Adding Payment Methods
1. Extend `payment_method` enum in order creation
2. Add frontend UI in checkout modal
3. Implement webhook handler if needed

### Modifying Exchange Rates
- Change default values in `.env`
- Update via Admin Panel → Rates tab
- Changes apply immediately to all new orders

---

## Security Best Practices

### Production Checklist

- [ ] Change `SECRET_KEY` to a strong random value
- [ ] Change default admin credentials
- [ ] Enable Supabase Row Level Security (RLS)
- [ ] Restrict CORS to your frontend domain only
- [ ] Use environment variables for all secrets (never hardcode)
- [ ] Set up HTTPS for all domains (Render/Vercel provides this)
- [ ] Regularly update dependencies
- [ ] Monitor Supabase usage to avoid rate limits
- [ ] Enable 2FA for Supabase account
- [ ] Use strong passwords for admin and database

### Supabase RLS Policies (Recommended)

```sql
-- Users can read their own data
CREATE POLICY "Users can read own data" ON users
  FOR SELECT USING (auth.uid() = id);

-- Products readable by everyone
CREATE POLICY "Products readable by all" ON products
  FOR SELECT USING (true);

-- Orders readable by owner
CREATE POLICY "Orders readable by owner" ON orders
  FOR SELECT USING (auth.uid() = user_id);
```

---

## Scaling Considerations

### When to Scale

| Metric | Threshold | Action |
|--------|-----------|--------|
| Users | 10,000+ | Upgrade Supabase plan |
| Products | 1,000+ | Implement search indexing |
| Orders/day | 500+ | Add Redis caching |
| Roblox verifications | 100 concurrent | Increase background workers |

### Recommended Upgrades
- **Supabase**: Pro plan ($25/mo) for increased limits
- **Render**: Starter plan ($7/mo) for 24/7 uptime
- **Vercel**: Pro plan ($20/mo) for team collaboration
- **Database indexing**: Add indexes on frequently queried columns

---

## Backup & Disaster Recovery

### Supabase Backups
- Automatic daily backups included
- Point-in-time recovery available on Pro plan
- Download backups from Supabase Dashboard

### Manual Backup
```bash
# Export all tables to JSON
curl -X GET "https://your-project.supabase.co/rest/v1/orders" \
  -H "apikey: YOUR_KEY" > orders_backup.json
```

### Restore Procedure
1. Download latest backup from Supabase
2. Use Supabase SQL Editor to restore tables
3. Verify data integrity before going live

---

## Support & Community

### Official Channels
- **Documentation**: [Current README]
- **Issues**: GitHub Issues (if public)
- **Email Support**: admin@xstore.com (configured in SMTP)

### Self-Help Resources
- FastAPI Docs: https://fastapi.tiangolo.com
- Supabase Docs: https://supabase.com/docs
- Roblox API Docs: https://create.roblox.com/docs/reference/cloud

---

## Changelog

### v1.0.0 (Current)
- Initial release
- Full product catalog with categories
- X Coin store credit system
- Roblox game pass verification
- PayPal and Stripe integration
- Admin dashboard with analytics
- Email receipts (SMTP)
- User profiles with Roblox linking
- Split payment support
- Audit logging

### Planned Features (v1.1.0)
- [ ] Discord OAuth login
- [ ] Affiliate/referral program
- [ ] Discount codes and coupons
- [ ] Automated email notifications
- [ ] Product reviews and ratings
- [ ] Wishlist feature
- [ ] Mobile app (React Native)
- [ ] WebSocket for real-time notifications
- [ ] Multi-language support
- [ ] Dark/light theme toggle

---

## Contributing

This is a private project. For internal contributions:

1. Fork the repository (if applicable)
2. Create a feature branch: `git checkout -b feature/name`
3. Commit changes: `git commit -m 'Add feature'`
4. Push to branch: `git push origin feature/name`
5. Submit for review

### Code Style
- Python: PEP 8 standards
- JavaScript: ES6+ with async/await
- CSS: BEM naming convention (optional)

---

## Acknowledgments

- **FastAPI** — Modern Python web framework
- **Supabase** — Open-source Firebase alternative
- **Roblox** — Game platform and API
- **GSAP** — Professional-grade animations
- **Stripe/PayPal** — Payment processing

---

## Contact

For business inquiries, support, or custom development:

- **Website**: https://xotiicsplaza.us
- **Discord**: [Join our server](https://discord.gg/SVvZFnct37)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2024-04-01 | Initial production release |
| 1.0.1 | TBD | Bug fixes and minor improvements |

---

**© 2026 Xotiic. All rights reserved.**
