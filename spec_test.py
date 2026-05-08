import argparse
import sys
import numpy as np

from asdcontroller.asd_controller import ASDController


def print_spectrum_info(spec):
    header = spec.fr_spectrum_header
    spectrum = np.array(spec.spec_buffer, dtype=np.float32)
    print("Header.header={} Header.errbyte={}".format(header.header, header.errbyte))
    print(
        "VNIR: it={} scans={} drift={} dark_subtracted={}".format(
            header.v_header.it,
            header.v_header.scans,
            header.v_header.drift,
            header.v_header.dark_substracted,
        )
    )
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Minimal ASD spectrometer debug using asdcontroller."
    )
    parser.add_argument("--host", default="169.254.1.11", help="ASD spectrometer host")
    parser.add_argument("--port", type=int, default=8080, help="ASD spectrometer TCP port")
    parser.add_argument(
        "--optimize-retries",
        type=int,
        default=3,
        help="Number of optimize retries before failing",
    )
    args = parser.parse_args()

    ctrl = None
    try:
        print("Connecting to spectrometer host={} port={}".format(args.host, args.port))
        ctrl = ASDController(ip=args.host, port=args.port)
        print("Connected.")

        print("\n=== Restore ===")
        restore_result = ctrl.restore()
        print("Restore result: errbyte={} count={}".format(restore_result.errbyte, restore_result.count))

        print("\n=== Optimize ===")
        optimize_result = None
        optimize_err = None
        for attempt in range(1, max(1, args.optimize_retries) + 1):
            print("Optimize attempt {}/{}".format(attempt, max(1, args.optimize_retries)))
            try:
                optimize_result = ctrl.optimize()
                break
            except Exception as exc:
                optimize_err = exc
                print("Optimize failed: {}: {}".format(type(exc).__name__, exc))
        if optimize_result is None:
            print("\nERROR: optimize failed after retries: {}".format(optimize_err))
            return 2
        print(
            "Optimize result: itime={} gain1={} gain2={} off1={} off2={}".format(
                optimize_result.itime,
                optimize_result.gain_1,
                optimize_result.gain_2,
                optimize_result.offset_1,
                optimize_result.offset_2,
            )
        )

        print("\n=== Acquire single spectrum (A,1,1) ===")
        spec = ctrl.acquire(1)
        print_spectrum_info(spec)
        print("\nDone: basic optimize + single acquisition completed.")
        return 0
    except Exception as exc:
        print("FATAL: {}: {}".format(type(exc).__name__, exc))
        return 1
    finally:
        if ctrl is not None:
            try:
                ctrl.close()
                print("Connection closed.")
            except Exception as exc:
                print("Connection close warning: {}: {}".format(type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
