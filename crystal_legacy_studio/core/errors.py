class StudioError(Exception):
    code = "CLS-000"

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}" + (f" — {self.detail}" if self.detail else "")


class ProjectError(StudioError):
    code = "PRJ-001"


class PackageBuildError(StudioError):
    code = "PKG-001"


class PackageVerificationError(StudioError):
    code = "PKG-002"
