import json
import math
import re
import shutil
import sys
from datetime import datetime, timezone
from os import environ
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from goniocontrol_app.errors import PreconditionError
from goniocontrol_app.state import AngleRow, AppState

DATASET_FORMAT_VERSION = 1
DATASET_DESCRIPTION = (
    "This dataset was collected with the FGI laboratory goniometer. "
    "It contains reflectance factors or radiances measured at different combinations "
    "of sensor and illumination geometry. When polarizing optics are used, "
    "polarization settings may also vary."
)


def _spectrum_quantity_label(reflectance_mode: bool) -> str:
    return "reflectance_factor" if reflectance_mode else "radiance"


def _polarization_measurement_mode_label(npols: int) -> str:
    # Rule matches WorkflowService.connect_devices: npols > 1 implies polarized acquisition path.
    return "Yes" if npols > 1 else "No"


def _dataset_info_string_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _round_significant_float(x: float, ndigits: int = 5) -> float:
    if x == 0.0:
        return 0.0
    if not math.isfinite(x):
        return float(x)
    return float(
        round(x, ndigits - 1 - int(math.floor(math.log10(abs(x)))))
    )


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
        suf = path.suffix.lower()
        if suf in (".pickle", ".pkl"):
            path = path.with_suffix(".json")
        elif suf != ".json":
            path = path.with_suffix(".json")
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
            "angles_file": str(
                defaults.get(
                    "angles_file", "example_sequences/PrincipalPlane_5deg.seq.txt"
                )
            ),
            "reflectance_mode": bool(defaults.get("reflectance_mode", True)),
            "light_zenith_deg": float(defaults.get("light_zenith_deg", 0.0)),
            "light_azimuth_deg": float(defaults.get("light_azimuth_deg", 0.0)),
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

        angles_raw = data.get("angles_file")
        if isinstance(angles_raw, str) and angles_raw.strip():
            angles_path = Path(angles_raw.strip())
            if not angles_path.is_absolute():
                angles_path = (self.workspace / angles_path).resolve()
            settings["angles_file"] = str(angles_path)

        mode_raw = data.get("reflectance_mode")
        if isinstance(mode_raw, bool):
            settings["reflectance_mode"] = mode_raw

        zen_raw = data.get("light_zenith_deg")
        if isinstance(zen_raw, (int, float)):
            settings["light_zenith_deg"] = float(zen_raw)

        az_raw = data.get("light_azimuth_deg")
        if isinstance(az_raw, (int, float)):
            settings["light_azimuth_deg"] = float(az_raw)

        return settings

    def save_runtime_settings(
        self, angles_file, reflectance_mode, light_zenith_deg, light_azimuth_deg
    ):
        settings = {
            "angles_file": str((angles_file if angles_file.is_absolute() else self.workspace / angles_file).resolve()),
            "reflectance_mode": bool(reflectance_mode),
            "light_zenith_deg": float(light_zenith_deg),
            "light_azimuth_deg": float(light_azimuth_deg),
        }
        path = self._state_path("runtime_settings.json")
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def load_dataset_document(self, outfile) -> Optional[Dict[str, Any]]:
        path = self._resolve_outfile_path(outfile)
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Dataset file {} is not valid UTF-8 JSON.".format(path)
            ) from exc
        if not isinstance(doc, dict):
            raise ValueError("Dataset file {} must contain a JSON object.".format(path))
        return doc

    def measurements_from_document(self, doc: Dict[str, Any]) -> List[Any]:
        ver = doc.get("goniocontrol_dataset_format_version")
        if ver != DATASET_FORMAT_VERSION:
            raise ValueError(
                "Unsupported goniocontrol_dataset_format_version {!r} (expected {}).".format(
                    ver, DATASET_FORMAT_VERSION
                )
            )
        measurements = doc.get("measurements")
        if measurements is None:
            raise ValueError("Dataset document missing 'measurements' array.")
        if not isinstance(measurements, list):
            raise ValueError("Dataset 'measurements' must be an array.")
        if len(measurements) == 0:
            return []
        info = doc.get("dataset_info") or {}
        pol_mode = info.get("polarization_measurement_mode")
        if pol_mode not in ("Yes", "No"):
            raise ValueError(
                "dataset_info.polarization_measurement_mode must be 'Yes' or 'No'."
            )
        pol_yes = pol_mode == "Yes"
        return [self._measurement_record_to_tuple(rec, pol_yes) for rec in measurements]

    def apply_dataset_metadata_to_state(self, doc: Dict[str, Any], state: AppState) -> None:
        info_raw = doc.get("dataset_info")
        info = info_raw if isinstance(info_raw, dict) else {}
        state.authors = _dataset_info_string_field(info.get("authors"))
        state.target_name = _dataset_info_string_field(info.get("target_name"))
        state.target_description = _dataset_info_string_field(
            info.get("target_description")
        )

        measurements = doc.get("measurements") or []
        sq = info.get("spectrum_quantity")

        if measurements:
            if sq == "reflectance_factor":
                state.reflectance_mode = True
            elif sq == "radiance":
                state.reflectance_mode = False
            else:
                raise ValueError(
                    "dataset_info.spectrum_quantity must be 'reflectance_factor' or 'radiance'."
                )
            state.reflectance_mode_locked = True
            return

        if sq == "reflectance_factor":
            state.reflectance_mode = True
            state.reflectance_mode_locked = True
        elif sq == "radiance":
            state.reflectance_mode = False
            state.reflectance_mode_locked = True
        elif sq is None:
            state.reflectance_mode_locked = False
        else:
            raise ValueError(
                "dataset_info.spectrum_quantity must be 'reflectance_factor' or 'radiance'."
            )

    def load_existing_dataset(self, outfile):
        try:
            doc = self.load_dataset_document(outfile)
        except ValueError:
            raise
        if doc is None:
            return []
        return self.measurements_from_document(doc)

    def checkpoint_dataset(
        self,
        outfile,
        data,
        reflectance_mode: bool,
        npols: int,
        authors: str = "",
        target_name: str = "",
        target_description: str = "",
    ):
        if not (outfile or "").strip():
            raise PreconditionError(
                "No output dataset file selected. Choose a JSON dataset path before measuring."
            )
        path = self._resolve_outfile_path(outfile)
        expected_sq = _spectrum_quantity_label(reflectance_mode)
        expected_pol = _polarization_measurement_mode_label(npols)

        existing_doc = None
        if path.exists():
            try:
                existing_doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raise PreconditionError(
                    "Cannot append: dataset file {} exists but is not valid JSON.".format(
                        path
                    )
                )

        if existing_doc:
            info = existing_doc.get("dataset_info") or {}
            psq = info.get("spectrum_quantity")
            if psq is not None and psq != expected_sq:
                raise PreconditionError(
                    "Dataset file spectrum_quantity is {!r} but current mode is {!r}.".format(
                        psq, expected_sq
                    )
                )
            ppol = info.get("polarization_measurement_mode")
            if ppol is not None and ppol != expected_pol:
                raise PreconditionError(
                    "Dataset file polarization_measurement_mode is {!r} but current hardware mode is {!r}.".format(
                        ppol, expected_pol
                    )
                )

        measurements_json = [
            self._measurement_tuple_to_record(row, expected_pol == "Yes")
            for row in data
        ]

        merged_info: Dict[str, Any] = {}
        if existing_doc and isinstance(existing_doc.get("dataset_info"), dict):
            merged_info = dict(existing_doc["dataset_info"])
        merged_info.update(
            {
                "dataset_description": DATASET_DESCRIPTION,
                "spectrum_quantity": expected_sq,
                "polarization_measurement_mode": expected_pol,
                "dataset_last_updated_utc": datetime.now(timezone.utc).isoformat(),
                "authors": authors or "",
                "target_name": target_name or "",
                "target_description": target_description or "",
            }
        )

        doc = {
            "goniocontrol_dataset_format_version": DATASET_FORMAT_VERSION,
            "dataset_info": merged_info,
            "measurements": measurements_json,
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    def _spectrum_ndarray_to_json_nested(self, spec: Any) -> Any:
        arr = np.asarray(spec, dtype=float)
        if arr.ndim == 0:
            return _round_significant_float(float(arr), 5)
        return [self._spectrum_ndarray_to_json_nested(arr[idx]) for idx in range(arr.shape[0])]

    def _json_nested_to_spectrum_ndarray(self, obj: Any) -> np.ndarray:
        if isinstance(obj, list):
            rows = [self._json_nested_to_spectrum_ndarray(item) for item in obj]
            return np.array(rows, dtype=float)
        return np.asarray(float(obj), dtype=float)

    def _measurement_tuple_to_record(self, row: Tuple[Any, ...], polarization_yes: bool) -> Dict[str, Any]:
        sz, sa00, ze, az, be, spec, _wwa, _wwb, lz, la = row
        rec = {
            "sensor_zenith_angle_deg": float(ze),
            "sensor_azimuth_angle_deg": float(az),
            "sample_rotation_angle_deg": float(be),
            "light_zenith_angle_deg": float(lz),
            "light_azimuth_angle_deg": float(la),
            "spectrum": self._spectrum_ndarray_to_json_nested(spec),
        }
        if polarization_yes:
            rec["sensor_polarizer_angle_deg"] = float(sz)
            rec["lamp_polarizer_angle_deg"] = float(sa00)
        return rec

    def _measurement_record_to_tuple(self, rec: Dict[str, Any], polarization_yes: bool) -> Tuple[Any, ...]:
        required = (
            "sensor_zenith_angle_deg",
            "sensor_azimuth_angle_deg",
            "sample_rotation_angle_deg",
            "light_zenith_angle_deg",
            "light_azimuth_angle_deg",
            "spectrum",
        )
        for key in required:
            if key not in rec:
                raise ValueError("Measurement record missing {!r}.".format(key))

        if polarization_yes:
            if "sensor_polarizer_angle_deg" not in rec or "lamp_polarizer_angle_deg" not in rec:
                raise ValueError(
                    "Measurement record missing polarizer angles for polarization Measurement mode Yes."
                )
            sz = float(rec["sensor_polarizer_angle_deg"])
            sa00 = float(rec["lamp_polarizer_angle_deg"])
        else:
            sz = 0.0
            sa00 = 0.0

        ze = float(rec["sensor_zenith_angle_deg"])
        az = float(rec["sensor_azimuth_angle_deg"])
        be = float(rec["sample_rotation_angle_deg"])
        lz = float(rec["light_zenith_angle_deg"])
        la = float(rec["light_azimuth_angle_deg"])
        spec = self._json_nested_to_spectrum_ndarray(rec["spectrum"])
        return (sz, sa00, ze, az, be, spec, 0.0, 1.0, lz, la)

    def export_text(self, state):
        if not (state.outfile or "").strip():
            return
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

