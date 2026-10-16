
from functools import lru_cache

import torch
from transformers import CLIPModel, CLIPProcessor

MODEL_NAME = "openai/clip-vit-base-patch32"


@lru_cache(maxsize=1)
def get_clip_components():
    """Load CLIP once and reuse it."""

    device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    model = CLIPModel.from_pretrained(MODEL_NAME)

    model.to(device)
    model.eval()
    model.requires_grad_(False)

    return processor, model, device
