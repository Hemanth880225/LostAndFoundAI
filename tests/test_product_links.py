"""Unit and integration tests for Product-Link Metadata Extraction and SSRF Protection."""

from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient

from app.extensions.product_links.security import validate_safe_url
from app.extensions.product_links.service import extract_product_metadata
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# SSRF Protection Tests
# ---------------------------------------------------------------------------

def test_ssrf_rejects_unsupported_schemes():
    with pytest.raises(Exception) as exc:
        validate_safe_url("file:///etc/passwd")
    assert "unsupported scheme" in str(exc.value).lower()

    with pytest.raises(Exception) as exc2:
        validate_safe_url("ftp://ftp.example.com/file.zip")
    assert "unsupported scheme" in str(exc2.value).lower()


def test_ssrf_rejects_loopback_and_local_hosts():
    with pytest.raises(Exception) as exc1:
        validate_safe_url("http://localhost:8000/internal")
    assert "forbidden" in str(exc1.value).lower()

    with pytest.raises(Exception) as exc2:
        validate_safe_url("http://127.0.0.1/admin")
    assert "forbidden" in str(exc2.value).lower()

    with pytest.raises(Exception) as exc3:
        validate_safe_url("http://169.254.169.254/latest/meta-data/")
    assert "forbidden" in str(exc3.value).lower()


def test_ssrf_endpoint_blocks_forbidden_urls(client):
    # Attempting to fetch localhost via API
    resp = client.post("/api/product-links/enrich", json={"url": "http://localhost:9000/keys"})
    assert resp.status_code == 200  # API returns graceful failed status
    data = resp.json()
    assert data["extraction_status"] == "failed"
    assert "forbidden" in data["error_message"].lower()


# ---------------------------------------------------------------------------
# Metadata Extraction & Parsing Tests
# ---------------------------------------------------------------------------

def test_extract_product_metadata_from_opengraph():
    import asyncio
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta property="og:title" content="Dell XPS 15 9520 Laptop (Silver, 16GB RAM) : Buy Online - Amazon.in" />
      <meta property="og:brand" content="Dell" />
      <meta property="og:image" content="https://m.media-amazon.com/images/I/71xyz.jpg" />
      <meta property="og:description" content="High performance laptop with silver aluminum body and black keyboard." />
      <meta property="product:price:amount" content="124999.00" />
    </head>
    <body><h1>Product Page</h1></body>
    </html>
    """

    mock_client = AsyncMock()
    mock_response = httpx.Response(
        status_code=200,
        html=sample_html,
        request=httpx.Request("GET", "https://www.amazon.in/dp/B0XYZ123"),
    )
    mock_client.get.return_value = mock_response

    with patch("app.extensions.product_links.service.validate_safe_url") as mock_val:
        mock_val.return_value = httpx.URL("https://www.amazon.in/dp/B0XYZ123")
        res = asyncio.run(
            extract_product_metadata(
                url="https://www.amazon.in/dp/B0XYZ123",
                client=mock_client,
            )
        )

    assert res.extraction_status == "success"
    assert "Dell XPS 15" in res.title
    assert res.brand == "Dell"
    assert res.color == "Silver"
    assert res.category == "Electronics"
    assert res.estimated_price_rupees == 124999.0
    assert "71xyz.jpg" in res.image_url


def test_extract_product_metadata_from_json_ld():
    import asyncio
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
      <title>Wildcraft Casual Backpack 30L</title>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": "Wildcraft Trailblazer Navy Blue Backpack",
        "brand": { "@type": "Brand", "name": "Wildcraft" },
        "image": "https://images.wildcraft.com/backpack.jpg",
        "offers": { "@type": "Offer", "price": "1899" }
      }
      </script>
    </head>
    <body></body>
    </html>
    """

    mock_client = AsyncMock()
    mock_response = httpx.Response(
        status_code=200,
        html=sample_html,
        request=httpx.Request("GET", "https://wildcraft.com/trailblazer"),
    )
    mock_client.get.return_value = mock_response

    with patch("app.extensions.product_links.service.validate_safe_url") as mock_val:
        mock_val.return_value = httpx.URL("https://wildcraft.com/trailblazer")
        res = asyncio.run(
            extract_product_metadata(
                url="https://wildcraft.com/trailblazer",
                client=mock_client,
            )
        )

    assert res.extraction_status == "success"
    assert "Wildcraft" in res.title
    assert res.brand == "Wildcraft"
    assert res.color == "Navy Blue"
    assert res.category == "Bags & Luggage"
    assert res.estimated_price_rupees == 1899.0


# ---------------------------------------------------------------------------
# Graceful Degradation & Network Failure Tests
# ---------------------------------------------------------------------------

def test_extraction_fails_gracefully_on_network_timeout():
    import asyncio
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("Connection timed out after 4 seconds")

    with patch("app.extensions.product_links.service.validate_safe_url") as mock_val:
        mock_val.return_value = httpx.URL("https://example-shop.com/item")
        res = asyncio.run(
            extract_product_metadata(
                url="https://example-shop.com/item",
                client=mock_client,
            )
        )

    assert res.extraction_status == "failed"
    assert "timeout" in res.error_message.lower()
    assert res.title is None


def test_api_product_enrichment_endpoint_handles_bad_url_safely(client):
    resp = client.post("/api/product-links/enrich", json={"url": "https://nonexistent-domain-xyz-404.com/prod"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["extraction_status"] == "failed"
