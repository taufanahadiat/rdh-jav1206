import importlib.util
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.py"
SPEC = importlib.util.spec_from_file_location("shared_master_config", CONFIG_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load shared config module: {CONFIG_PATH}")

MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

for name in dir(MODULE):
    if name.startswith("__"):
        continue
    globals()[name] = getattr(MODULE, name)
