from functools import lru_cache
from io import BytesIO
from threading import Lock

from PIL import Image, ImageOps

from tourismo.store import ARTIFACTS, read_json

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 16_000_000
inference_lock = Lock()


def decode(content):
    if len(content) > MAX_BYTES:
        raise ValueError("La photo dépasse 5 Mio.")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > MAX_PIXELS:
                raise ValueError("Utilisez une photo JPEG, PNG ou WebP de 16 mégapixels maximum.")
            return ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError("Impossible de lire cette photo.") from error


@lru_cache(maxsize=1)
def load_model():
    config = read_json(ARTIFACTS / "vision.json", {})
    if not config:
        return None
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = onnxruntime.InferenceSession(
        str(ARTIFACTS / "vision.onnx"), sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return config, session


def preprocess(image, config):
    import numpy as np

    shape = (config["size"], config["size"])
    pixels = np.asarray(ImageOps.fit(image, shape, method=Image.Resampling.BICUBIC), dtype="float32") / 255
    values = (pixels - np.asarray(config["mean"], dtype="float32")) / np.asarray(config["std"], dtype="float32")
    return values.transpose(2, 0, 1)[None]


def scores(image, config, session):
    import numpy as np

    output = session.run(None, {session.get_inputs()[0].name: preprocess(image, config)})[0].ravel()
    if config["method"] == "clip":
        vector = output / max(np.linalg.norm(output), 1e-12)
        return np.asarray(config["gallery"], dtype="float32") @ vector
    return output


def rank(values, config, kind, eligible, threshold=None):
    best = {}
    for identifier, value in zip(config["labels"], values, strict=True):
        if identifier in eligible:
            best[identifier] = max(best.get(identifier, float("-inf")), float(value))
    ordered = sorted(best.items(), key=lambda pair: (-pair[1], pair[0]))
    threshold = config["thresholds"].get(kind) if threshold is None else threshold
    state = "candidate" if ordered and threshold is not None and ordered[0][1] >= threshold else "uncertain"
    return {"status": state, "candidates": [{"id": key, "score": val} for key, val in ordered[:3]]}


def recognize(image, kind, eligible):
    with inference_lock:
        model = load_model()
        if model is None:
            return {"status": "unavailable", "candidates": []}
        config, session = model
        return rank(scores(image, config, session), config, kind, eligible)
