# 🛒 OGGY SITE CHKR — Telegram Bot

Full-featured Shopify site checker + scraper bot.

---

## ✅ Features

| Feature | Command |
|---|---|
| Auto-check .txt files | Send `.txt` file → instant check |
| Check links/msg | `/check` (reply to msg or file) |
| Clean txt | `/cleantxt` (reply to msg/file) |
| Categorize by price | `/cat` (reply to msg/file) |
| Export by price | `/export 5` (reply to file) |
| Google scraper | `/scrape` → keyword → count |
| Stop mid-session | `/stop` |
| Cancel FSM | `/cancel` |
| Admin panel | `/admin` (owner only) |
| Stats | inline button on `/start` |

---

## 🚀 Deploy on Render (Free Tier)

### Step 1 — Upload to GitHub
1. Create a new GitHub repo
2. Upload all 5 files: `bot.py`, `scraper.py`, `requirements.txt`, `render.yaml`, `Dockerfile`

### Step 2 — Create Render Service
1. Go to [render.com](https://render.com) → New → **Background Worker**
2. Connect your GitHub repo
3. Set:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`

### Step 3 — Set Environment Variables
In Render → Environment tab, add:

| Key | Value |
|---|---|
| `BOT_TOKEN` | `8558886316:AAG3qGKnqX_o2nBb0NVRlM4E8B4oxRpCzKo` |
| `OWNER_ID` | Your Telegram numeric user ID |

> Get your ID by messaging [@userinfobot](https://t.me/userinfobot) on Telegram.

### Step 4 — Deploy
Click **Deploy** → Wait ~2 min → Bot goes live!

---

## 📁 File Structure

```
oggy_site_chkr/
├── bot.py          ← Main bot logic
├── scraper.py      ← Google scraper engine
├── requirements.txt
├── render.yaml     ← Render config
├── Dockerfile      ← Docker deploy
└── README.md
```

---

## 💬 Commands Reference

```
/start        → Welcome screen
/help         → Full command list
/check        → Reply to msg/file to check Shopify sites
/cleantxt     → Reply to msg/file, returns clean domain list
/cat          → Reply to msg/file, categorizes by price tier
/export N     → Reply to file, exports sites ≤ $N
/scrape       → Scrape Google for Shopify sites by keyword
/stop         → Stop current running session (returns partial results)
/cancel       → Cancel any pending input state
/admin        → Owner-only control panel
```

---

## 💰 Price Tiers

- 0$–5$
- 5$–10$
- 10$–20$
- 20$–50$
- 50$–100$
- 100$+

---

## 🔧 How Checking Works

1. Fetches `/products.json` from each site → confirms it's Shopify
2. Extracts lowest product price from all variants
3. Checks `/checkout` and `/cart` pages for captcha patterns
4. Categorizes into price tiers
5. On early stop (`/stop`) → sends: checked sites, clean sites, remaining sites

---

## 📌 Notes

- The scraper uses Google dork queries + domain verification
- No Google API key needed (uses direct search with rotating user agents)
- Concurrent checks: 20 parallel (configurable in `bot.py`)
- Concurrent scrape verifications: 8 parallel
