from __future__ import annotations

import pickle
from pathlib import Path
from typing import List

import numpy as np

from goniocontrol_app.state import AngleRow, AppState


class PersistenceService:
    def __init__(self, workspace: Path):
        self.workspace = workspace

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
            return default
        return path.read_text(encoding="utf-8").strip() or default

    def save_outfile_name(self, outfile: str) -> None:
        (self.workspace / "outfile.txt").write_text(outfile, encoding="utf-8")
        np.save(self.workspace / "outfile.npy", outfile)

    def load_existing_dataset(self, outfile: str):
        pickle_path = self.workspace / f"{outfile}.pickle"
        if not pickle_path.exists():
            return []
        with pickle_path.open("rb") as handle:
            return pickle.load(handle)

    def checkpoint_dataset(self, outfile: str, data) -> None:
        with (self.workspace / f"{outfile}.pickle").open("wb") as handle:
            pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

    def export_text(self, state: AppState) -> None:
        outfile = state.outfile
        try:
            np.savetxt(self.workspace / f"{outfile}_.txt", np.ravel(state.data))
        except Exception:
            pass
        out = self.workspace / f"{outfile}.txt"
        with out.open("w", encoding="utf-8") as handle:
            for datum in state.data:
                handle.write(str(datum[:5]))
                handle.write(str(np.ravel(datum[5])) + "\n")

