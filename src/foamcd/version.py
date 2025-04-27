import os
import importlib.metadata
from pathlib import Path

def get_version() -> str:
    """Get the package version from pyproject.toml or package metadata"""
    try:
        # First, try to get the version from package metadata
        return importlib.metadata.version("foamCD")
    except importlib.metadata.PackageNotFoundError:
        # If the package is not installed, read the version from pyproject.toml
        try:
            # Look for pyproject.toml in project root (typically 3 levels up from src/foamcd/version.py)
            current_file = Path(__file__)
            project_root = current_file.parents[2]  # src/foamcd/version.py -> src/ -> project root
            pyproject_path = project_root / "pyproject.toml"
            
            if pyproject_path.exists():
                try:
                    import tomli
                    with open(pyproject_path, "rb") as f:
                        data = tomli.load(f)
                        return data.get("version", "0.0.0")
                except ImportError:
                    # Fallback if tomli is not available
                    with open(pyproject_path, "r") as f:
                        for line in f:
                            if line.strip().startswith("version = "):
                                return line.split("=")[1].strip().strip('"\'')
            
            return "0.0.0"
        except Exception as e:
            return "0.0.0"
