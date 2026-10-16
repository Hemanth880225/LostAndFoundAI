# AI Lost & Found System

An AI-powered Lost & Found application designed to help users identify potentially matching lost and found items using text descriptions, image embeddings, item attributes, location, event dates, and rule-based reasoning.

## Overview

Finding a lost item can be difficult when users describe the same object differently or do not know where it was found. This project aims to make the process easier by combining semantic similarity with structured item information and explainable matching rules.

The backend provides REST APIs for reporting lost and found items, uploading item images, finding potential matches, submitting claims, and managing the review and handover process.

## Features

- **Lost and found reports:** Create, retrieve, and list reports with optional filters.
- **AI-assisted matching:** Rank candidate reports using text similarity, image similarity when available, item attributes, location, and event dates.
- **CLIP embeddings:** Use the `openai/clip-vit-base-patch32` model to generate text and image embeddings in a shared representation space.
- **Rule-based reasoning:** Evaluate matching evidence and prioritize rule-supported candidates.
- **Image uploads:** Validate image formats, file sizes, and image dimensions before storing uploaded files.
- **Claim management:** Submit claims against found-item reports.
- **Reviewer authorization:** Protect claim review and handover operations using an `X-Reviewer-Key` header.
- **Handover tracking:** Record successful handovers and update the found item's status.
- **REST API documentation:** Explore endpoints through FastAPI's interactive Swagger UI.
- **Automated tests:** Test core services, validation, matching logic, and HTTP endpoints.

## Technology Stack

- **Language:** Python
- **Backend framework:** FastAPI
- **Database:** SQLite
- **ORM:** SQLAlchemy
- **Data validation:** Pydantic
- **AI model:** OpenAI CLIP ViT-B/32
- **Image processing:** Pillow
- **Testing:** pytest
- **HTTP integration testing:** FastAPI TestClient

## Project Structure

```text
LostAndFoundAI/
├── app/
│   ├── ai/
│   │   ├── clip_model.py
│   │   ├── image_embeddings.py
│   │   ├── ranking.py
│   │   ├── rule_engine.py
│   │   ├── similarity.py
│   │   └── text_embeddings.py
│   ├── core/
│   ├── db/
│   ├── routers/
│   │   ├── claims.py
│   │   ├── images.py
│   │   └── reports.py
│   ├── schemas/
│   ├── services/
│   └── main.py
├── tests/
├── uploads/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Getting Started

### 1. Prerequisites

Install:

- Python 3.11 or later, subject to compatibility with your installed dependencies
- Git
- Internet access for downloading model weights on the first run, unless the model is already cached

The project has been developed and tested in a Python 3.13 environment.

### 2. Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd LostAndFoundAI
```

Replace the placeholder URL with your repository's actual GitHub URL.

### 3. Create a Virtual Environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, consult the Python virtual-environment documentation or activate the environment through your IDE.

### 4. Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

PyTorch and Transformers are used by the CLIP integration. Follow the relevant installation instructions if your machine requires a specific PyTorch build.

### 5. Configure Environment Variables

Create a local `.env` file if your application configuration requires it. Do not commit this file.

The reviewer authentication component reads the following environment variable:

```dotenv
REVIEWER_API_KEY=replace_with_a_long_random_secret
```

Set a strong secret for local development and deployment. The value above is only an example; never use it as a real production credential.

If your deployment uses environment variables configured by the hosting platform, configure the secret there instead.

### 6. Start the Application

From the repository root, run:

```powershell
uvicorn app.main:app --reload
```

The local API should be available at:

- API base URL: `http://127.0.0.1:8000`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- Alternative API documentation: `http://127.0.0.1:8000/redoc`
- Health endpoint: `http://127.0.0.1:8000/api/health`

The SQLite database is configured by the application. Check the database configuration before deploying or changing the working directory.

## API Overview

The following routes are implemented in the backend.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check application health |
| `POST` | `/api/reports` | Create a lost or found report |
| `GET` | `/api/reports` | List reports with optional filtering and limits |
| `GET` | `/api/reports/{report_id}` | Retrieve a report |
| `GET` | `/api/reports/{report_id}/matches` | Find and rank potential matches |
| `POST` | `/api/reports/{found_report_id}/images` | Upload an image for a found-item report |
| `POST` | `/api/reports/{found_report_id}/claims` | Submit a claim against a found item |
| `PATCH` | `/api/reports/claims/{claim_id}/review` | Approve or reject a claim |
| `POST` | `/api/reports/claims/{claim_id}/handover` | Record item handover |

