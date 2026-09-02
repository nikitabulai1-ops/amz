# RUCVA

A private, standalone Amazon FBA/FBM virtual assistant. Chat (voice or text)
powered by Claude, a Product Analyzer, a COGS tracker, a sourcing assistant,
a task manager, a metrics dashboard, five financial calculators, and an
ungating tracker — all in one app, deployed to your own URL.

**Design note:** this ships as two files (`index.html` + `app.js`) instead of
one, to keep ~1,500 lines of app logic maintainable. They deploy together as
one site at one URL — functionally identical to a single file.

## What's fully built vs. what needs your own setup

Everything in this folder is complete, working code. Three things can't be
done on your behalf, because they require accounts and credentials that only
you can create:

1. **An Anthropic API key** (powers the AI chat) — costs money per use, billed to you.
2. **A Google Cloud OAuth Client ID** (powers Sheets/Drive) — free, but needs a few
   clicks in Google's own console.
3. **Deploying to Vercel** — free tier is enough for personal use, but it's your
   account, your project.

Everything else — every calculator, every tracker, the whole UI, the chat
backend's code — is done. This doc walks through exactly those three gaps.

---

## 1. Get an Anthropic API key

1. Go to https://console.anthropic.com and sign up / log in.
2. Add a payment method (Settings → Billing) — this is pay-per-use, not a subscription.
   Chat usage for personal use typically runs a few dollars a month.
3. Go to Settings → API Keys → Create Key. Copy it (starts with `sk-ant-...`).
   You won't be able to see it again — if you lose it, make a new one.

Keep this key secret. Don't paste it into the app, into chat with any AI, or
commit it to git. It goes into Vercel's environment variables (step 3 below)
and nowhere else.

---

## 2. Set up Google Sheets & Drive (optional — skip if you don't need it yet)

This uses Google's modern client-side OAuth (Google Identity Services) —
no backend, no client secret, nothing sensitive to protect. Just a Client ID,
which is safe to have visible in the browser.

1. Go to https://console.cloud.google.com and create a new project (or use an existing one).
2. Enable the APIs: search for and enable **Google Sheets API** and **Google Drive API**
   (APIs & Services → Library).
3. Configure the consent screen (APIs & Services → OAuth consent screen):
   - User type: **External** (unless you have a Google Workspace org — then Internal is simpler).
   - Fill in the required fields (app name "RUCVA", your email).
   - Add yourself as a **test user**. This keeps the app in "Testing" mode, which
     skips Google's full app-verification review (that process is for public apps,
     not a personal tool with one user) — but tokens expire after 7 days in Testing
     mode, so you'll re-click "Connect" occasionally. That's expected and fine.
4. Create credentials (APIs & Services → Credentials → Create Credentials → OAuth client ID):
   - Application type: **Web application**.
   - Authorized JavaScript origins: add your Vercel URL once you have it (step 3) —
     e.g. `https://your-project.vercel.app`. You can add `http://localhost:3000` too
     if you want to test locally first.
   - Copy the **Client ID** (ends in `.apps.googleusercontent.com`). You do NOT need
     the client secret — this flow doesn't use one.
5. In the app's **Settings** tab, paste the Client ID, plus:
   - Your **Google Sheet ID** — the long string in your sheet's URL between `/d/` and `/edit`.
   - Optionally a **Drive folder ID** — the string after `/folders/` in a Drive folder's URL.

Click "Connect Google Account" in Settings to authorize. If it fails, the most common
cause is the Vercel URL not matching an authorized JavaScript origin exactly (including
`https://` and no trailing slash).

---

## 3. Deploy to Vercel

1. Go to https://vercel.com and sign up (free) — "Continue with GitHub" is easiest
   since this project is already in a GitHub repo.
2. Click **Add New → Project**, select this repository.
3. **Important:** set the **Root Directory** to `rucva` (this repo has other,
   unrelated projects at the top level) — there's a "Root Directory" field on the
   import screen, click Edit next to it and select `rucva`.
