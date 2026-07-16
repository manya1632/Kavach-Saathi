from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import Any

from kavach_saathi.config import Settings

logger = logging.getLogger("kavach_saathi.model_registry")

# Process-wide caches
_clip_model = None
_clip_processor = None
_bert_tokenizer = None
_bert_model = None
_resnet50_weights = None
_resnet50_model = None
_sam2_model = None
_sam2_processor = None
_sentence_transformer = None
_sd_pipeline = None

_gemini_client = None
_groq_client = None

# Locks for per-model lazy loading
_clip_lock = threading.Lock()
_bert_lock = threading.Lock()
_resnet_lock = threading.Lock()
_sam2_lock = threading.Lock()
_sentence_transformer_lock = threading.Lock()
_sd_lock = threading.Lock()
_gemini_lock = threading.Lock()
_groq_lock = threading.Lock()

# Warmup state
_warmed_up = False


def get_clip(settings: Settings) -> tuple[Any, Any]:
    global _clip_model, _clip_processor
    if _clip_model is not None and _clip_processor is not None:
        return _clip_model, _clip_processor

    with _clip_lock:
        if _clip_model is not None and _clip_processor is not None:
            return _clip_model, _clip_processor

        t0 = time.perf_counter()
        logger.info("Loading CLIP model 'openai/clip-vit-base-patch32'...")
        from transformers import CLIPModel, CLIPProcessor

        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        logger.info(f"Loaded CLIP in {time.perf_counter() - t0:.2f}s")
        return _clip_model, _clip_processor


def get_bert() -> tuple[Any, Any]:
    global _bert_tokenizer, _bert_model
    if _bert_tokenizer is not None and _bert_model is not None:
        return _bert_tokenizer, _bert_model

    with _bert_lock:
        if _bert_tokenizer is not None and _bert_model is not None:
            return _bert_tokenizer, _bert_model

        t0 = time.perf_counter()
        logger.info("Loading BERT model 'bert-base-uncased'...")
        from transformers import AutoModel, AutoTokenizer

        _bert_tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
        _bert_model = AutoModel.from_pretrained("bert-base-uncased")
        logger.info(f"Loaded BERT in {time.perf_counter() - t0:.2f}s")
        return _bert_tokenizer, _bert_model


def get_resnet() -> tuple[Any, Any]:
    global _resnet50_weights, _resnet50_model
    if _resnet50_weights is not None and _resnet50_model is not None:
        return _resnet50_weights, _resnet50_model

    with _resnet_lock:
        if _resnet50_weights is not None and _resnet50_model is not None:
            return _resnet50_weights, _resnet50_model

        t0 = time.perf_counter()
        logger.info("Loading ResNet-50 model...")
        from torchvision.models import ResNet50_Weights, resnet50

        _resnet50_weights = ResNet50_Weights.IMAGENET1K_V2
        _resnet50_model = resnet50(weights=_resnet50_weights)
        _resnet50_model.eval()
        logger.info(f"Loaded ResNet-50 in {time.perf_counter() - t0:.2f}s")
        return _resnet50_weights, _resnet50_model


_SAM2_CHECKPOINT = "facebook/sam2.1-hiera-tiny"


def get_sam2() -> tuple[Any, Any]:
    global _sam2_model, _sam2_processor
    if _sam2_model is not None and _sam2_processor is not None:
        return _sam2_model, _sam2_processor

    with _sam2_lock:
        if _sam2_model is not None and _sam2_processor is not None:
            return _sam2_model, _sam2_processor

        t0 = time.perf_counter()
        logger.info(f"Loading SAM2 model '{_SAM2_CHECKPOINT}'...")
        # `transformers`' own Sam2Model/Sam2Processor -- the standalone `sam2` package
        # isn't a project dependency. Once cached, `from_pretrained`'s default online
        # ETag check against the Hub can itself take minutes even though no download is
        # needed (observed live) -- try cache-only first, fall back to network only if
        # the cache is genuinely missing.
        from transformers import Sam2Model, Sam2Processor

        try:
            model = Sam2Model.from_pretrained(
                _SAM2_CHECKPOINT, device_map=None, low_cpu_mem_usage=False, local_files_only=True
            )
            processor = Sam2Processor.from_pretrained(_SAM2_CHECKPOINT, local_files_only=True)
        except OSError:
            model = Sam2Model.from_pretrained(_SAM2_CHECKPOINT, device_map=None, low_cpu_mem_usage=False)
            processor = Sam2Processor.from_pretrained(_SAM2_CHECKPOINT)
        model.to("cpu")
        model.eval()
        _sam2_model = model
        _sam2_processor = processor
        logger.info(f"Loaded SAM2 in {time.perf_counter() - t0:.2f}s")
        return _sam2_model, _sam2_processor


