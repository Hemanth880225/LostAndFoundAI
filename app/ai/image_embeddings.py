
from pathlib import Path

import torch
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError

from app.ai.clip_model import get_clip_components


def encode_image(image_path: str | Path) -> list[float]:
    """Convert an image into a normalized CLIP vector."""
    path = Path(image_path)

    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Could not read the image.") from exc

    processor, model, device = get_clip_components()

    inputs = processor(
        images=image,
        return_tensors="pt",
    )

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        features = model.get_image_features(**inputs)
        features = F.normalize(features, p=2, dim=-1)

    return features[0].cpu().tolist()
