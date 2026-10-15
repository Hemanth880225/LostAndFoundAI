
import torch
import torch.nn.functional as F

from app.ai.clip_model import get_clip_components


def encode_text(text: str) -> list[float]:
    """Convert a description into a normalized CLIP vector."""
    if not text or not text.strip():
        raise ValueError("Text must not be empty.")

    processor, model, device = get_clip_components()

    inputs = processor(
        text=[text.strip()],
        return_tensors="pt",
        padding=True,
        truncation=True,
    )

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        features = model.get_text_features(**inputs)
        features = F.normalize(features, p=2, dim=-1)

    return features[0].cpu().tolist()
