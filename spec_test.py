import argparse
import socket
import sys
import time
from typing import Optional, Tuple

import numpy as np

from ASDlib import Optimize, ReadASD, ReadASD1, VNIRinfo


class DebugSocket:
    """Thin socket proxy that prints all traffic for ASD debugging."""

    def __init__(self, sock: socket.socket, max_print_bytes: int = 64):
        self._sock = sock
        self._max_print_bytes = max_print_bytes

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def sendall(self, data: bytes, *args, **kwargs):
        self._print_payload("sendall", data)
        return self._sock.sendall(data, *args, **kwargs)

    def recv(self, bufsize: int, *args, **kwargs) -> bytes:
        data = self._sock.recv(bufsize, *args, **kwargs)
        self._print_payload("recv", data, extra="bufsize={}".format(bufsize))
        return data

    def _print_payload(self, direction: str, data: bytes, extra: str = ""):
        if data is None:
            print("DEBUG_SOCKET {} data=None {}".format(direction, extra))
            return
        shown = data[: self._max_print_bytes]
        text_preview = shown.decode("ascii", errors="replace")
        print(
            "DEBUG_SOCKET {} len={} {} bytes={!r} text={!r}".format(
                direction,
                len(data),
                extra,
                shown,
                text_preview,
            )
        )


def connect_debug_socket(host: str, port: int, timeout_s: float) -> DebugSocket:
    print("Connecting to spectrometer host={} port={}".format(host, port))
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    raw.settimeout(timeout_s)
    t0 = time.time()
    raw.connect((host, port))
    print("Connected in {:.3f}s".format(time.time() - t0))
    s = DebugSocket(raw)
    greeting = s.recv(128)
    print("Greeting len={} bytes={!r}".format(len(greeting), greeting))
    return s


def try_optimize(s: DebugSocket, retries: int) -> Tuple[Optional[tuple], Optional[Exception]]:
    last_exc = None
    for attempt in range(1, retries + 1):
        print("\n=== Optimize attempt {}/{} ===".format(attempt, retries))
        try:
            result = Optimize(s)
            print("Optimize result: {}".format(result))
            return result, None
        except Exception as exc:
            last_exc = exc
            print("Optimize FAILED on attempt {}: {}: {}".format(attempt, type(exc).__name__, exc))
    return None, last_exc


def acquire_single_spectrum(s: DebugSocket):
    print("\n=== Acquire single spectrum (A,1,1) ===")
    try:
        header, spectrum = ReadASD1(s, 1)
        source = "ReadASD1"
    except Exception as exc:
        print("ReadASD1 failed: {}: {}".format(type(exc).__name__, exc))
        print("Falling back to legacy ReadASD (A).")
        header, spectrum = ReadASD(s)
        source = "ReadASD"

    print("Acquisition source: {}".format(source))
    print("Header[0]={} header[22]={}".format(header[0], header[22]))
    print(
        "Spectrum stats: min={:.3f} max={:.3f} mean={:.3f}".format(
            float(np.min(spectrum)),
            float(np.max(spectrum)),
            float(np.mean(spectrum)),
        )
    )
    print(
        "Spectrum edge samples: first5={} last5={}".format(
            np.array2string(spectrum[:5], precision=3),
            np.array2string(spectrum[-5:], precision=3),
        )
    )
    return header, spectrum


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Minimal ASD spectrometer debug: connect, optimize, acquire single spectrum."
    )
    parser.add_argument("--host", default="169.254.1.11", help="ASD spectrometer host")
    parser.add_argument("--port", type=int, default=8080, help="ASD spectrometer TCP port")
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=30.0,
        help="Socket timeout in seconds",
    )
    parser.add_argument(
        "--optimize-retries",
        type=int,
        default=3,
        help="Number of optimize retries before failing",
    )
    args = parser.parse_args()

    sock = None
    try:
        sock = connect_debug_socket(args.host, args.port, args.timeout_s)

        print("\n=== Query VNIR info ===")
        vwl1, vwl2, vdcc = VNIRinfo(sock)
        print("VNIR info: Vwl1={} Vwl2={} VDCC={}".format(vwl1, vwl2, vdcc))

        optimize_result, optimize_err = try_optimize(sock, max(1, args.optimize_retries))
        if optimize_result is None:
            print("\nERROR: optimize failed after retries: {}".format(optimize_err))
            return 2

        acquire_single_spectrum(sock)
        print("\nDone: basic optimize + single acquisition completed.")
        return 0
    except Exception as exc:
        print("FATAL: {}: {}".format(type(exc).__name__, exc))
        return 1
    finally:
        if sock is not None:
            try:
                sock.close()
                print("Socket closed.")
            except Exception as exc:
                print("Socket close warning: {}: {}".format(type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