def get_sentence_transformer(settings: Settings) -> Any:
    global _sentence_transformer
    if _sentence_transformer is not None:
        return _sentence_transformer

    with _sentence_transformer_lock:
        if _sentence_transformer is not None:
            return _sentence_transformer

        t0 = time.perf_counter()
        logger.info(f"Loading SentenceTransformer '{settings.embedding_model}'...")
        from sentence_transformers import SentenceTransformer

        _sentence_transformer = SentenceTransformer(settings.embedding_model)
        logger.info(f"Loaded SentenceTransformer in {time.perf_counter() - t0:.2f}s")
        return _sentence_transformer


def get_stable_diffusion() -> Any:
    global _sd_pipeline
    if _sd_pipeline is not None:
        return _sd_pipeline

    with _sd_lock:
        if _sd_pipeline is not None:
            return _sd_pipeline

        t0 = time.perf_counter()
        logger.info("Loading Stable Diffusion + ControlNet pipeline...")
        import torch
        from diffusers import ControlNetModel, StableDiffusionControlNetPipeline

        sd_checkpoint = "runwayml/stable-diffusion-v1-5"
        controlnet_checkpoint = "lllyasviel/sd-controlnet-canny"
        # Once these checkpoints are cached, `from_pretrained`'s default online ETag
        # check against the Hub can itself take minutes (observed live) even though no
        # actual download is needed -- try cache-only first, fall back to network only
        # if the cache is genuinely missing.
        try:
            controlnet = ControlNetModel.from_pretrained(
                controlnet_checkpoint, torch_dtype=torch.float32, local_files_only=True
            )
            pipeline = StableDiffusionControlNetPipeline.from_pretrained(
                sd_checkpoint,
                controlnet=controlnet,
                torch_dtype=torch.float32,
                safety_checker=None,
                local_files_only=True,
            )
        except OSError:
            controlnet = ControlNetModel.from_pretrained(controlnet_checkpoint, torch_dtype=torch.float32)
            pipeline = StableDiffusionControlNetPipeline.from_pretrained(
                sd_checkpoint, controlnet=controlnet, torch_dtype=torch.float32, safety_checker=None
            )
        pipeline.set_progress_bar_config(disable=True)
        _sd_pipeline = pipeline
        logger.info(f"Loaded Stable Diffusion in {time.perf_counter() - t0:.2f}s")
        return _sd_pipeline


def get_gemini_client(settings: Settings) -> Any:
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    with _gemini_lock:
        if _gemini_client is not None:
            return _gemini_client
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        from google import genai

        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
        return _gemini_client


def get_groq_client(settings: Settings) -> Any:
    global _groq_client
    if _groq_client is not None:
        return _groq_client

    with _groq_lock:
        if _groq_client is not None:
            return _groq_client
        from groq import AsyncGroq

        _groq_client = AsyncGroq(
            api_key=settings.groq_api_key,
            timeout=settings.provider_timeout_seconds,
            max_retries=0,
        )
        return _groq_client


def warm_up_models(settings: Settings) -> None:
    """Pre-loads heavyweight models required for the hackathon path if warm-up is enabled."""
    global _warmed_up
    if _warmed_up:
        return
    _warmed_up = True

    logger.info("Starting model warm-up...")
    try:
        get_clip(settings)
    except Exception as e:
        logger.error(f"Warmup failed for CLIP: {e}")

    try:
        get_resnet()
    except Exception as e:
        logger.error(f"Warmup failed for ResNet: {e}")

    try:
        get_sentence_transformer(settings)
    except Exception as e:
        logger.error(f"Warmup failed for SentenceTransformer: {e}")
    logger.info("Model warm-up completed.")


@contextlib.contextmanager
def log_timing(category: str, detail: str = ""):
    t0 = time.perf_counter()
    yield
    elapsed = time.perf_counter() - t0
    logger.info(f"TIMING: Category={category} | Detail={detail} | Elapsed={elapsed:.4f}s")
