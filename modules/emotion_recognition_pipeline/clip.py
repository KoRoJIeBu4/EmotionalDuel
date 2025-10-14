import torch
import open_clip
import glob
import os
from PIL import Image
import numpy as np
import torchvision.transforms as T
from huggingface_hub import hf_hub_download
from pathlib import Path



class EDModel:
    def __init__(self, device, weights_dir="data/weights"):
        self.device = device

        self.weights_dir = Path(weights_dir)
        self.weights_dir.mkdir(parents=True, exist_ok=True)
        self.weights_path = self.weights_dir / "edmodel.pth"

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-H-14',
            pretrained=None,
            device=device,
        )
        self.model = model
        self.preprocess = preprocess
        self.tokenizer = open_clip.get_tokenizer('ViT-H-14')

        if not self.weights_path.exists():
            print(f"[INFO] Downloading weights to {self.weights_path}...")
            self.weights_path = hf_hub_download(
                repo_id="KoRoJIeBu4/my-emotion-model",
                filename="edmodel.pth",
                cache_dir=str(self.weights_dir)
            )
        else:
            print(f"[INFO] Using existing weights at {self.weights_path}")

        state_dict = torch.load(self.weights_path, map_location=device)
        self.model.load_state_dict(state_dict)
        self.model.eval()

        print(f"[INFO] Model initialized on {self.device}")
        print(f"[INFO] Weights loaded from: {self.weights_path}")

    
    def play_duel(self, task: str, images: list[Image.Image]) -> list[tuple[Image.Image, float]]:
        '''
        Принимает задание, набор картинок - возвращает кортежы, где 
        каждый кортеж - это картинка и скор
        ! Порядок возврата картинок тот же, что и прием
        '''
        TEMPLATES = [
            "a photo of a person showing {emotion}",
            "a person expressing {emotion}",
            "a person with a {emotion}",
            "an image of a person having {emotion}",
            "a photo showing {emotion}",
            "on the picture: {emotion}",
        ]
        promt = [tplt.format(emotion=task) for tplt in TEMPLATES]
        sims = []

        with torch.no_grad():
            preprocessed_text = self.tokenizer(promt).to(self.device)
            text_features = self.model.encode_text(preprocessed_text)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            preprocessed_text = self.tokenizer(promt).to(self.device)
            text_features = self.model.encode_text(preprocessed_text)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            images_tensor = torch.stack([self.preprocess(img) for img in images]).to(self.device)
            image_features = self.model.encode_image(images_tensor)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            sims = (image_features @ text_features.T).mean(dim=1).tolist()

            return list(zip(images, sims))



def initialize_model():
    """
    Загружает модель CLIP с заданными весами.
    Returns:
        EDModel — инициализированная модель
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    edmodel = EDModel(device)

    return edmodel