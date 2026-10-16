
# AI Lost & Found

FastAPI application for reporting lost and found items, browsing reports, reviewing AI-ranked candidates, uploading item photos, and submitting claims.

## Run locally

Create and activate a Python environment, install the dependencies, then start the server from this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000` for the web application or `http://127.0.0.1:8000/docs` for the API documentation. The SQLite database is created or opened in the current working directory. The first AI match request may download the CLIP model if it is not cached.

See [API_INTEGRATION.md](API_INTEGRATION.md) for endpoint contracts and known limitations.
