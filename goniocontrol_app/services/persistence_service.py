import json
import pickle
import shutil
import sys
from os import environ
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from goniocontrol_app.state import AngleRow, AppState


class PersistenceService:
    def __init__(self, workspace, state_dir=None):
        self.workspace = Path(workspace).resolve()
        self.state_dir = self._resolve_state_dir(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_state_dir(self, explicit_state_dir):
        if explicit_state_dir:
            return Path(explicit_state_dir).expanduser().resolve()

        override = environ.get("GONIO_STATE_DIR", "").strip()
        if override:
            return Path(override).expanduser().resolve()

        if sys.platform.startswith("win"):
            base = environ.get("LOCALAPPDATA", "").strip()
            if base:
                candidate = Path(base) / "goniocontrol"
            else:
                candidate = Path.home() / "AppData" / "Local" / "goniocontrol"
        else:
            xdg_state = environ.get("XDG_STATE_HOME", "").strip()
            if xdg_state:
                candidate = Path(xdg_state) / "goniocontrol"
            else:
                candidate = Path.home() / ".local" / "state" / "goniocontrol"

        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate.resolve()
        except Exception:
            fallback = (self.workspace / ".goniocontrol_state").resolve()
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _state_path(self, filename):
        return self.state_dir / filename

    def _legacy_path(self, filename):
        return self.workspace / filename

    def _migrate_if_needed(self, src, dst):
        if dst.exists() or not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass

    def _resolve_outfile_path(self, outfile):
        raw = (outfile or "").strip() or "Test00"
        path = Path(raw)
        if not path.is_absolute():
            path = self.workspace / path
        if path.suffix.lower() != ".pickle":
            path = path.with_suffix(".pickle")
        return path.resolve()

    def read_angles(self, angle_file):
        path = angle_file if angle_file.is_absolute() else self.workspace / angle_file
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("S"):
                    break
                vals = [float(x) for x in stripped.split()]
                if len(vals) != 7:
                    continue
                rows.append(tuple(vals))  # type: ignore[arg-type]
        return rows

    def load_optional_array(self, filename):
        path = self._state_path(filename)
        legacy = self._legacy_path(filename)
        if not path.exists() and legacy.exists():
            self._migrate_if_needed(legacy, path)
        if path.exists():
            try:
                return np.load(path, allow_pickle=True)
            except ModuleNotFoundError as exc:
                # Legacy pickled object arrays can reference old/broken NumPy module paths.
                if not self._install_numpy_compat_aliases(exc):
                    raise
                return np.load(path, allow_pickle=True)
        return None

    @staticmethod
    def _install_numpy_compat_aliases(exc):
        missing = str(exc)
        if "numpy_.core" not in missing and "numpy._core" not in missing:
            return False
        # Map legacy or typo module names to current NumPy modules for unpickling.
        sys.modules.setdefault("numpy_", np)
        sys.modules.setdefault("numpy_.core", np.core)
        sys.modules.setdefault("numpy._core", np.core)
        return True

    def save_array(self, filename, data):
        np.save(self._state_path(filename), data)

    def load_outfile_name(self, default= "Test00"):
        path = self._state_path("outfile.txt")
        legacy = self._legacy_path("outfile.txt")
        if not path.exists() and legacy.exists():
            self._migrate_if_needed(legacy, path)
        if not path.exists():
            return str(self._resolve_outfile_path(default))
        stored = path.read_text(encoding="utf-8").strip() or default
        return str(self._resolve_outfile_path(stored))

    def save_outfile_name(self, outfile):
        normalized = str(self._resolve_outfile_path(outfile))
        self._state_path("outfile.txt").write_text(normalized, encoding="utf-8")
        np.save(self._state_path("outfile.npy"), normalized)

    def load_runtime_settings(self, defaults):
        settings = {
            "outfile": str(self._resolve_outfile_path(str(defaults.get("outfile", "Test00")))),
            "angles_file": str(defaults.get("angles_file", "Angles.txt")),
            "reflectance_mode": bool(defaults.get("reflectance_mode", True)),
        }
        path = self._state_path("runtime_settings.json")
        legacy = self._legacy_path("runtime_settings.json")
        if not path.exists() and legacy.exists():
            self._migrate_if_needed(legacy, path)
        if not path.exists():
            return settings
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return settings
        if not isinstance(data, dict):
            return settings

        outfile_raw = data.get("outfile")
        if isinstance(outfile_raw, str) and outfile_raw.strip():
            settings["outfile"] = str(self._resolve_outfile_path(outfile_raw))

        angles_raw = data.get("angles_file")
        if isinstance(angles_raw, str) and angles_raw.strip():
            angles_path = Path(angles_raw.strip())
            if not angles_path.is_absolute():
                angles_path = (self.workspace / angles_path).resolve()
            settings["angles_file"] = str(angles_path)

        mode_raw = data.get("reflectance_mode")
        if isinstance(mode_raw, bool):
            settings["reflectance_mode"] = mode_raw

        return settings

    def save_runtime_settings(self, outfile, angles_file, reflectance_mode):
        settings = {
            "outfile": str(self._resolve_outfile_path(outfile)),
            "angles_file": str((angles_file if angles_file.is_absolute() else self.workspace / angles_file).resolve()),
            "reflectance_mode": bool(reflectance_mode),
        }
        path = self._state_path("runtime_settings.json")
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def load_existing_dataset(self, outfile):
        pickle_path = self._resolve_outfile_path(outfile)
        if not pickle_path.exists():
            return []
        with pickle_path.open("rb") as handle:
            return pickle.load(handle)

    def checkpoint_dataset(self, outfile, data):
        pickle_path = self._resolve_outfile_path(outfile)
        pickle_path.parent.mkdir(parents=True, exist_ok=True)
        with pickle_path.open("wb") as handle:
            pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

    def export_text(self, state):
        outfile = self._resolve_outfile_path(state.outfile)
        try:
            np.savetxt(outfile.with_name("{}_.txt".format(outfile.stem)), np.ravel(state.data))
        except Exception:
            pass
        out = outfile.with_suffix(".txt")
        with out.open("w", encoding="utf-8") as handle:
            for datum in state.data:
                handle.write(str(datum[:5]))
                handle.write(str(np.ravel(datum[5])) + "\n")

