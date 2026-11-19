"""Identity consistency verification using DINOv2 (Apache-2.0).

Compares cropped target detection boxes to reference identity images (e.g. Maotai master ref)
via cosine similarity, producing minimum and average similarity metrics.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from qc.gpu import resolve_device

logger = logging.getLogger("qc.identity")


class DINOv2Extractor:
    """Feature extraction via DINOv2 (Apache-2.0 License)."""

    def __init__(self, model_name: str = "facebook/dinov2-small", device: Optional[str] = None):
        self.device = device or resolve_device()
        self.model_name = model_name
        self.model = None
        self.transform = None
        self._load_model()

    def _load_model(self):
        try:
            import torch
            from torchvision import transforms
            from transformers import AutoModel

            logger.info(f"Loading DINOv2 model ({self.model_name}) on device: {self.device}...")
            self.model = AutoModel.from_pretrained(self.model_name, local_files_only=True).to(self.device)
            self.model.eval()

            self.transform = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
            logger.info("DINOv2 loaded successfully.")
        except Exception as exc:
            logger.warning(f"DINOv2 unavailable ({exc}). Using permissive CV histogram/gradient embeddings.")
            self.model = None

    def extract_embedding(self, img_bgr: np.ndarray) -> np.ndarray:
        """Extract L2-normalized embedding vector."""
        if img_bgr is None or img_bgr.size == 0:
            return np.zeros(384, dtype=np.float32)

        if self.model is not None and self.transform is not None:
            try:
                import torch
                rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                tensor = self.transform(rgb).unsqueeze(0).to(self.device)
                with torch.no_grad():
                    outputs = self.model(tensor)
                    # Use pooler output or CLS token
                    if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
                        emb = outputs.pooler_output.squeeze().cpu().numpy()
                    else:
                        emb = outputs.last_hidden_state[:, 0, :].squeeze().cpu().numpy()
                norm = np.linalg.norm(emb)
                return emb / (norm + 1e-7)
            except Exception as exc:
                logger.warning(f"DINOv2 extraction failed: {exc}")

        # Fallback embedding: combined normalized color histogram + Hu moments + edge features
        return compute_fallback_embedding(img_bgr)


def compute_fallback_embedding(img_bgr: np.ndarray) -> np.ndarray:
    """Permissive lightweight feature vector for offline consistency verification."""
    resized = cv2.resize(img_bgr, (128, 128))
    # HSV histogram
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [32], [0, 180]).flatten()
    hist_s = cv2.calcHist([hsv], [1], None, [32], [0, 256]).flatten()
    hist_v = cv2.calcHist([hsv], [2], None, [32], [0, 256]).flatten()

    # Spatial grayscale gradient blocks
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    blocks = [gray[i*32:(i+1)*32, j*32:(j+1)*32].mean() for i in range(4) for j in range(4)]

    vector = np.concatenate([hist_h, hist_s, hist_v, np.array(blocks, dtype=np.float32)])
    norm = np.linalg.norm(vector)
    return vector / (norm + 1e-7)


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Compute cosine similarity between two feature vectors."""
    dot = np.dot(v1, v2)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-7 or n2 < 1e-7:
        return 0.0
    return float(np.clip(dot / (n1 * n2), -1.0, 1.0))


def evaluate_identity_consistency(
    crops: List[np.ndarray],
    ref_image_path: str | Path,
    extractor: Optional[DINOv2Extractor] = None,
    min_similarity_threshold: float = 0.65,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Compare cropped detected entities to a reference image."""
    fails: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "ref_image": str(ref_image_path),
        "crops_evaluated": len(crops),
        "min_similarity": None,
        "avg_similarity": None,
    }

    ref_p = Path(ref_image_path)
    if not ref_p.is_file():
        warnings.append({
            "check": "identity_ref_missing",
            "frame": None,
            "detail": f"Reference image file not found: {ref_image_path}",
        })
        return fails, warnings, metrics

    ref_bgr = cv2.imdecode(np.fromfile(ref_p, dtype=np.uint8), cv2.IMREAD_COLOR)
    if ref_bgr is None:
        warnings.append({
            "check": "identity_ref_corrupt",
            "frame": None,
            "detail": f"Failed to decode reference image: {ref_image_path}",
        })
        return fails, warnings, metrics

    if not crops:
        warnings.append({
            "check": "identity_no_crops",
            "frame": None,
            "detail": "No detected target entity crops available to evaluate identity.",
        })
        return fails, warnings, metrics

    if extractor is None:
        extractor = DINOv2Extractor()

    ref_emb = extractor.extract_embedding(ref_bgr)
    sims: List[float] = []

    for crop in crops:
        if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            continue
        c_emb = extractor.extract_embedding(crop)
        sim = cosine_similarity(ref_emb, c_emb)
        sims.append(sim)

    if not sims:
        return fails, warnings, metrics

    min_sim = float(np.min(sims))
    avg_sim = float(np.mean(sims))

    metrics["min_similarity"] = round(min_sim, 3)
    metrics["avg_similarity"] = round(avg_sim, 3)
    metrics["all_similarities"] = [round(s, 3) for s in sims]

    if min_sim < min_similarity_threshold:
        fails.append({
            "check": "identity_drift",
            "frame": None,
            "detail": (
                f"Identity cosine similarity dropped to {min_sim:.3f} "
                f"(threshold {min_similarity_threshold:.2f}, avg {avg_sim:.3f}). "
                "Entity appearance diverges from master reference."
            ),
        })

    return fails, warnings, metrics
