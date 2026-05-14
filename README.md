# VisCode — AI-Powered Code Visualizer

> Push from MacBook Air → Pull on Office Laptop → Run

---

## 📦 Step 1: Push from This Machine

```bash
cd /Volumes/yeshvault/viscode

# Init git (if not already)
git init
git add -A
git commit -m "VisCode v1.0 — full-stack ready"
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

---

## 🖥️ Step 2: Pull on Office Laptop

```bash
git clone <YOUR_REPO_URL> viscode
cd viscode
```

---

## 🔑 Step 3: Set Up API Key ⚡ IMPORTANT

```bash
cd backend
cp .env.example .env
```

Then edit `backend/.env` and replace the placeholder:
```
OPENAI_API_KEY=sk-proj-YOUR-ACTUAL-KEY-HERE
```

> **This is the only required manual step.** Without a valid API key the scan works but AI analysis will fail.

---

## 🐍 Step 4: Set Up Backend

```bash
cd backend

# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Start the backend
python main.py
```

You should see:
```
VisCode server starting on 0.0.0.0:8000
```

> If port 8000 is busy, it auto-finds the next available port and prints a message.

---

## 🌐 Step 5: Set Up Frontend

Open a **new terminal**:

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

You should see:
```
  VITE v8.x.x  ready in XXXms

  ➜  Local:   http://localhost:5173/
```

---

## 🎯 Step 6: Use It

1. Open **http://localhost:5173** in your browser
2. The green dot (top-right) confirms backend connection
3. Enter a project path, e.g.: `/Users/you/some-project`
4. Click **Estimate** to see cost before committing
5. Click **Analyze** to start the AI pipeline

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| Red dot (backend unreachable) | Is backend running? Check terminal for errors |
| `OPENAI_API_KEY not configured` | Edit `backend/.env` with your actual key |
| `Address already in use` | Auto-handled; or run `lsof -ti:8000 \| xargs kill` |
| `Path is outside allowed directories` | Edit `ALLOWED_PATHS` in `backend/.env` to include your project's parent dir |
| `No supported code files found` | Check the path is correct and contains `.py`, `.js`, `.ts`, etc. files |
| Frontend shows CORS error | Make sure `npm run dev` (not `npm run build`) is running — Vite proxy handles CORS |

---

## 📁 Project Structure

```
viscode/
├── backend/
│   ├── .env.example       ← Copy to .env and add API key
│   ├── main.py            ← FastAPI server entry
│   ├── config.py          ← All configuration
│   ├── requirements.txt   ← Python dependencies
│   ├── services/          ← Scanner, Extractor, Analyzer, etc.
│   ├── models/            ← Pydantic data models
│   └── cache/             ← Disk-based analysis cache
├── frontend/
│   ├── index.html         ← Single page app
│   ├── vite.config.js     ← Dev proxy config
│   ├── package.json       ← Node dependencies
│   └── src/
│       ├── main.js        ← App entry + state management
│       ├── api.js         ← Backend API client
│       ├── canvas.js      ← D3.js visualization engine
│       ├── panel.js       ← Detail panel component
│       └── styles/
│           └── index.css  ← Full design system
└── docs/                  ← Architecture & design docs
```

---

## 💰 Cost Reference

| Model Tier | Pass 1 Model | Pass 2/3 Model | ~Cost per 100 files |
|------------|-------------|----------------|---------------------|
| `fast` | gpt-4.1-mini | gpt-4.1-mini | ~$0.05 |
| `balanced` (default) | gpt-4.1-mini | gpt-4.1 | ~$0.15 |
| `deep` | gpt-4.1 | gpt-4.1 | ~$0.50 |

Always use **Estimate** first to check cost before analyzing!
