"""LLM backend: Qwen3 8B via llama-cpp-python.

Loads on demand, unloads when idle — never sits on VRAM.
Respects the 8GB-minimum discipline: lean context, no waste.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO_ROOT / "models" / "Qwen3-8B-Q4_K_M.gguf"

# Lean by design: enough context for code gen + error feedback,
# not so much that we waste VRAM on dead tokens.
N_CTX = 8192
N_GPU_LAYERS = -1  # offload all to GPU if present; falls back to CPU


class QwenBackend:
    def __init__(self, model_path: Path | None = None, n_ctx: int = N_CTX):
        self.model_path = model_path or MODEL_PATH
        self.n_ctx = n_ctx
        self._llm = None

    def load(self) -> None:
        if self._llm is not None:
            return
        if not self.model_path.exists():
            raise FileNotFoundError(f"model not found: {self.model_path}")
        from llama_cpp import Llama
        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )

    def unload(self) -> None:
        # Drop the reference; Python GC frees the VRAM.
        self._llm = None
        import gc
        gc.collect()

    def generate(self, system: str, prompt: str, timeout_s: int = 180) -> str:
        if self._llm is None:
            raise RuntimeError("backend not loaded — call load() first")
        out = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,  # low temp: we want correct code, not creative code
            max_tokens=2048,
        )
        text = out["choices"][0]["message"]["content"] or ""
        return _strip_code_fences(text.strip())


def _strip_code_fences(text: str) -> str:
    """The model may wrap code in ```python fences — strip them."""
    if text.startswith("```"):
        lines = text.split("\n")
        # drop opening fence
        lines = lines[1:]
        # drop closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def make_generate_fn(backend: QwenBackend):
    """Build the generate_fn the Phase0Loop expects."""
    def generate_fn(prompt, system, prior_script, error_log, context):
        backend.load()
        user = f"Part to make: {prompt}\n\nReference data:\n{context}"
        if prior_script and error_log:
            user += (
                f"\n\nYour previous script:\n{prior_script}\n\n"
                f"It failed with:\n{error_log}\n\n"
                "Fix it. Output ONLY the corrected Python code."
            )
        try:
            return backend.generate(system, user)
        finally:
            # Unload after each generation — never sit on VRAM between steps.
            # (The loop's ModelLifecycle can hold it across attempts if preferred.)
            pass
    return generate_fn
