
from io import BytesIO
from pathlib import Path
from typing import Union

import torch
import torch.nn.functional as F
from PIL import Image, UnidentifiedImageError

from app.ai.clip_model import get_clip_components


def encode_image(
    image_source: Union[str, Path, BytesIO, bytes, Image.Image]
) -> list[float]:
    """Convert an image (file path, bytes, BytesIO, or PIL Image) into a normalized CLIP vector."""

    if isinstance(image_source, Image.Image):
        image = image_source.convert("RGB")
    elif isinstance(image_source, (str, Path)):
        path = Path(image_source)

        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")

        try:
            with Image.open(path) as img:
                img.load()
                image = img.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Could not read the image.") from exc
    elif isinstance(image_source, (bytes, bytearray)):
        try:
            with Image.open(BytesIO(image_source)) as img:
                img.load()
                image = img.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Could not read the image.") from exc
    elif isinstance(image_source, BytesIO):
        try:
            with Image.open(image_source) as img:
                img.load()
                image = img.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("Could not read the image.") from exc
    else:
        raise ValueError(f"Unsupported image source type: {type(image_source)}")


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
        if hasattr(features, "pooler_output") and features.pooler_output is not None:
            features = features.pooler_output
        elif hasattr(features, "last_hidden_state") and features.last_hidden_state is not None:
            features = features.last_hidden_state
        features = F.normalize(features, p=2, dim=-1)

    return features[0].cpu().tolist()

