"""In-game overlay integration (EDMCModernOverlay / legacy edmcoverlay API)."""

__all__ = ["BuildProjectOverlay"]


def __getattr__(name: str):
    if name == "BuildProjectOverlay":
        from .build_project import BuildProjectOverlay

        return BuildProjectOverlay
    raise AttributeError(name)
