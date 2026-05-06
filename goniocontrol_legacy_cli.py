#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Jun 13 14:58:52 2018

Control new SpaceGeoGonioSpectroPolariMeter ()

@author: jouni

THIS IS AN OLD OUTDATED COMMANDLINE VERSION! USE goniocontrol.py with GUI INSTEAD!

Versions:
2023-09-08  Juha Suomalainen
* Added support for using non-existing paths and subdirs for output file. E.g. outfile = 'mysubdir/mydatafile'
* "Restore" no longer asks to set a new file name. You need to do it manually separately.
* Added support for TakeI-function to take average of spectra with syntax "TakeI(s,repeats=1)"
  Such support has not been added to other polarized Take* functions!
* Dark current and white reference are now collected with 25 averages.
  Again, polarized WR still use just single measurements
* Measure task now asks for how many averages to take at each angle.
* Improved error handling. User commands cannot anymore make the program crash.
  In case of error, the exception traceback shown on screen but measurements can be continued normally.
* Cleaned up code and added commenting.

2023-09-01  Juha Suomalainen
* VNIR dark current was not corrected perfectly with ASD maths.
  Added in Dark-function a measurement of a dark radiance spectrum.
  This is subtracted from all later radiances.
  WARNING! THIS HAS BEEN IMPLEMENTED ONLY ON SINGLE POLARIZATION MATHS. IF THIS WORKS, ADD THE FIX ALSO TO POLARIZATION MATHS

2023-08-30  Juha Suomalainen
* "What do you want, Sir?"-input accepts now also lowercase letters
* Options now show the "Go"-feature that drives sensor zenith angle
* Command "0" switches the data saving mode between the radiance and reflectance mode. Default is reflectance mode

2023-08-30  Jouni Peltoniemi
* Original version