4. Before deploying, expand **Environment Variables** and add:
   - `ANTHROPIC_API_KEY` = the key from step 1
   - (optional) `ANTHROPIC_MODEL` = `claude-sonnet-4-6` (or leave unset for the same default)
5. Click **Deploy**. In a minute or two you'll get a URL like `your-project.vercel.app`.
6. If you set up Google in step 2, go back and add that exact URL to the OAuth
   client's Authorized JavaScript origins (step 2.4) — Google needs to know about
   your real deployed domain.

That's it — open the URL, you have a working app. Every push to your GitHub
branch redeploys automatically once this is connected.

### If deploys fail

- **"maxDuration" error on the Hobby plan:** `vercel.json` requests 60 seconds
  for the chat function (Claude's thinking can take a while). Some Vercel plan
  tiers cap this lower than others — if deploy fails on this, lower the number
  in `vercel.json` or check your plan's current limit in Vercel's docs.
- **Chat says "ANTHROPIC_API_KEY is not configured":** the env var didn't save —
  check Project Settings → Environment Variables in Vercel, and redeploy after
  adding it (env var changes need a new deploy to take effect).

---

## Local testing (optional)

```bash
cd rucva
npm install
vercel dev   # requires: npm install -g vercel, then `vercel login` once
```

This runs the same serverless function locally. Put your key in a local
`.env` file (`ANTHROPIC_API_KEY=...`) — it's gitignored, never commit it.

---

## What each section does

| Section | What it does |
|---|---|
| Dashboard | Today's revenue/profit, monthly goal progress, active inventory, tasks due today |
| AI Chat | Talk or type to RUCVA — it can call the real FBA/FBM calculators mid-conversation |
| Product Analyzer | Answer a few questions about a product, get profit/ROI/margin/breakeven and a Buy/Skip call |
| COGS Tracker | Editable spreadsheet of your inventory — auto-calculates totals and profit, exports to CSV or Sheets |
| Sourcing Assistant | Generates Keepa filter suggestions, a sourcing checklist, and a session tally |
| Daily Tasks | Task list with categories, due dates, overdue flagging, and auto low-stock/stale-inventory alerts |
| Metrics | Log daily numbers, see weekly/monthly totals, month-over-month, projected month-end, FBA vs FBM split |
| Calculator | FBA profit, FBM profit, gift card savings, loan/credit ROI, Q4 compounding — always available |
| Ungating Tracker | Track every brand/category application, status, and follow-up dates |
| Settings | Monthly goal, minimum margin threshold, Claude connection test, Google Sheets/Drive setup |

**Data storage:** everything (products, tasks, metrics, chat history, ungating
records) lives in your browser's local storage — nothing goes to an external
database. Clearing your browser's site data for this URL erases it, so don't
rely on it as your only copy of anything important; export to CSV/Sheets
periodically.

## Known limitations (being straight about scope)

- The AI chat only has two tools wired in (FBA/FBM profit calculators) — it
  doesn't yet read your Keepa/SellerAmp data automatically or pull live numbers
  from Amazon. You paste/describe numbers; it reasons and calculates.
- It has no live internet access — it can't check today's actual fee schedule
  or browse a real listing. It's instructed to say so rather than guess.
- Voice input/output depends on the Web Speech API, which is solid in Chrome/Edge
  and weak-to-absent in Safari/Firefox. The mic and speaker buttons auto-hide if
  your browser doesn't support them.
- The chat supports photo/screenshot attachments (paste with Ctrl+V, or the 📎
  button) — up to 4 images per message, ~4MB each. Attached images aren't kept
  in chat history after that turn (consistent with how Claude's own apps handle
  images in a running conversation) — describe what mattered about one in text
  if you need to refer back to it later.
- The Drive integration can upload/list files but isn't a full file browser —
  good enough for saving notes and pulling up a folder's contents, not a
  Drive replacement.
