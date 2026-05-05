from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from goniocontrol_app.state import AngleRow, AppState


class PersistenceService:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def _resolve_outfile_path(self, outfile: str) -> Path:
        raw = (outfile or "").strip() or "Test00"
        path = Path(raw)
        if not path.is_absolute():
            path = self.workspace / path
        if path.suffix.lower() != ".pickle":
            path = path.with_suffix(".pickle")
        return path.resolve()

    def read_angles(self, angle_file: Path) -> List[AngleRow]:
        path = angle_file if angle_file.is_absolute() else self.workspace / angle_file
        rows: List[AngleRow] = []
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

    def load_optional_array(self, filename: str):
        path = self.workspace / filename
        if path.exists():
            return np.load(path, allow_pickle=True)
        return None

    def save_array(self, filename: str, data) -> None:
        np.save(self.workspace / filename, data)

    def load_outfile_name(self, default: str = "Test00") -> str:
        path = self.workspace / "outfile.txt"
        if not path.exists():
            return str(self._resolve_outfile_path(default))
        stored = path.read_text(encoding="utf-8").strip() or default
        return str(self._resolve_outfile_path(stored))

    def save_outfile_name(self, outfile: str) -> None:
        normalized = str(self._resolve_outfile_path(outfile))
        (self.workspace / "outfile.txt").write_text(normalized, encoding="utf-8")
        np.save(self.workspace / "outfile.npy", normalized)

    def load_runtime_settings(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        settings: Dict[str, Any] = {
            "outfile": str(self._resolve_outfile_path(str(defaults.get("outfile", "Test00")))),
            "angles_file": str(defaults.get("angles_file", "Angles.txt")),
            "reflectance_mode": bool(defaults.get("reflectance_mode", True)),
        }
        path = self.workspace / "runtime_settings.json"
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

    def save_runtime_settings(self, outfile: str, angles_file: Path, reflectance_mode: bool) -> None:
        settings = {
            "outfile": str(self._resolve_outfile_path(outfile)),
            "angles_file": str((angles_file if angles_file.is_absolute() else self.workspace / angles_file).resolve()),
            "reflectance_mode": bool(reflectance_mode),
        }
        path = self.workspace / "runtime_settings.json"
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def load_existing_dataset(self, outfile: str):
        pickle_path = self._resolve_outfile_path(outfile)
        if not pickle_path.exists():
            return []
        with pickle_path.open("rb") as handle:
            return pickle.load(handle)

    def checkpoint_dataset(self, outfile: str, data) -> None:
        pickle_path = self._resolve_outfile_path(outfile)
        pickle_path.parent.mkdir(parents=True, exist_ok=True)
        with pickle_path.open("wb") as handle:
            pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

    def export_text(self, state: AppState) -> None:
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

