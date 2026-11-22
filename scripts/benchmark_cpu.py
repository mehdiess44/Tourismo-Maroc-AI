"""Measure the quantized encoder on a local image or a synthetic input."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import onnxruntime
from PIL import Image, ImageOps
import psutil

from tourismo.store import ARTIFACTS
from tourismo.vision import preprocess


def benchmark(path):
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    start = perf_counter()
    session = onnxruntime.InferenceSession(str(ARTIFACTS / "vision.onnx"), sess_options=options,
                                           providers=["CPUExecutionProvider"])
    load = perf_counter() - start
    if path:
        with Image.open(path) as raw:
            picture = ImageOps.exif_transpose(raw).convert("RGB")
    else:
        picture = Image.new("RGB", (640, 480), "gray")
    start = perf_counter()
    pixels = preprocess(picture, {"size":224, "mean":[.48145466,.4578275,.40821073],
                                 "std":[.26862954,.26130258,.27577711]})
    embedding = session.run(["image_embeds"], {session.get_inputs()[0].name:pixels})[0]
    elapsed = perf_counter() - start
    memory = psutil.Process().memory_info()
    return {"input":path.name if path else "synthetic", "load_seconds":round(load, 3),
            "first_inference_seconds":round(elapsed, 3), "shape":list(embedding.shape),
            "peak_working_set_mib":round(memory.peak_wset / 1048576, 1) if hasattr(memory, "peak_wset") else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    print(json.dumps(benchmark(parser.parse_args().image), indent=2))
