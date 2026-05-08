#!/usr/bin/env python3

import socket
import time
from typing import Callable, List, Optional

from .asd_types import FRInterpSpec, InitStruct, OptimizeStruct, ITimeEnum, \
    create_FRInterpSpec, create_InitStruct, create_OptimizeStruct, ERRBYTE, CommandOutput, \
    InstrumentControlStruct, create_IC

MAX_WLEN = 2500
MIN_WLEN = 350
INITIAL_MESSAGE_BASE_LEN = 47
ACQUIRE_HEADER_SIZE = 64
OPT_SIZE = 7
RESTORE_SIZE = 1904
IC_SIZE = 4

class ASDException(Exception):
    pass

class ASDController:

    def __init__(self, ip: str = "10.1.1.11", port: int = 8080):
        self.ip = ip
        self.port = port
        self.closed = True
        self.sent_itime = None
        self.sent_gain1 = None
        self.sent_gain2 = None
        self._connect()

    def __del__(self):
        self.close()
    
    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.sock.settimeout(15)
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
            raise Exception("Timeout error receiving data. Received {}, expected {} ({} + {})".format(
                len(msg), total_bytes, data_bytes, initial_msg_len))
        return msg[initial_msg_len:]

    
    def _restore(self) -> InitStruct:
        self.sock.settimeout(60)
        self.sock.sendall(bytes("RESTORE,1", "utf-8"))
        data = self._recv(RESTORE_SIZE*4)
        return create_InitStruct(data)

    def _optimize(self) -> OptimizeStruct:
        self.sock.settimeout(60)
        self.sock.sendall(bytes("OPT,7", "utf-8"))
        data = self._recv(OPT_SIZE*4)
        return create_OptimizeStruct(data)
    
    def _acquire(self, n_averages: int) -> FRInterpSpec:
        self.sock.settimeout(5 + 1*n_averages)
        self.sock.sendall(bytes("A,1,{}".format(n_averages), "utf-8"))
        data = self._recv((MAX_WLEN - MIN_WLEN)*4 + ACQUIRE_HEADER_SIZE*4)
        return create_FRInterpSpec(data)
    
    def _set_itime(self, itime: ITimeEnum) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,2,0,{}".format(itime.value), "utf-8"))
        data = self._recv(IC_SIZE * 4)
        self.sent_itime = itime
        return create_IC(data)

    def _set_gain1(self, gain_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,0,1,{}".format(gain_value), "utf-8"))
        data = self._recv(IC_SIZE * 4)
        self.sent_gain1 = gain_value
        return create_IC(data)

    def _set_gain2(self, gain_value: int) -> InstrumentControlStruct:
        self.sock.settimeout(30)
        self.sock.sendall(bytes("IC,1,1,{}".format(gain_value), "utf-8"))
        data = self._recv(IC_SIZE * 4)
        self.sent_gain2 = gain_value
        return create_IC(data)

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
                return self.send_cmd(f, args, recursion-1)
            return out
        except (ConnectionResetError, BrokenPipeError):
            self.close()
            self._connect()
            self.restore()
            self.optimize() # This might be wrong, and/or restore too.
            if self.sent_itime is not None:
                self.set_itime(self.sent_itime)
            if self.sent_gain1 is not None:
                self.set_gain1(self.sent_gain1)
            if self.sent_gain2 is not None:
                self.set_gain2(self.sent_gain2)
            return self.send_cmd(f, args, recursion-1)

    def restore(self) -> InitStruct:
        return self.send_cmd(self._restore)

    def optimize(self) -> OptimizeStruct:
        return self.send_cmd(self._optimize)

    def acquire(self, n_averages: int) -> FRInterpSpec:
        return self.send_cmd(self._acquire, [n_averages])

    def set_itime(self, itime: ITimeEnum) -> InstrumentControlStruct:
        return self.send_cmd(self._set_itime, [itime])
    
    def set_gain1(self, gain1: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_gain1, [gain1])

    def set_gain2(self, gain2: int) -> InstrumentControlStruct:
        return self.send_cmd(self._set_gain2, [gain2])

    def close(self):
        if not self.closed:
            self.sock.close()
            self.closed = True

def translate_errbyte(errbyte: int) -> str:
    if errbyte in ERRBYTE:
        return ERRBYTE[errbyte]
    return str(errbyte)
