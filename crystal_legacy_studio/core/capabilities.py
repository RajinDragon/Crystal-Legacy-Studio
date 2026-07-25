from dataclasses import dataclass, field
from typing import Callable

@dataclass(frozen=True)
class Capability:
    name: str
    description: str

@dataclass
class StudioModule:
    module_id: str
    display_name: str
    category: str
    capabilities: set[str] = field(default_factory=set)
    activate: Callable[[], None] | None = None

class CapabilityRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, StudioModule] = {}

    def register(self, module: StudioModule) -> None:
        if module.module_id in self._modules:
            raise ValueError(f"Module already registered: {module.module_id}")
        self._modules[module.module_id] = module

    def get(self, module_id: str) -> StudioModule | None:
        return self._modules.get(module_id)

    def all(self) -> list[StudioModule]:
        return sorted(self._modules.values(), key=lambda m: (m.category, m.display_name))