"""

# TODO:
# * Add residual dark current correction also to polarized Take* measurements!!!
# * Add repeats-parameter to also the polarized Take* measurements? Implement also in polarized White reference measurement?
# * move multiwave plate to lamp. horizontal
# * take calibration from LCC
# * find a way to extend the calibration to SWIR
#

# %% Imports

import numpy as np
import matplotlib.pyplot as plt
import socket
import time
import pickle
import json
import os
import traceback


try:
    from pyximc import *
except ImportError as err:
    print(
        "Can't import pyximc module. The most probable reason is that you changed the relative location of the testpython.py and pyximc.py files. See developers' documentation for details."
    )
    exit()
except OSError as err:
    print(
        "Can't load libximc library. Please add all shared libraries to the appropriate places. It is decribed in detail in developers' documentation. On Linux make sure you installed libximc-dev package.\nmake sure that the architecture of the system and the interpreter is the same"
    )
    exit()

import LCClib
from ASDlib import *

# %% Helping functions


def plottaile(wl, data):
    l = len(data)
    za = np.zeros(l)
    I515 = np.zeros(l)
    Q515 = np.zeros(l)
    U515 = np.zeros(l)
    V515 = np.zeros(l)
    i = 0
    for datum in data:
        # print('datum:',datum)
        SS = datum[4]

        plt.plot(wl, SS[0])
        plt.ylim(0.0, 2.0)
        plt.xlabel("wavelength/nm")
        plt.ylabel("BRF")
        plt.show()
        plt.plot(wl, SS[1] / SS[0], "r-", label="Q")
        plt.plot(wl, SS[2] / SS[0], "b-", label="U")
        #        plt.plot(wl,SS[3]/SS[0],'g-',label='V')
        plt.ylim(-1.0, 1.0)
        plt.xlabel("wavelength/nm")
        plt.ylabel("Polarization")
        plt.legend()
        plt.show()
        za[i] = datum[2]
        I515[i] = datum[4][0][515 - 350]
        Q515[i] = datum[4][1][515 - 350]
        U515[i] = datum[4][2][515 - 350]
        #        V515[i]=datum[4][3][515-350]
        i += 1
    plt.plot(za, I515)
    plt.xlabel("zenith angle / deg")
    plt.ylabel("BRF")
    plt.show()
    plt.plot(za, Q515 / I515, "r.", label="Q")
    plt.plot(za, U515 / I515, "b.", label="U")
    #    plt.plot(za,V515/I515,'g.',label='V')
    plt.xlabel("zenith angle")
    plt.ylabel("Polarization")
    plt.legend()
    plt.show()


def plot2(wl, datum):

    SS = datum[5]
    fig = plt.figure()
    ax1 = fig.add_subplot(121)
    ax2 = fig.add_subplot(122)
    ax1.plot(wl, SS[0])
    ax1.set_ylim(0.0, 1.0)
    ax1.set_xlabel("wavelength/nm")
    ax1.set_ylabel("BRF")

    ax2.plot(wl, SS[1] / SS[0], "r-", label="Q")
    ax2.plot(wl, SS[2] / SS[0], "b-", label="U")
    #        plt.plot(wl,SS[3]/SS[0],'g-',label='V')
    ax2.set_ylim(-0.50, 0.50)
    ax2.set_xlabel("wavelength/nm")
    ax2.set_ylabel("Polarization")
    ax2.legend()
    plt.show()


t0 = time.time()


def TakePolSequence(P_id, s, pcalib, wg_pols, retardances, P0):
    subdata = []
    t0 = time.time()
    for wg_pol in wg_pols:
        result = lib.command_move(P_id, int(80 * wg_pol) + P0.Position, P0.uPosition)
        result = lib.command_wait_for_stop(P_id, 10)

        for ret in retardances:
            LCClib.LCC.write("RE=" + str(ret))
            print(
                "Retardance=", ret, " polangle=", wg_pol
            )  # ,time.process_time(),time.time()-t0)
            #             t0=time.time()
            header, spectrum = ReadASD(s)
            driftM = header[22]
            subdata.append((ret, wg_pol, spectrum, driftM))
        LCClib.LCC.write(
            "RE=" + str(retardances[0])
        )  # slower movement back, starting now

    result = LCClib.LCC.read()  # to empty the buffer
    result = lib.command_move(
        P_id, P0.Position, P0.uPosition
    )  # start moving to zero for next measurement

    return subdata


def TakePolSequence44(
    P_id, L_id, s, Pcalib, Lcalib, wg_pols, retardances, ls_pols, P0, L0
):
    subdata = []
    t0 = time.time()
    for ls_pol in ls_pols:
        result = lib.command_move(L_id, int(80 * ls_pol) + L0.Position, L0.uPosition)
        for wg_pol in wg_pols:
            result = lib.command_move(
                P_id, int(80 * wg_pol) + P0.Position, P0.uPosition
            )
            result = lib.command_wait_for_stop(L_id, 10)
            result = lib.command_wait_for_stop(P_id, 10)

            for ret in retardances:
                LCClib.LCC.write("RE=" + str(ret))
                print(
                    "Retardance=",
                    ret,
                    " sensor polangle=",
                    wg_pol,
                    " lamp polangle=",
                    ls_pol,
                )  # ,time.process_time(),time.time()-t0)
                #             t0=time.time()
                header, spectrum = ReadASD(s)
                driftM = header[22]
                subdata.append((ret, wg_pol, ls_pol, spectrum, driftM))
            LCClib.LCC.write(
                "RE=" + str(retardances[0])
            )  # slower movement back, starting now

    result = LCClib.LCC.read()  # to empty the buffer
    result = lib.command_move(
        P_id, P0.Position, P0.uPosition
    )  # start moving to zero for next measurement
    result = lib.command_move(L_id, L0.Position, L0.uPosition)
    return subdata


def TakePolSequenceIQU(P_id, s, pcalib, wg_pols, retardances, P0):
    subdata = []
    t0 = time.time()
    LCClib.LCC.write("RE=0")
    for wg_pol in wg_pols:
        result = lib.command_move(P_id, int(80 * wg_pol) + P0.Position, P0.uPosition)
        result = lib.command_wait_for_stop(P_id, 10)
        ret = 0.0

        print(
            "Retardance=", 0, " polangle=", wg_pol
        )  # ,time.process_time(),time.time()-t0)
        #             t0=time.time()
        header, spectrum = ReadASD(s)
        driftM = header[22]
        subdata.append((ret, wg_pol, spectrum, driftM))
    # move next?
    #    LCClib.LCC.write('RE=0')
    result = LCClib.LCC.read()  # to empty the buffer
    result = lib.command_move(
        P_id, P0.Position, P0.uPosition
    )  # start moving to zero for next measurement
    return subdata


def TakeI(s, repeats=1):
    #    t0=time.time()
    #             t0=time.time()
    # collect data from spectrometer
    spectum_sum = 0
    header, spectrum = ReadASD1(s, repeats)
    driftM = header[22]
    ret = 0.0
    wg_pol = 0.0
    # store to subdata format and return
    subdata = []
    subdata.append((ret, wg_pol, spectrum, driftM))
    return subdata


NcalRs = LCClib.NRets  # ????
calpols = 45 * np.arange(8)
calrets = 103 * np.arange(NcalRs)


def TakeCalSequence(P_id, s, P0):  # probably not needed any more
    subdata = []
    t0 = time.time()
    for wg_pol in calpols:
        result = lib.command_move(P_id, int(80 * wg_pol) + P0.Position, P0.uPosition)
        result = lib.command_wait_for_stop(P_id, 10)
        for ret in calrets:
            LCC.write("RE=" + str(ret))
            print("Retardance=", ret, " polangle=", wg_pol)
            header, spectrum = ReadASD(s)
            driftM = header[22]
            subdata.append((ret, wg_pol, spectrum, driftM))
    # move next?

    return subdata  # makeStokes(subdata,DC,WS,polcal)


def CalPol(data):
    Q0 = 0.0
    U0 = 0.0
    for datum in data:
        Q0 += np.sum(datum[4][1][100:500])
        U0 += np.sum(datum[4][2][100:500])
    alpha = 0.5 * np.arctan2(U0, Q0)
    if (np.sin(2 * alpha) * U0 + np.cos(2 * alpha)) < 0.0:
        alpha = alpha + np.pi * 0.5
    print("calibrated alpha: ", alpha)
    return alpha


# %% CONNECT TO MOTOR CONTROLLERS

Brot = False  # until found
SNames = [
    "xi-com:///dev/ttyACM0",
    "xi-com:///dev/ttyACM1",
    "xi-com:///dev/ttyACM2",
    "xi-com:///dev/ttyACM3",
    "xi-com:///dev/ttyACM4",
    "xi-com:///dev/ttyACM5",
    "xi-com:///dev/ttyACM6",
    "xi-com:///dev/ttyACM7",
    "xi-com:///dev/ttyACM8",
    "xi-com:///dev/ttyACM9",
    "xi-com:///dev/ttyACM10",
]
for StandaName in SNames:
    # print(StandaName)
    StandaName = StandaName.encode()
    id = lib.open_device(StandaName)
    # print(id)
    x_serial = c_uint()
    result = lib.get_serial_number(id, byref(x_serial))
    # print(x_serial.value)
    if x_serial.value == 13536 + 0 * 12202:  # sensor polariser
        P_id = id
        Pcalib = calibration_t()
        eeP = engine_settings_t()
        lib.get_engine_settings(P_id, byref(eeP))
        Pcalib.MicrostepMode = eeP.MicrostepMode
        Pcalib.A = 1.0 / 80.0
        print(StandaName, id, x_serial.value)
    elif x_serial.value == 99 + 13536:  # lamp polariser
        L_id = id
        Lcalib = calibration_t()
        eeL = engine_settings_t()
        lib.get_engine_settings(L_id, byref(eeL))
        Lcalib.MicrostepMode = eeL.MicrostepMode
        Lcalib.A = 1.0 / 80.0
        print(StandaName, id, x_serial.value)
    elif x_serial.value == 12224:  # sample motor
        B_id = id
        Brot = True
        Bcalib = calibration_t()
        eeB = engine_settings_t()
        lib.get_engine_settings(B_id, byref(eeB))
        Bcalib.MicrostepMode = eeB.MicrostepMode
        Bcalib.A = 1.0 / 100.0
        Bmove = move_settings_t()
        lib.get_move_settings(B_id, byref(Bmove))

        Bmove.Decel = Bmove.Accel
        Bmove.Speed = 1000
        print("Bmove:", Bmove.Accel, Bmove.Decel, Bmove.Speed)
        lib.set_move_settings(B_id, byref(Bmove))
        print(StandaName, id, x_serial.value)
    elif x_serial.value == 13217:  # zenith motor
        Z_id = id
        Zcalib = calibration_t()
        eeZ = engine_settings_t()
        lib.get_engine_settings(Z_id, byref(eeZ))
        Zcalib.MicrostepMode = eeZ.MicrostepMode
        Zcalib.A = 1.0 / 100.0
        Zmove = move_settings_t()
        lib.get_move_settings(Z_id, byref(Zmove))
        Zmove.Decel = Zmove.Accel
        print("Zmove;", Zmove.Accel, Zmove.Decel, Zmove.Speed)
        lib.set_move_settings(Z_id, byref(Zmove))
        print(StandaName, id, x_serial.value)
    elif x_serial.value == 13225:  # azimuth motor
        A_id = id
        Acalib = calibration_t()
        eeA = engine_settings_t()
        lib.get_engine_settings(A_id, byref(eeA))
        Acalib.MicrostepMode = eeA.MicrostepMode
        Acalib.A = 1.0 / 100.0
        Amove = move_settings_t()
        lib.get_move_settings(A_id, byref(Amove))
        Amove.Decel = Amove.Accel

        #        Amove.Speed=1000  # hopefully this is less
        lib.set_move_settings(A_id, byref(Amove))
        print("Amove:", Amove.Accel, Amove.Decel, Amove.Speed)
        print(StandaName, id, x_serial.value)
    #       STOP
    else:
        lib.close_device(byref(cast(id, POINTER(c_int))))
        print(
            "unknown motor:",
            x_serial.value,
            "If stuck here, check all connections to motors, controllers, and power, and reboot!",
        )


print(
    "Move manually all motors to zero position! (zenith arm, azimuth, sample, polarizers, ...) "
)
input("Press Return, when done!")


Z_pos0 = get_position_t()
result = lib.get_position(Z_id, byref(Z_pos0))
print("Position: {0} steps, {1} microsteps".format(Z_pos0.Position, Z_pos0.uPosition))

Z_pos1 = get_position_calb_t()
result = lib.get_position_calb(Z_id, byref(Z_pos1), byref(Zcalib))
print("Position: {0} deg, {1} encoder".format(Z_pos1.Position, Z_pos1.EncPosition))

A_pos0 = get_position_t()
result = lib.get_position(A_id, byref(A_pos0))
print("Position: {0} steps, {1} microsteps".format(A_pos0.Position, A_pos0.uPosition))

A_pos1 = get_position_calb_t()
result = lib.get_position_calb(A_id, byref(A_pos1), byref(Acalib))
print("Position: {0} deg, {1} encoder".format(A_pos1.Position, A_pos1.EncPosition))

if Brot:
    B_pos0 = get_position_t()
    result = lib.get_position(B_id, byref(B_pos0))
    print(
        "Position: {0} steps, {1} microsteps".format(B_pos0.Position, B_pos0.uPosition)
    )

    B_pos1 = get_position_calb_t()
    result = lib.get_position_calb(B_id, byref(B_pos1), byref(Bcalib))
    print("Position: {0} deg, {1} encoder".format(B_pos1.Position, B_pos1.EncPosition))
else:
    print("No sample rotator.")

try:
    P_pos0 = get_position_t()
    result = lib.get_position(P_id, byref(P_pos0))
    print(
        "Position: {0} steps, {1} microsteps".format(P_pos0.Position, P_pos0.uPosition)
    )

    P_pos1 = get_position_calb_t()
    result = lib.get_position_calb(P_id, byref(P_pos1), byref(Pcalib))
    print("Position: {0} deg, {1} encoder".format(P_pos1.Position, P_pos1.EncPosition))
except:
    print("no polariser")
    npols = 1
try:
    L_pos0 = get_position_t()
    result = lib.get_position(L_id, byref(L_pos0))
    print(
        "Position: {0} steps, {1} microsteps".format(L_pos0.Position, L_pos0.uPosition)
    )

    L_pos1 = get_position_calb_t()
    result = lib.get_position_calb(L_id, byref(L_pos1), byref(Lcalib))
    print("Position: {0} deg, {1} encoder".format(L_pos1.Position, L_pos1.EncPosition))
    npols = 16
except:
    print("Light polariser not set")
    npols = np.minimum(npols, 3)

# result = lib.command_move_calb(P_id, byref(P_pos1), byref(pcalib))


wg_pols = np.array(
    [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
)  ####+P_pos1.Position
wg_pols = np.array([0, 45, 90, 135])
# wg_pols=np.array([0,45])#,90,135])
lamppol = 99
sunpols = [0]  # ,90]
angles = []
anglef = open("Angles.txt")
for line in anglef:
    if line[0] == "S":
        break
    if line[0] != "#":
        angs = np.array(line.split(), dtype="float")
        # print(angs)
        angles.append(angs)
anglef.close()
NA = len(angles)
print(
    "Just checking, that everythigh moves and returns to original position. This tells the positive direction."
)
ze = 0
az = 0
be = 0
result = lib.command_move(A_id, int(az * 100 + A_pos0.Position), A_pos0.uPosition)
print(result)
result = lib.command_move(Z_id, int(ze * 100 + Z_pos0.Position), Z_pos0.uPosition)
print(result)
result = lib.command_move(B_id, int(be * 100 + B_pos0.Position), B_pos0.uPosition)
print(result)
# result = lib.command_move(P_id,int(be*100+P_pos0.Position),P_pos0.uPosition)
result = lib.command_wait_for_stop(Z_id, 10)
print(result)
result = lib.command_wait_for_stop(A_id, 10)
print(result)
# result = lib.command_wait_for_stop(P_id, 10)
result = lib.command_wait_for_stop(B_id, 10)
print(result)
result = lib.command_move(A_id, int(A_pos0.Position), A_pos0.uPosition)
result = lib.command_move(Z_id, int(Z_pos0.Position), Z_pos0.uPosition)
result = lib.command_move(B_id, int(B_pos0.Position), B_pos0.uPosition)
# result = lib.command_move(P_id,int(P_pos0.Position),P_pos0.uPosition)


# %% CONNECT TO SPECTROMETER
# define connection to ASD spectrometer
HOST = "169.254.1.11"  # The ASD spectrometer remote host
PORT = 8080  # The same port as used by the server
# Connect to spectrometer
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
print("connecting:", HOST, PORT)
s.connect((HOST, PORT))
print("connected.")
print(s.recv(128))  # greetings

# %% RESTORE PREVIOUS MEASUREMENT STATE


# init data structure
data = []

# get VNIR info and generate list of wavelengths
Vwl1, Vwl2, VDCC = VNIRinfo(s)
wl = Vwl1 + np.arange(Nwl)

# read previous dark current and white reference values
DC = np.load("DC.npy")
driftDC = np.load("DriftDC.npy")
if npols == 3:
    AA = np.load("AA3.npy")
    WC = np.load("White3.npy")
elif npols == 4:
    AA = np.load("AA4.npy")
    WC = np.load("White4.npy")
elif npols == 16:
    AA = np.load("AA44.npy")
    WC = np.load("White44.npy")
elif npols == 1:
    WC = np.load("White1.npy")

try:  # smooth restart with ongoing measurement
    of = open("outfile.txt")
    outfile = of.readline()
    print("Outfilename:", outfile)
    of.close()
    #    outfile=np.load("outfile.npy")
    try:
        with open(outfile + ".pickle", "rb") as handle:
            data = pickle.load(handle)
            print(
                "Old data exist. Appending data, but not clever enough to start, where it stopped, sorry."
            )
    except:
        data = []
except:
    outfile = "Test00"
    print("Outfilename:", outfile)

# for a warm start, read and set old Optimiser parameters
Oheader = np.load("Oheader.npy")
SetOpt(s, Oheader[2], Oheader[3], Oheader[4])
itime = Oheader[2]

# %% MAIN LOOP
# Is the operating mode saving reflectances or radiances?
reflectance_mode = True
print('Operating mode is REFLECTANCE. Use command "S" to switch to radiance.')

# Loop asking for and performing commands until user quits with "Q"
cmd_queue = []
while True:

    # Ask user for next command, if there are no commands in queue
    if len(cmd_queue) == 0:
        try:
            print("\nWhat do you want, Sir?")
            if reflectance_mode:
                goo = input(
                    "New, Restore, Optimize, Dark, White, [View], Measure, Ending white, [Go], [Plot], [Zero], Quit.\n"
                )
            else:
                goo = input(
                    "New, Restore, Optimize, Dark, Measure, [Go], [Zero], Quit.\n"
                )
            # format command to single uppercase letter
            go = goo[0].upper()
            # add command to queue
            cmd_queue.append(go)
            # print(go)
        except:
            print("Wrong input.")

    # get the first command from the command queue
    if len(cmd_queue) > 0:
        go = cmd_queue.pop(0)
    else:
        go = ""

    # Perform the commanded task
    try:
        if go == "R":  # RESTORE
            print("RESTORE")
            Restore(s)
            # outfile=input('Output file name?\n')
            # of=open('outfile.txt','w')
            # of.write(outfile)
            # of.close()
            # np.save('outfile',outfile)
            # data=[]
            Vwl1, Vwl2, VDCC = VNIRinfo(s)
            print("VDCC:", VDCC)

        elif go == "N":  # START NEW DATASET TO A NEW OUTPUT FILE
            print("NEW DATASET")
            # start new measurement without restore
            # ask for output file
            outfile = input("Output file name?\n")

            # save outputfile path to a txt file, for smooth continue
            of = open("outfile.txt", "w")
            of.write(outfile)
            of.close()
            # save it also in numpy format
            np.save("outfile", outfile)

            # create the subdir if user defined file in one
            subdirpath = os.path.split(outfile)[0]
            if subdirpath != "":
                os.makedirs(subdirpath, exist_ok=True)

            # reset data
            data = []

        # elif (go=='F'): # IS THIS SOME OUTDATED VERSION OF "N"
        #     outfile=input('Output file name?'\n)
        #     out=open(outfile+'.txt','w')
        #     for d in data:
        #         out.write(str(d)+'\n')
        #     out.close()
        #     with open(outfile+'.pickle', 'wb') as handle:
        #         pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

        elif go == "O":  # OPTIMIZE SPECTROMETER
            print("OPTIMIZE")
            # Instruct user and ask at which zenith angle the optimization will be collected on
            WRZA = np.float(input("Put white reference! Give WR zenith angle!\n"))
            # Drive to the angle
            result = lib.command_move(
                Z_id, int(WRZA * 100 + Z_pos0.Position), Z_pos0.uPosition
            )  # Move to selected position
            result = lib.command_wait_for_stop(Z_id, 10)
            # optimize the spectrometer
            for i in range(25):  # sometoimes optimisation fails. retry a few times
                Oheader = Optimize(s)
                if Oheader[0] == 100:
                    break
            itime = Oheader[2]
            np.save("Oheader", Oheader)
            print("Optimized:", Oheader, itime)
            # Vwl1,Vwl2,VDCC=VNIRinfo(s)

            # after optimization it is mandatory to take a new dark current
            cmd_queue.append("D")

        elif go == "D":  # DARK CURRENT
            print("DARK CURRENT")
            #            DC,DriftDC=DarkCurrent(s,itime)
            DC, DriftDC = DarkCurrent2(s, 25)

            # The ASD's mathematics for DC in VNIR are not working perfectly.
            # Thus we must now collect a radiance spectrum that should be zero, but isn't
            Idata = TakeI(s, repeats=25)
            DC_remainder = MakeI(Idata, DC, driftDC, VDCC)

            np.save("DC", DC)
            np.save("DriftDC", DriftDC)
            np.save("DC_remainder", DC_remainder)
            # plt.plot(wl,DC)
            # plt.show()
            # Vwl1,Vwl2,VDCC=VNIRinfo(s)
            print("Dark current collected.")

        elif go == "S":  # SWITCH BETWEEN REFLECTANCE AND RADIANCE MODE
            print("SWITCH BETWEEN REFLECTANCE AND RADIANCE")
            # switch between reflectance and radiance mode
            reflectance_mode = not reflectance_mode
            if reflectance_mode:
                print(
                    'Operating mode is REFLECTANCE. Use command "S" to switch to radiance.'
                )
            else:
                print(
                    'Operating mode is RADIANCE. Use command "S" to switch to reflectance.'
                )

        elif go[0] == "C":  # CALIBRATE POLARIZER
            print("CALIBRATE POLARIZER")
            PCZA = np.float(
                input(
                    "Calibrating polarizer. Give a forward zenith angle (>0) of max polarization and ensure full left-right symmetry!\n"
                )
            )
            result = lib.command_move(
                Z_id, int(PCZA * 100 + Z_pos0.Position), Z_pos0.uPosition
            )
            result = lib.command_wait_for_stop(Z_id, 10)

            caldata = TakePolSequence(
                P_id, s, pcalib, wg_pols, LCClib.retardances, P_pos0
            )
            #             cal=CalAA(caldata,DC,driftDC,VDCC)
            #             AA=MakeAA(WRdata)
            #             np.save('AA',AA)
            alpha = PolCal(caldata)
            P_pos0.Position += alpha * 80 / deg
            print("cal taken.")

        # elif (go[0]=='L'): # SOME UNKNOWN NON-FUNCTIONING FEATURE
        #      print('This is not really working.')
        #      RetardanceTable=LCClib.LCCcals(wl)
        #      np.save('RetardanceTable',RetardanceTable)

        elif go[0] == "W":  # WHITE REFERENCE
            print("WHITE REFERENCE")
            WRZA = np.float(input("Put white reference! Give WR zenith angle!\n"))
            result = lib.command_move(
                Z_id, int(WRZA * 100 + Z_pos0.Position), Z_pos0.uPosition
            )
            result = lib.command_wait_for_stop(Z_id, 10)

            if npols == 16:
                WRdata = TakePolSequence44(
                    P_id,
                    L_id,
                    s,
                    Pcalib,
                    Lcalib,
                    wg_pols,
                    LCClib.retardances,
                    P_pos0,
                    L_pos0,
                )
                AA = MakeAA44(WRdata)
                np.save("AA44", AA)
                WC = MakeMuller(WRdata, DC, driftDC, VDCC, AA)
                np.save("White44", WC)
            elif npols == 3:
                WRdata = TakePolSequenceIQU(
                    P_id, s, Pcalib, wg_pols, LCClib.retardances, P_pos0
                )
                AA = MakeAA3(WRdata)
                np.save("AA3", AA)
                WC = MakeStokesIQU(WRdata, DC, driftDC, VDCC, AA)
                np.save("White3", WC)
            elif npols == 1:
                WRdata = TakeI(s, repeats=25)
                WC = MakeI(WRdata, DC, driftDC, VDCC) - DC_remainder
                np.save("White1", WC)
            else:
                print("not yet ready")
                stop
                AA = MakeAA4(WRdata)
                np.save("AA4", AA)
                WC = MakeMuller(WRdata, DC, driftDC, VDCC, AA)
                np.save("White4", WC)
            np.save("WRZA", WRZA)
            plt.plot(wl, WC[0, :])
            plt.show()
            print("WR taken.")

        elif go[0] == "E":  # ENDING WHITE REFERENCE
            print("WHITE REFERENCE (END)")
            # Instruct user and ask for zenith angle
            WRZA = np.float(input("Put white reference! Give WR zenith angle!\n"))
            # drive goniometer to the angle
            result = lib.command_move(
                Z_id, int(WRZA * 100 + Z_pos0.Position), Z_pos0.uPosition
            )
            result = lib.command_wait_for_stop(Z_id, 10)
            # collect spectometer data
            if npols == 16:
                WRdata = TakePolSequence44(
                    P_id,
                    L_id,
                    s,
                    Pcalib,
                    Lcalib,
                    wg_pols,
                    LCClib.retardances,
                    P_pos0,
                    L_pos0,
                )

                WCE = MakeMuller(WRdata, DC, driftDC, VDCC, AA)
                np.save("White44E", WCE)
            elif npols == 3:
                WRdata = TakePolSequenceIQU(
                    P_id, s, Pcalib, wg_pols, LCClib.retardances, P_pos0
                )

                WCE = MakeStokesIQU(WRdata, DC, driftDC, VDCC, AA)
                np.save("White3E", WCE)
            elif npols == 1:
                WRdata = TakeI(s, repeats=25)
                WCE = MakeI(WRdata, DC, driftDC, VDCC) - DC_remainder
                np.save(outfile + "White1E", WCE)
                WRE = MakeRef(WC, WCE)
            else:
                print("not yet ready")
                stop
                AA = MakeAA4(WRdata)
                np.save("AA4", AA)
                WC = MakeMuller(WRdata, DC, driftDC, VDCC, AA)
                np.save("White4", WC)
            np.save("WRZAE", WRZA)
            plt.plot(wl, WCE[0, :])
            plt.show()
            plt.plot(wl, WRE[0, :])
            plt.show()
            print("WR taken.")

        elif go[0] == "G":  # GO TO ZENITH ANGLE
            print("GO. DRIVE SENSOR ZENITH")
            # Ask for zenith angle
            ZA = np.float(input("Give zenith angle!\n"))
            # drive goniometer to the angle
            result = lib.command_move(
                Z_id, int(ZA * 100 + Z_pos0.Position), Z_pos0.uPosition
            )
            result = lib.command_wait_for_stop(Z_id, 10)

        # elif (go[0]=='A'): # TAKE SINGLE SPECTRUM AND PLOT A REFLECTANCE SPECTRUM ?????
        #      print('Continuous mode.')

        #      header,spectrum=ReadASD(s)

        #      for i in range(1):
        #          plt.plot(wl,(spectrum[:,i]-DC)/WC[0,0,:])#+VDCC+(driftM-driftDC)#/WC[0,:])
        #      plt.ylim(-0.1,1.0)
        #      plt.show()

        elif go[0] == "V":  # TAKE POLARIZATION DATA AND VIEW IT
            try:
                # takes just one sequence in current position
                if npols == 1:
                    Vdata = TakeI(s)
                    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(8, 8))
                    VI = MakeI(Vdata, DC, driftDC, VDCC) - DC_remainder
                    ax3.plot(wl, Vdata[0][2])
                    ax3.plot(wl, VI[0, :])
                    RV = MakeRef(VI, WC)
                    ax4.plot(wl, RV[0, :])
                    ax4.plot(wl, RV[0, :] * 10)
                    ax4.plot(wl, RV[0, :] * 100)
                    ax4.set_ylim(0.0, 10.0)
                    ax1.plot(wl, DC)
                    ax2.plot(wl, WC[0, :])
                    plt.savefig("GonioViews.png")
                    plt.show()

                else:
                    Bdata = TakePolSequenceIQU(
                        P_id, s, Pcalib, wg_pols, LCClib.retardances, P_pos0
                    )
                    AA3 = MakeAA3(Bdata)
                    d0 = MakeStokesIQU(Bdata, DC, driftDC, VDCC, AA3)

                    plt.plot(wl, d0[0, :])
                    plt.plot(wl, d0[1, :])
                    plt.plot(wl, d0[2, :])
                    # plt.plot(wl,d0[3,:])
                    plt.ylabel("raw number")
                    plt.show()
                    r0 = MakeRef(d0, WC)
                    plt.plot(wl, r0[0, :])
                    plt.plot(wl, r0[1, :])
                    plt.plot(wl, r0[2, :])
                    # plt.plot(wl,r0[3,:])
                    plt.ylim(-0.1, 1.1)
                    plt.ylabel("reflectance factors I,Q,U")
                    plt.show()
                    plt.plot(wl, r0[1, :] / r0[0, :])
                    plt.plot(wl, r0[2, :] / r0[0, :])
                    # plt.plot(wl,r0[3,:])
                    plt.ylim(-0.5, 1.0)
                    plt.ylabel("degree of polarisation")
                    plt.show()
            except:
                print("Failed")

        elif go == "I":  # SHOW VNIR INFO
            Vwl1, Vwl2, VDCC = VNIRinfo(s)
            print(Vwl1, Vwl2, VDCC)

        elif go == "P":  # PLOT DATA
            plottaile(wl, data)

        elif go == "Z":  # DRIVE ALL MOTORS TO ZERO POSITION
            # move erevrything to zero
            result = lib.command_move(A_id, int(A_pos0.Position), A_pos0.uPosition)
            result = lib.command_move(Z_id, int(Z_pos0.Position), Z_pos0.uPosition)
            if Brot:
                result = lib.command_move(B_id, int(B_pos0.Position), B_pos0.uPosition)
            if npols > 1:
                result = lib.command_move(P_id, int(B_pos0.Position), B_pos0.uPosition)

        elif go == "M":  # COLLECT MEASUREMENT SEQUENCE AND SAVE IT
            print("MEASURE")
            # ask user how many spectra to repeat at each angle
            ans = input("How many spectra to average at each angle?\n")
            if len(ans) == 0:
                print("1")
                repeats = 1
            else:
                repeats = int(ans)

            # take measurement at each angle defined in Angles.txt
            for sz, sa00, ze, az, be, wwa, wwb in angles:
                # Give commands to drive goniometer motors to the desired angle
                print("moving to:", ze, az, be, "/", NA)
                Z_pos2 = Z_pos1
                Z_pos2.Position = ze
                A_pos2 = A_pos1
                A_pos2.Position = az
                if Brot:
                    B_pos2 = B_pos1
                    B_pos2.Position = be
                    result = lib.command_move(
                        B_id, int(be * 100 + B_pos0.Position), B_pos0.uPosition
                    )
                result = lib.command_move(
                    A_id, int(az * 100 + A_pos0.Position), A_pos0.uPosition
                )
                result = lib.command_move(
                    Z_id, int(ze * 100 + Z_pos0.Position), Z_pos0.uPosition
                )

                # while driving, save all data to output file
                # (Why is this done here and now, as we dont have yet new data yet?)
                with open(outfile + ".pickle", "wb") as handle:
                    pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

                # make sure spectrometer settings are set correctly, in case something is changed
                SetOpt(s, Oheader[2], Oheader[3], Oheader[4])

                # Wait for all motors to stop driving
                result = lib.command_wait_for_stop(Z_id, 10)
                result = lib.command_wait_for_stop(A_id, 10)
                result = lib.get_position_calb(Z_id, byref(Z_pos1), byref(Zcalib))
                result = lib.get_position_calb(A_id, byref(A_pos1), byref(Acalib))

                # skip collecting spectral data on this angle if it has weight of zero
                if wwb == 0.0:
                    print("Jumping one value")
                    continue

                # TEMPORARY CODE BLOCK: Warning about dark current not yet being handled properly with npols>1
                # you can delete this whole warning code block once this is fixed
                # Every row with dark current correction measurement like MakeI or Make* (except in dark current) should have DC_remainder removed/handled.
                if npols > 1:
                    raise Warning(
                        "Dark current residual is handled only in case npols==1. You really should fix this before taking any more polarized measurements!"
                    )

                # Take spectrometer measurement(s) with wanted polarizations
                if npols == 16:
                    subdata = TakePolSequence44(
                        P_id,
                        L_id,
                        s,
                        Pcalib,
                        Lcalib,
                        wg_pols,
                        LCClib.retardances,
                        P_pos0,
                        L_pos0,
                    )
                    SS = MakeMuller(subdata, DC, driftDC, VDCC, AA)
                    RR = MakeRef44(SS, WC)
                elif npols == 3:
                    subdata = TakePolSequenceIQU(
                        P_id, s, Pcalib, wg_pols, LCClib.retardances, P_pos0
                    )
                    SS = MakeStokesIQU(subdata, DC, driftDC, VDCC, AA)
                    RR = MakeRef(SS, WC)
                elif npols == 1:
                    subdata = TakeI(s, repeats=repeats)
                    SS = MakeI(subdata, DC, driftDC, VDCC) - DC_remainder
                    RR = MakeRef(SS, WC)

                # append reflectance or radiance data
                if reflectance_mode:
                    data.append((sz, sa00, ze, az, be, RR, wwa, wwb))
                else:
                    data.append((sz, sa00, ze, az, be, SS, wwa, wwb))

            result = lib.command_move(
                Z_id, int(Z_pos0.Position), Z_pos0.uPosition
            )  # at the end, move to starting position
            result = lib.command_move(
                A_id, int(A_pos0.Position), A_pos0.uPosition
            )  # at the end, move to starting position
            if Brot:
                result = lib.command_move(
                    B_id, int(B_pos0.Position), B_pos0.uPosition
                )  # at the end, move to starting position

            with open(outfile + ".pickle", "wb") as handle:
                pickle.dump(data, handle, protocol=pickle.HIGHEST_PROTOCOL)

        elif go == "Q":
            # Quit
            break

        else:
            print("Unrecognized command: " + str(go))

    except Exception as err:
        print('Performing command "' + str(go) + '" failed with error:')
        traceback.print_exc()


# %% GRACEFULL EXIT
lib.close_device(byref(cast(Z_id, POINTER(c_int))))
try:
    lib.close_device(byref(cast(P_id, POINTER(c_int))))
except:
    pass
lib.close_device(byref(cast(A_id, POINTER(c_int))))
try:
    lib.close_device(byref(cast(L_id, POINTER(c_int))))
except:
    pass
if Brot:
    lib.close_device(byref(cast(B_id, POINTER(c_int))))

try:
    np.savetxt(outfile + "_.txt", np.ravel(data))
except:
    print("savetxt did not work!")
# jout=open(outfile+'.json','w')
# json.dump(data,jout)
# jout.close()
out = open(outfile + ".txt", "w")
for d in data:
    # for g in d:
    out.write(str(d[:5]))
    out.write(str(np.ravel(d[5])) + "\n")
out.close()
# np.save(outfile+'.npy',data)
