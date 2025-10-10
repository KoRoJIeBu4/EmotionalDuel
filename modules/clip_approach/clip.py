import torch
from transformers import CLIPModel, CLIPProcessor
from PIL import Image
from functools import lru_cache
import os
from typing import List, Union

MODEL_NAME = "openai/clip-vit-base-patch32"
MODEL_CACHE_DIR = "./model_cache/clip"
IMAGES_PATH = "./data/images"


@lru_cache(maxsize=1)
def load_clip():
    """
    Загружает (и кэширует) CLIP модель и препроцессор.
    Сохраняет модель в локальный кэш.
    """
    if os.path.exists(MODEL_CACHE_DIR):
        model = CLIPModel.from_pretrained(MODEL_CACHE_DIR)
        processor = CLIPProcessor.from_pretrained(MODEL_CACHE_DIR)
    else:
        model = CLIPModel.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            use_safetensors=True
        )
        processor = CLIPProcessor.from_pretrained(MODEL_NAME)
        os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
        model.save_pretrained(MODEL_CACHE_DIR)
        processor.save_pretrained(MODEL_CACHE_DIR)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    return model, processor, device


def compute_image_scores(
    image_dir: str,
    text_prompt: str
):
    """
    Для всех изображений в директории images вычисляет
    скор относительно текстового описания text_prompt.
    Возвращает словарь {имя_файла: score}.
    """
    model, processor, device = load_clip()

    image_files = [
        os.path.join(image_dir, f)
        for f in os.listdir(image_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]

    if not image_files:
        raise ValueError(f"В директории '{image_dir}' нет изображений")

    images = []
    for file_path in image_files:
        try:
            img = Image.open(file_path).convert("RGB")
            images.append(img)
        except Exception as e:
            print(f"Ошибка при чтении {file_path}: {e}")

    if not images:
        raise ValueError("Не удалось загрузить ни одно изображение")

    inputs = processor(
        text=[text_prompt],
        images=images,
        return_tensors="pt",
        padding=True
    ).to(device)

    with torch.no_grad():
        outputs = model(**inputs)
        logits_per_image = outputs.logits_per_image
        scores = logits_per_image.squeeze(1).softmax(dim=0).tolist()

    return {os.path.basename(path): score for path, score in zip(image_files, scores)}


result = compute_image_scores(IMAGES_PATH, "a person smiling with closed eyes")

print(*result.items(), sep='\n')