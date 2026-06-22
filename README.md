# Amazon Product Analyzer

Chrome extension + Python backend that analyzes Amazon products using Keepa & SellerAmp APIs.

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your Keepa + SellerAmp API keys
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`.

### 2. Chrome Extension

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select the `extension/` folder
4. Browse any Amazon product page — the analyzer panel appears on the right

### Usage

- Navigate to any Amazon product page
- Enter your product cost in the panel
- Click **Analyze** to get Keepa + SellerAmp data
- ROI is color-coded: green (30%+), yellow (10-30%), red (<10%)
