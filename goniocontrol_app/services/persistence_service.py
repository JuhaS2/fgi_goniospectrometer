import json
import pickle
import re
import shutil
import sys
from datetime import datetime
from os import environ
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from goniocontrol_app.state import AngleRow, AppState


class PersistenceService:
    _SEQ_VERSION_RE = re.compile(r"^#\s*seq_format_version\s*:\s*(.+?)\s*$", re.IGNORECASE)
    _SEQ_V1_COLUMNS = [
        "SensorZen",
        "SensorAz",
        "TargetRotation",
        "SensorPolarizerAngle",
        "LampPolarizerAngle",
    ]

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
        rows: List[Tuple[float, float, float, float, float, float, float]] = []
        content_rows: List[Tuple[int, str]] = []
        version = None
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    match = self._SEQ_VERSION_RE.match(stripped)
                    if match is not None:
                        version = match.group(1).strip().lower()
                    continue
                content_rows.append((line_number, stripped))

        if not version:
            raise ValueError(
                "Angles file missing required version comment. Add '# seq_format_version: 1' "
                "for new format or '# seq_format_version: legacy-v0' for legacy format."
            )

        if version == "1":
            if not content_rows:
                return rows
            header_line_no, header_row = content_rows[0]
            header_cols = [part.strip() for part in header_row.split("\t")]
            if header_cols != self._SEQ_V1_COLUMNS:
                raise ValueError(
                    "Invalid v1 sequence header on line {}. Expected tab-separated columns: {}".format(
                        header_line_no, ", ".join(self._SEQ_V1_COLUMNS)
                    )
                )

            for line_no, data_row in content_rows[1:]:
                parts = [part.strip() for part in data_row.split("\t")]
                if len(parts) != 5:
                    raise ValueError(
                        "Invalid v1 sequence row on line {}: expected 5 tab-separated values.".format(
                            line_no
                        )
                    )
                try:
                    sensor_zen, sensor_az, target_rotation, sensor_pol, lamp_pol = [
                        float(x) for x in parts
                    ]
                except ValueError as exc:
                    raise ValueError(
                        "Invalid numeric value on line {} in v1 sequence file.".format(line_no)
                    ) from exc

                rows.append(
                    (
                        sensor_pol,  # sz
                        lamp_pol,  # sa00
                        sensor_zen,  # ze
                        sensor_az,  # az
                        target_rotation,  # be
                        0.0,  # wwa
                        1.0,  # wwb
                    )
                )
            return rows

        if version in ("legacy-v0", "legacy_v0"):
            for line_no, row in content_rows:
                if row.startswith("S"):
                    break
                parts = row.split()
                if len(parts) != 7:
                    raise ValueError(
                        "Invalid legacy sequence row on line {}: expected 7 values.".format(
                            line_no
                        )
                    )
                try:
                    vals = [float(x) for x in parts]
                except ValueError as exc:
                    raise ValueError(
                        "Invalid numeric value on line {} in legacy sequence file.".format(
                            line_no
                        )
                    ) from exc
                rows.append(tuple(vals))  # type: ignore[arg-type]
            return rows

        raise ValueError(
            "Unsupported sequence format version '{}'. Supported values: 1, legacy-v0.".format(
                version
            )
        )
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

    def load_calibration_timestamps(self):
        defaults = {"dark_collected_at": None, "white_collected_at": None}
        path = self._state_path("calibration_timestamps.json")
        if not path.exists():
            return defaults
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return defaults
        if not isinstance(data, dict):
            return defaults

        out = dict(defaults)
        for key in out:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                out[key] = datetime.fromisoformat(raw)
            except ValueError:
                continue
        return out

    def save_calibration_timestamps(self, dark_collected_at, white_collected_at):
        payload = {
            "dark_collected_at": (
                dark_collected_at.isoformat() if dark_collected_at is not None else None
            ),
            "white_collected_at": (
                white_collected_at.isoformat()
                if white_collected_at is not None
                else None
            ),
        }
        self._state_path("calibration_timestamps.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

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
            "angles_file": str(
                defaults.get(
                    "angles_file", "example_sequences/PrincipalPlane_5deg.seq.txt"
                )
            ),
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

