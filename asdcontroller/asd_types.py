#!/usr/bin/env python3

from dataclasses import dataclass
from enum import Enum
from typing import List
import struct
from abc import ABC, abstractmethod
import re

class CommandOutput(ABC):
    @abstractmethod
    def get_errbyte(self) -> int:
        pass

@dataclass
class VnirHeader: # 16 bytes
    it: int
    scans: int
    max_channel: int
    min_channel: int
    saturation: int
    shutter: int
    drift: int
    dark_substracted: int
    reserved: List[int] # len 8

@dataclass
class SwirHeader: # 16 bytes
    tec_status: int
    tec_current: int
    max_channel: int
    min_channel: int
    saturation: int
    a_scans: int
    b_scans: int
    dark_current: int
    gain: int
    offset: int
    scansize1: int
    scansize2: int
    dark_substracted: int
    reserved: List[int] # len 3

@dataclass
class SpectrumHeader: # 64 bytes
    header: int
    errbyte: int
    sample_count: int
    trigger: int
    voltage: int
    current: int
    temperature: int
    motor_current: int
    instrument_hours: int
    instrument_minutes: int
    instrument_type: int
    ab: int
    reserved: List[int] # len 4
    v_header: VnirHeader
    s1_header: SwirHeader
    s2_header: SwirHeader

@dataclass
class FRInterpSpec(CommandOutput):
    fr_spectrum_header: SpectrumHeader
    spec_buffer: List[float] # len 2151

    def to_npl_format(self):
        drift = self.fr_spectrum_header.v_header.drift
        for i in range(0, 1000 - 350 + 1):
            self.spec_buffer[i] = self.spec_buffer[i] - drift
    
    def get_errbyte(self) -> int:
        return self.fr_spectrum_header.errbyte

@dataclass
class OptimizeStruct(CommandOutput):
    header: int
    errbyte: int
    itime: int
    gain_1: int
    gain_2: int
    offset_1: int
    offset_2: int

    def get_errbyte(self) -> int:
        return self.errbyte

@dataclass
class InitStruct(CommandOutput):
    header: int
    errbyte: int
    name: List[str] # len 200 str of len 30
    value: List[float] # len 200 doubles
    count: int
    verify: int

    def get_errbyte(self) -> int:
        return self.errbyte

@dataclass
class InstrumentControlStruct(CommandOutput):
    header: int
    errbyte: int
    detector: int
    cmdType: int
    value: int

    def get_errbyte(self) -> int:
        return self.errbyte

class ITimeEnum(Enum):
    t8p5ms = -1
    t17ms = 0
    t34ms = 1
    t68ms = 2
    t136ms = 3
    t272ms = 4
    t544ms = 5
    t1p09s = 6
    t2p18s = 7
    t4p35s = 8
    t8p70s = 9
    t17p41s = 10
    t34p82s = 11
    t1p16min = 12
    t2p32min = 13
    t4p64min = 14
    t9p28min = 15

    def to_str(self) -> str:
        name = self.name[1:].replace('p', '.')
        space_i = name.rindex(re.findall(r'\d', name)[-1]) + 1
        name = name[:space_i] + " " + name[space_i:]
        return name

ERRBYTE = {
    0: "NO_ERROR",
    -1: "NOT_READY",
    -2: "NO_INDEX_MARKS",
    -3: "TOO_MANY_ZEROS",
    -4: "SCANSIZE_ERROR",
    -8: "MISSING_PARAMETER",
    -10: "VNIR_TIMEOUT",
    -11: "SWIR_TIMEOUT",
    -12: "VNIR_NOT_READY",
    -13: "SWIR1_NOT_READY",
    -14: "SWIR2_NOT_READY",
    -15: "VNIR_OPT_ERROR",
    -16: "SWIR1_OPT_ERROR",
    -17: "SWIR2_OPT_ERROR",
    -18: "ABORT_ERROR",
    -20: "VNIR_INTERP_ERROR",
    -21: "SWIR1_INTERP_ERROR",
    -22: "SWIR2_INTERP_ERROR",
}

def create_FRInterpSpec(data: bytes) -> FRInterpSpec:
    header_ints = []
    spec_buffer = []
    for i in range(0, 64*4, 4):
        val = struct.unpack('!i', data[i:i+4])[0]
        header_ints.append(val)
    for i in range(64*4, len(data)-3, 4):
        val = struct.unpack('!f', data[i:i+4])[0]
        spec_buffer.append(val)
    v_header = VnirHeader(*[*header_ints[16:24], header_ints[24:32]])
    s1_header = SwirHeader(*[*header_ints[32:45], header_ints[45:48]])
    s2_header = SwirHeader(*[*header_ints[48:61], header_ints[61:]])
    header_params = [*header_ints[:12], header_ints[12:16], v_header, s1_header, s2_header]
    header = SpectrumHeader(*header_params)
    return FRInterpSpec(header, spec_buffer)

def create_OptimizeStruct(data: bytes) -> OptimizeStruct:
    vals = []
    for i in range(0, len(data)-3, 4):
        val = struct.unpack('!i', data[i:i+4])[0]
        vals.append(val)
    return OptimizeStruct(*vals)

def create_InitStruct(data: bytes) -> InitStruct:
    ints_start = []
    names = []
    values = []
    ints_end = []
    pointer = 0
    for i in range(pointer, 2*4, 4):
        val = struct.unpack('!i', data[i:i+4])[0]
        ints_start.append(val)
    pointer = 2*4
    for i in range(200):
        name = data[pointer+i*30:pointer+(i+1)*30].decode("utf-8")
        names.append(name)
    pointer += 200*30
    for i in range(pointer, pointer+200*8, 8):
        val = struct.unpack('d', data[i:i+8])[0]
        values.append(val)
    pointer += 200*8
    for i in range(pointer, pointer+2*4, 4):
        val = struct.unpack('!i', data[i:i+4])[0]
        ints_end.append(val)
    params = [*ints_start, names, values, *ints_end]
    return InitStruct(*params)

def create_IC(data: bytes) -> InstrumentControlStruct:
    vals = []
    for i in range(0, len(data)-3, 4):
        val = struct.unpack('!i', data[i:i+4])[0]
        vals.append(val)
    return InstrumentControlStruct(*vals)
