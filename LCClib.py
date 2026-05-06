#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug  3 15:39:39 2018

@author: jouni
modified by Juha Suomalainen 2026-05-06

Interface for the LCC serial controller used in polarization measurements.

This module:
- connects to the LCC device over a serial VISA resource,
- initializes communication settings,
- exposes device state used by the application (for example LCC, NRets,
  RetStep, retardances, and LCCwl),
- provides helper functions to query wavelength-dependent retardance behavior.
"""
# pip3 install pyvisa pyvisa-py pyserial pyusb

try:
    import pyvisa as visa  # Preferred modern import (PyVISA package name)
except ImportError:
    import visa  # Fallback for older environments where PyVISA was imported as 'visa'

import time
import numpy as np

startt = "\x05"
resources = visa.ResourceManager("@py")
rm = visa.ResourceManager()
lr = rm.list_resources()
print(lr)
LCC = None
resources = visa.ResourceManager("@py")
trialres = [
    "ASRL/dev/ttyUSB0::INSTR",
    "ASRL/dev/ttyUSB1::INSTR",
    "ASRL/dev/ttyUSB3::INSTR",
    "ASRL/dev/ttyUSB4::INSTR",
    "ASRL/dev/ttyUSB5::INSTR",
    "ASRL/dev/ttyUSB6::INSTR",
    "ASRL/dev/ttyUSB7::INSTR",
    "ASRL/dev/ttyUSB8::INSTR",
]
for ress in trialres:
    try:
        LCC = resources.open_resource(ress)  # select the right device
        print(ress + " won.")
        break
    except:
        continue

if LCC == None:
    print("No LCC found, continue without")
    NRets = 0
    RetStep = 0.0
    LCCwl = []
else:
    startt = "\x05"
    # print('RT:',LCC.read_termination)
    # print('WT:',LCC.write_termination=='\r\n')
    print("starting LCC initialisation...")
    LCC.baud_rate = 115200
    LCC.timeout = 2000
    LCC.write(startt)
    LCC.read_termination = "\r"
    LCC.write_termination = "\r"

    time.sleep(1)
    print(LCC.read())  # to empty the buffer from some scratch
    print(LCC.read())
    print(LCC.query("*IDN?"))
    time.sleep(1)
    result = LCC.query("OM=1")
    result = LCC.query("WL=" + str(515))
    result = LCC.query("WL=515")
    LCCwlq = LCC.query("WL?")
    LCCwl = int(LCCwlq[4:7])
    print("LCC lead wavelength:", LCCwl, "nm")
    # print(len(LCD.query('WL?')))

    SP = LCC.query("SP?")
    WLmax = np.int(SP[7:10])
    SP = LCC.read()
    WLmin = np.int(SP[7:10])
    print(WLmin, WLmax)
    SP = LCC.read()
    SP = LCC.read()
    LCC.write("RE=0")
    NRets = 3
    RetStep = 103
    retardances = RetStep * np.arange(
        NRets - 1, -1, -1
    )  # more optimal to move this way
    print("Nominal Retardances:", retardances)
    volts = np.zeros(NRets)


def GetSpectralRetardances(ret, wls):
    result = LCC.query("RE=" + str(ret))
    print(result[:-2])
    vt00 = LCC.query("VT?")
    print(vt00[:-2])
    vt0 = np.single(vt00[3:-2])
    print(vt0, ":" + str(vt0) + ":")
    result = LCC.query("OM?")
    print(result[:-2])
    result = LCC.query("OM=2")
    print(result[:-2])
    result = LCC.query("OM?")
    print(result[:-2])
    Retardance = np.zeros(len(wls))
    for wl in wls:
        if (wl >= WLmin) * (wl <= WLmax):
            print("*" + str(wl) + "*")
            print("WL=" + str(wl) + "*")
            result = LCC.query("WL=" + str(wl))
            print(result[:-2])
            vt1 = LCC.query("VT=" + str(vt0)[:-1])
            print(vt1[:-2])
            re = LCC.query("RE?")
            print(re[:-2])
            vt = LCC.query("VT?")
            print(vt[:-2])
            wl1 = LCC.query("WL?")
            print(wl1[:-2])
            print(wl, wl1[3:-2], re[3:-2], vt[3:-2])
            Retardance[wl - 350] = np.int(re[3 : len(re) - 2])
    Retardance[: WLmin - 350] = Retardance[WLmin - 350]
    Retardance[WLmax - 350 :] = Retardance[WLmax - 350]
    result = LCC.query("OM=1")
    LCC.write(LCCwlq)
    return Retardance


def LCCcals(wls):
    iret = 0
    print("LCCcals:", retardances)
    Retardance = np.zeros((NRets, len(wls)))
    for ret in retardances[1:]:
        print(iret, ret)
        Retardance[iret, :] = GetSpectralRetardances(ret, wls)
        iret += 1
    return Retardance
