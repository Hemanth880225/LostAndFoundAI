
import torch
import torch.nn.functional as F

from app.ai.clip_model import get_clip_components


def encode_text(text: str) -> list[float]:
    """Convert a description into a normalized CLIP vector."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Text must be a non-empty string.")

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
        if hasattr(features, "pooler_output") and features.pooler_output is not None:
            features = features.pooler_output
        elif hasattr(features, "last_hidden_state") and features.last_hidden_state is not None:
            features = features.last_hidden_state
        features = F.normalize(features, p=2, dim=-1)


    return features[0].cpu().tolist()
