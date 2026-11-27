"""Provider extension boundary shared by the host and fresh worker processes."""

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import entry_points

from .providers import Provider


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    key_env: str
    model_env: str
    factory: object  # Callable[[aiohttp.ClientSession], adapter with async run(...)]
    modes: tuple[str, ...] = ("vision", "code", "reed")


@lru_cache(maxsize=1)
def providers():
    specs = {
        p: ProviderSpec(p, label, key, model, lambda session, name=p: Provider(name, session))
        for p, label, key, model in (
            ("openai", "OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL"),
            ("gemini", "Gemini", "GEMINI_API_KEY", "GEMINI_MODEL"),
        )
    }
    # Extensions are trusted installed Python packages, never uploaded code.
    for entry in entry_points(group="reed_bench.providers"):
        spec = entry.load()
        if (
            not isinstance(spec, ProviderSpec)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", spec.name)
            or spec.name in specs
            or not spec.modes
            or any(m not in ("vision", "code", "reed") for m in spec.modes)
        ):
            raise ValueError("Invalid or duplicate installed benchmark provider adapter")
        specs[spec.name] = spec
    return specs


def provider_metadata(keys):
    return {
        p: {
            "label": s.label,
            "configured": bool(keys.get(p) or os.getenv(s.key_env)),
            "model": os.getenv(s.model_env, ""),
            "modes": list(s.modes),
        }
        for p, s in providers().items()
    }


def create_provider(name, session):
    return providers()[name].factory(session)
