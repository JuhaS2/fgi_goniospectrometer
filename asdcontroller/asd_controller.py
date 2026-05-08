#!/usr/bin/env python3

import socket
import struct
import time
from typing import Callable, List, Optional, Tuple

from .asd_types import FRInterpSpec, InitStruct, OptimizeStruct, ITimeEnum, \
    create_FRInterpSpec, create_InitStruct, create_OptimizeStruct, ERRBYTE, CommandOutput, \
    InstrumentControlStruct, create_IC, itime_int_to_enum

MAX_WLEN = 2500
MIN_WLEN = 350
INITIAL_MESSAGE_BASE_LEN = 47
ACQUIRE_HEADER_SIZE = 64
OPT_SIZE = 7
RESTORE_SIZE = 1904
# ASDlib SetOpt uses recv(20) per IC reply (5 x int32).
IC_REPLY_BYTES = 20


class ASDException(Exception):
    pass


class ASDController:

    def __init__(self, ip: str = "10.1.1.11", port: int = 8080, default_sock_timeout_s: float = 30.0):
        self.ip = ip
        self.port = port
        self.default_sock_timeout_s = default_sock_timeout_s
        self.closed = True
        self.sent_itime = None
        self.sent_gain1 = None
        self.sent_gain2 = None
        self.sent_offset0 = None
        self.sent_offset1 = None
        self._connect()

    def __del__(self):
        self.close()

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(self.default_sock_timeout_s)
        self.sock.connect((self.ip, self.port))
        self.closed = False
        self.hello = True

    def _recv(self, data_bytes: int) -> bytes:
        initial_msg_len = 0
        if self.hello:
            initial_msg_len = len(self.ip) + len(str(self.port)) + INITIAL_MESSAGE_BASE_LEN
            self.hello = False
        msg: bytes = b''
        total_bytes = initial_msg_len + data_bytes
        try:
            while len(msg) < total_bytes:
                rec = self.sock.recv(16384)
                msg += rec
                time.sleep(0.1)
        except socket.timeout:
            raise socket.timeout(
                "Timeout receiving ASD data: got {} of {} bytes (payload {} + hello {})".format(
                    len(msg), total_bytes, data_bytes, initial_msg_len
                )
            )
        return msg[initial_msg_len:]

    def _restore(self) -> InitStruct:
        self.sock.settimeout(60)
        self.sock.sendall(bytes("RESTORE,1", "utf-8"))
        data = self._recv(RESTORE_SIZE * 4)
        return create_InitStruct(data)

    def _optimize(self) -> OptimizeStruct:
        self.sock.settimeout(60)
        self.sock.sendall(bytes("OPT,7", "utf-8"))
        data = self._recv(OPT_SIZE * 4)
        return create_OptimizeStruct(data)

    def _acquire(self, n_averages: int) -> FRInterpSpec:
        self.sock.settimeout(5 + 1 * n_averages)
        self.sock.sendall(bytes("A,1,{}".format(n_averages), "utf-8"))
        data = self._recv((MAX_WLEN - MIN_WLEN) * 4 + ACQUIRE_HEADER_SIZE * 4)
        return create_FRInterpSpec(data)

    def _set_itime(self, itime: ITimeEnum) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,2,0,{}".format(itime.value), "utf-8"))
        data = self._recv(IC_REPLY_BYTES)
        self.sent_itime = itime
        return create_IC(data)

    def _set_gain1(self, gain_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,0,1,{}".format(gain_value), "utf-8"))
        data = self._recv(IC_REPLY_BYTES)
        self.sent_gain1 = gain_value
        return create_IC(data)

    def _set_gain2(self, gain_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,1,1,{}".format(gain_value), "utf-8"))
        data = self._recv(IC_REPLY_BYTES)
        self.sent_gain2 = gain_value
        return create_IC(data)

    def _set_offset0(self, offset_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,0,2,{}".format(offset_value), "utf-8"))
        data = self._recv(IC_REPLY_BYTES)
        self.sent_offset0 = offset_value
        return create_IC(data)

    def _set_offset1(self, offset_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,1,2,{}".format(offset_value), "utf-8"))
        data = self._recv(IC_REPLY_BYTES)
        self.sent_offset1 = offset_value
        return create_IC(data)

    def _init_query_double(self, param_ascii: str) -> float:
        self.sock.settimeout(30)
        self.sock.sendall(b"INIT,0," + param_ascii.encode("ascii"))
        data = self._recv(50)
        if len(data) < 50:
            raise ASDException("INIT reply too short: {} bytes".format(len(data)))
        header, errbyte, _name, value_d, _count = struct.unpack(">ii30sdi", data[:50])
        if errbyte != 0:
            raise ASDException(
                "INIT {} error: errbyte={} header={}".format(param_ascii, errbyte, header)
            )
        return float(value_d)

    def send_cmd(self, f: Callable, args: Optional[List] = None, recursion: int = 3):
        if args is None:
            args = []
        try:
            out: CommandOutput = f(*args)
            errbyte = out.get_errbyte()
            if errbyte != 0:
                if recursion == 0:
                    raise ASDException("ASD ERROR {}: {}. When {}.".format(errbyte,
                        translate_errbyte(errbyte), f))
                time.sleep(0.1)
                return self.send_cmd(f, args, recursion - 1)
            return out
        except (ConnectionResetError, BrokenPipeError):
            self.close()
            self._connect()
            self.restore()
            self.optimize()
            if self.sent_itime is not None:
                self.set_itime(self.sent_itime)
            if self.sent_gain1 is not None:
                self.set_gain1(self.sent_gain1)
            if self.sent_gain2 is not None:
                self.set_gain2(self.sent_gain2)
            if self.sent_offset0 is not None:
                self.set_offset0(self.sent_offset0)
            if self.sent_offset1 is not None:
                self.set_offset1(self.sent_offset1)
            return self.send_cmd(f, args, recursion - 1)

    def restore(self) -> InitStruct:
        return self.send_cmd(self._restore)

    def optimize(self) -> OptimizeStruct:
        opt = self.send_cmd(self._optimize)
        if opt.itime > 5:
            cap_enum = itime_int_to_enum(5)
            self.set_itime(cap_enum)
            return OptimizeStruct(
                opt.header,
                opt.errbyte,
                5,
                opt.gain_1,
                opt.gain_2,
                opt.offset_1,
                opt.offset_2,
            )
        return opt

    def acquire(self, n_averages: int) -> FRInterpSpec:
        return self.send_cmd(self._acquire, [n_averages])

    def set_itime(self, itime: ITimeEnum) -> InstrumentControlStruct:
        return self.send_cmd(self._set_itime, [itime])

    def set_gain1(self, gain1: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_gain1, [gain1])

    def set_gain2(self, gain2: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_gain2, [gain2])

    def set_offset0(self, offset0: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_offset0, [offset0])

    def set_offset1(self, offset1: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_offset1, [offset1])

    def apply_set_opt(self, itime_int: int, gain: List[int], offset: List[int]) -> None:
        """Match ASDlib SetOpt ordering: itime, offset[1], offset[0], gain[1], gain[0]."""
        self.send_cmd(self._set_itime, [itime_int_to_enum(int(itime_int))])
        self.send_cmd(self._set_offset1, [int(offset[1])])
        self.send_cmd(self._set_offset0, [int(offset[0])])
        self.send_cmd(self._set_gain2, [int(gain[1])])
        self.send_cmd(self._set_gain1, [int(gain[0])])

    def vnir_info(self) -> Tuple[float, float, float]:
        vwl1 = self._init_query_double("VStartingWavelength")
        vdcc = self._init_query_double("VDarkCurrentCorrection")
        vwl2 = self._init_query_double("VEndingWavelength")
        return vwl1, vwl2, vdcc

    def close(self):
        if not self.closed:
            self.sock.close()
            self.closed = True


def translate_errbyte(errbyte: int) -> str:
    if errbyte in ERRBYTE:
        return ERRBYTE[errbyte]
    return str(errbyte)