Reviewer-protected operations require the `X-Reviewer-Key` HTTP header. Inspect the API documentation for request fields, response schemas, and validation requirements.

## How AI Matching Works

### 1. Report representation

The system combines relevant report fields, such as item name, category, brand, model, color, and description, into searchable text.

### 2. Embedding generation

The CLIP integration generates vector representations for text and images. Stored embeddings can be reused instead of recomputed when the matching service finds a compatible saved embedding.

### 3. Similarity and metadata scoring

The matching service considers available signals:

- Text similarity
- Image similarity, when both reports have usable image embeddings
- Item attribute similarity
- Location similarity, when location information is available
- Event-date similarity, when dates are available

The current configured component weights are:

| Component | Weight |
|---|---:|
| Text | 30% |
| Image | 35% |
| Attributes | 15% |
| Location | 12% |
| Time | 8% |

Unavailable optional components are omitted and the weights of the included components are normalized.

The resulting score is a ranking score, not a calibrated probability that two reports refer to the same item.

### 4. Rule-based evaluation

The rule engine evaluates evidence from the candidate reports. Rule-supported candidates are ranked before unsupported candidates, with the calculated similarity score used to order candidates within the same plausibility group.

### 5. Ranked results

The API returns the source report ID, number of eligible candidates, candidate details, matching scores, component scores, and reasoning information.

AI-generated matches are suggestions. They should not be treated as proof of ownership; claims require an appropriate review process.

## Image Uploads

The image endpoint validates uploaded files before processing them.

Current implementation limits include:

- Maximum file size: 5 MiB
- Maximum image dimensions: 20 million pixels
- Supported image formats: JPEG, PNG, and WebP

Uploaded images are stored locally in the application's uploads directory. Embedding generation can fail independently of image storage; the API supports reporting a pending embedding status for that case.

For a multi-user deployment, review file storage, access control, backup, retention, and image-serving policies before accepting real user uploads.

## Running Tests

Activate the virtual environment, then run the complete test suite:

```powershell
python -m pytest -v
```

Run a specific test module when debugging:

```powershell
python -m pytest tests/test_api_reports.py -v
python -m pytest tests/test_api_images.py -v
python -m pytest tests/test_api_claims.py -v
python -m pytest tests/test_api_matching.py -v
```

The tests use an in-memory SQLite database for API integration tests and mocks for selected AI operations. Consequently, passing tests validate the tested application behavior but do not, by themselves, establish the accuracy of the real CLIP model or production readiness.

## Security and Data Handling

- Keep `.env` and credentials out of version control.
- Do not commit the local SQLite database or private user uploads.
- Use a strong reviewer key and configure it through a secure environment-variable mechanism.
- Restrict access to reviewer-only operations.
- Treat item descriptions, contact information, and uploaded photographs as potentially sensitive user data.
- Use HTTPS and suitable access controls when deploying the API.
- Review rate limiting, abuse prevention, logging, backups, and database migration practices before production use.

## Current Scope and Limitations

This project is an AI-assisted Lost & Found backend MVP.

- Match quality depends on the quality and completeness of report descriptions, photographs, and metadata.
- Similarity scores are not probabilities.
- Image embeddings may be pending when embedding generation fails.
- The current database configuration uses SQLite.
- Local uploads require a persistent storage strategy if the application is deployed to an environment with ephemeral filesystems.
- Passing automated tests does not replace end-to-end testing, security review, or validation with real-world examples.

## Future Improvements

Potential future enhancements include:

- A production database such as PostgreSQL
- Persistent object storage for uploaded images
- More extensive concurrency and transaction tests
- Improved reviewer authentication and role management
- Monitoring and structured application logs
- Evaluation of matching quality on a labeled dataset
- Deployment automation and database migrations

## License

Choose and add a license before distributing this project publicly. Until a license is added, do not assume others have permission to reuse or redistribute the code.
