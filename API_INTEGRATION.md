# API integration

The web interface is served by the existing FastAPI application. The report endpoints below were missing from the provided router and were added without changing database models or matching logic.

## Routes

| Method and path | Purpose | Request / response |
|---|---|---|
| `GET /api/health` | Health check | Existing response with service status and version. |
| `POST /api/reports` | Create a lost or found report | JSON matching `ItemReportCreate`; returns `ItemReportResponse`. |
| `GET /api/reports?report_type=&category=&limit=24&offset=0` | Browse active reports | Optional lost/found type, exact category (case-insensitive), pagination; returns an array of report records. |
| `GET /api/reports/{report_id}` | Read one report | Returns a report record or 404. |
| `GET /api/reports/{report_id}/images` | List public images for a report | Returns image IDs, public `/uploads/...` URLs, and content types. |
| `POST /api/reports/{report_id}/images` | Upload an image | Multipart field `file`; JPEG, PNG, or WebP, maximum 5 MiB and 20 megapixels. Returns image metadata. |
| `GET /api/reports/{report_id}/matches?limit=10` | Compare with active opposite-type reports in the same category | Returns source ID, candidate count, match list, scores, components, and rule-engine reasoning. AI vectors may be generated on the first request and can take time. |
| `POST /api/reports/{found_report_id}/claims` | Submit a claim for a found report | JSON: `lost_report_id`, `claimant_name`, `contact_email`, `claim_message`; returns pending claim metadata. |

## Report JSON

Required: `report_type` (`lost` or `found`), `item_name` (2–120 chars), `category` (2–80), `description` (5–2000), `event_date` (`YYYY-MM-DD`), and `location_text` (2–255). Optional: `color`, `brand`, `model`, `latitude`, and `longitude`. Coordinates must be supplied together.

The browser creates the report as JSON first, then sends an optional image in a separate multipart request. If the upload fails, the page retains the created report ID and retries only the image upload.

## Matching fields

Each match includes `report_id`, `item_name`, `category`, `report_type`, `location_text`, `event_date`, `match_score`, `score_components`, and `reasoning`. The UI displays the backend score and available components. It explicitly describes the score as similarity ranking, not probability or ownership verification. The current service restricts candidates to the same category and active status.

## Limits and missing capabilities

- Search text is filtered in the browser over the records loaded so far; the server does not provide full text search.
- There is no authentication or user-specific report/claim listing, edit, or delete API. “My reports” and “My claims” pages explain this limitation instead of showing invented personal data.
- Claims can be submitted from found-item details, but this API has no reviewer workflow or claim-status listing. Claims remain pending until handled outside the application.
- Coordinates are accepted by the API, but the current form uses approximate location text and does not geocode addresses.
- Uploaded item photos are served from `/uploads/`; report text and contact details are not included in public report responses.
- The matching service uses CLIP vectors; initial matching may need network access to download the configured model if it is not already cached.

## Run

From the project root, activate the environment with the listed dependencies and run:

```powershell
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`. The API schema is at `http://127.0.0.1:8000/docs`.
