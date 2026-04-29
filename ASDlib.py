# -*- coding: utf-8 -*-
"""
Created on Wed Apr  4 13:53:30 2018

@author: jouni
"""
# Echo client program
import numpy as np
import scipy.linalg
import scipy
import time
from struct import unpack
from LCClib import NRets, LCCwl,RetStep#,SpectralRetardances

Nwl=2151
Vwl1=350
Vwl2=1000
#VDCC=1
wls=np.array(Vwl1+np.arange(Nwl))

def recvall(s,N):
    ln=0
    data=[]
    while (ln<N):
        #print(ln,N)
        d=s.recv(N-ln)
        #print(d)
        data.append(d)
        ln+=len(d)
    return b''.join(data)    



def Optimize(s):
    s.sendall(b'OPT,7')
    data = s.recv(32)
    if (len(data)<28):
        data += s.recv(32)
        print(len(data))
    header,errbyte,itime,gain1,gain2,offset1,offset2=unpack('>iiiiiii', data[:28])
    if header !=100:
        print('PROBLEMS IN OPTIMISATION')
        print(header,errbyte,itime,gain1,gain2,offset1,offset2)
    offset=[offset1,offset2]
    gain=[gain1,gain2]
    if (itime>5):  ### this may be suspicious, maybe not receiving well????
        print('WARNING: maybe too low signal!')
        itime=5
        com=('IC,2,0,'+str(itime)).encode('ASCII')
        print(com)
        s.sendall(com)
        data=recvall(s,20)
    return header,errbyte,itime,gain,offset

def SetOpt(s,itime,gain,offset):
#    print(itime,gain,offset)
    com=('IC,2,0,'+str(itime)).encode('ASCII')
#    print(com)
    s.sendall(com)
    dummydata = s.recv(20)
    com=('IC,1,2,'+str(offset[1])).encode('ASCII')
    s.sendall(com)
    dummydata = s.recv(20)
    com=('IC,0,2,'+str(offset[0])).encode('ASCII')
    s.sendall(com)
    dummydata = s.recv(20)
    com=('IC,1,1,'+str(gain[1])).encode('ASCII')
    s.sendall(com)
    dummydata = s.recv(20)
    com=('IC,0,1,'+str(gain[0])).encode('ASCII')
    s.sendall(com)
    dummydata = s.recv(20)
    
    
def DarkCurrent(s,itime):
      input('Close cap for Dark Current!')
  #    Time=0.017*2**itime
  #    Scount=int(2.5/Time)
  #    print(itime,Time,Scount)
  #    header,DC=ReadASD1(s,Scount)
      header,DC=ReadASD(s)
      DriftDC=header[22]
      print('DC done. Open cap!',DriftDC)
     
      return DC,DriftDC
  
def DarkCurrent2(s,Dcount=10):
      input('Close cap for Dark Current!')
 
      header,DC=ReadASD1(s,Dcount)      
      DriftDC=header[22]
      print('DC done. Open cap!',DriftDC,Dcount)
     
      return DC,DriftDC
    
def Version(s):    
    s.sendall(b'V')
    data = recvall(s,50)
    name=str(30)
    header,errbyte,name,value,type=unpack('>ii30sdi',data[:50])
    return header,errbyte,name,value,type

def VNIRinfo(s):    
    s.sendall(b'INIT,0,VStartingWavelength')
    data = recvall(s,50)
    name=str(30)
    header,errbyte,name,Vwl1,count=unpack('>ii30sdi',data[:50])
    print(header,errbyte,name,Vwl1,count)

    s.sendall(b'INIT,0,VDarkCurrentCorrection')
    data = recvall(s,50) #s.recv(64)
    name=str(30)
    header,errbyte,name,VDCC,count=unpack('>ii30sdi',data[:50])

    print(header,errbyte,name,'VDCC:',VDCC,count)

    s.sendall(b'INIT,0,VEndingWavelength')
    data = recvall(s,50) #s.recv(64)
    name=str(30)
    header,errbyte,name,Vwl2,count=unpack('>ii30sdi',data[:50])
    print(header,errbyte,name,Vwl2,count)
    return Vwl1,Vwl2,VDCC



def ReadASD1x(s,count): # testing another sequence
    spectrum=np.zeros((Nwl,count))
    for i in range(count):
        s.sendall(b'A,1,1')
        print(i)
    for i in range(count):  
        datax1=recvall(s,Nwl*4+256)
        header=unpack('>64i', datax1[:256])    
        spectrum[:,i]=np.array(unpack('>2151f', datax1[256:256+8604])) 
        print(i)
    return header,spectrum    
    
def ReadASD1(s,count):
    t0=time.time()
    
    com=('A,1,'+str(count)).encode('ASCII')
    #print(com)
    s.sendall(com)
    l0=0
    datd=[]
#    time.sleep(0.1) # here could do something useful
    #print('S1:',time.process_time(),time.time()-t0,count)
#   t0=time.time() 
    while (l0<Nwl*4+256):
        data = s.recv(Nwl*4+256-l0)
#        print('Sw1:',l0,time.process_time(),time.time()-t0)
        #t0=time.time()
        ln=len(data)
        datd.append(data)
        l0+=ln
#        print('Sw2:',l0,ln,time.process_time(),time.time()-t0)
#        t0=time.time()
#    print('S2:',time.process_time(),time.time()-t0)
#    t0=time.time()
    datc=b''.join(datd)        
    header=unpack('>64i', datc[:256])    
    spectrum=np.array(unpack('>2151f', datc[256:256+8604]))
    #print('S3:',time.process_time(),time.time()-t0,l0,ln)
#    t0=time.time()    
    return header,spectrum

def ReadASD(s): 
    s.sendall(b'A')
    datc=recvall(s,Nwl*4+256)
#    l0=0
#    datd=[]
#    while (l0<Nwl*4+256):
#        data = s.recv(Nwl*4+256-l0)
#        ln=len(data)
#        datd.append(data)
#        l0+=ln
#    datc=b''.join(datd)        
    header=unpack('>64i', datc[:256])    
    spectrum=np.array(unpack('>2151f', datc[256:256+8604]))
    return header,spectrum

def NOTReadASD0(s,count):
#    print('A')
    s.sendall(b'A,1,1')
    data = s.recv(256)
    if (len(data)<256):
        print(len(data))
        data += s.recv(256-len(data))
        print('ReadASD header again:',len(data))
    header=unpack('>64i', data[:256])
    l0=0
#    dat=b''
    datb=bytearray(4*Nwl)
    for i in range(999):
        data = s.recv(4096)#min(4096,8604-l0))
#        dat+=data
        ln=len(data)
        datb[l0:l0+ln]=data
        l0+=ln
#        print(i,ln,l0,len(datb))
        if (l0>=Nwl*4):
            break

    spectrum=np.array(unpack('>2151f', datb[:4*Nwl]))
    return header,spectrum

def Restore(s):
    print('R')
    s.sendall(b'RESTORE,1')
    nb=0
    
    for i in range(333):   
#        print(i,nb)
        data = s.recv(1024)
        nb+=len(data)
        if (nb>=7616):
            break
    print('RR.')

class datastruct:
    sunzen=0.0
    sunaz=0.0
    obszen=0.0
    obsaz=0.0
    spectrum=np.zeros(Nwl)

#
#def RecordSpectrum1(sz,sa,oz,oa,so):
#    header,spectrum=ReadASD(so,1)
#    data=datastruct()
#    data.sunzen=sz
#    data.sunaz=sa
#    data.obszen=oz
#    data.obsaz=oa
#    data.spectrum=(spectrum-DC)/(WR-DC)
#    return data
#
#def RecordSpectrum(so):
#    header,spectrum=ReadASD(so,1)
#    return spectrum

def MullerRetarder(delta,theta):
    A=np.zeros((4,4))
    A[0,0]=1.0
    A[1,1:]=[np.cos(2*theta)**2+np.sin(2*theta)**2*np.cos(delta),np.cos(2*theta)*np.sin(2*theta)*(1-np.cos(delta)),np.sin(2*theta)*np.sin(delta)]
    A[2,1:]=[np.cos(2*theta)*np.sin(2*theta)*(1-np.cos(delta)),np.cos(2*theta)**2*np.cos(delta)+np.sin(2*theta)**2,-np.cos(2*theta)*np.sin(delta)]
    A[3,1:]=[-np.sin(2*theta)*np.sin(delta),np.cos(2*theta)*np.sin(delta),np.cos(delta)]
    return A

def MullerRetarder0(delta):#theta=0
    A=np.zeros((4,4))
    A[0,:]=[1.0,0.0,0.0,0.0]
    A[1,:]=[0.0,1.0,0.0,0.0]
    A[2,:]=[0.0,0.0,np.cos(delta),-np.sin(delta)]
    A[3,:]=[0.0,0.0,np.sin(delta), np.cos(delta)]
    return A


def MullerRot(delta):#theta=0
    A=np.zeros((4,4))
    A[0,:]=[1.0,0.0,0.0,0.0]
    A[1,:]=[0.0, np.cos(delta),np.sin(delta),0.0]
    A[2,:]=[0.0,-np.sin(delta),np.cos(delta),0.0]
    A[3,:]=[0.0,0.0,0.0,1.0]
    return A


deg=np.pi/180.0
#thetaMWP=45.0  # or whatever it is, must be known

deltaLCC=np.zeros((Nwl,NRets))  #normally < 2pi
#deltaMWP=np.zeros(Nwl)+np.pi/2  #can be very big

def IQUVsincos(x,I,Q,U,V):
    return I+Q*np.cos(2*theta)+U*np.cos(delta)*np.sin(2*theta)+V*np.sin(delta)*np.sin(2*theta)




def CalAA(caldata,rundata,DC,driftDC,VDCC):  # NOT USED; NOT NEEDED, WRONG
    i=0
    
#    AA=np.zeros((Nwl,len(caldata),4))
    II=np.zeros(Nwl)
    Q1=np.zeros(Nwl)
    Q2=np.zeros(Nwl)
    iLCC=0
    iWG=0
    ret0=0
    wga0=0
    for dat in caldata:
        ret,wga,spectrum,driftM=dat
        if (ret>ret0):
            iLCC+=1
            ret0=ret
        if (wga>wga0):
            iWG+=1
            wga0=wga    
            iLCC=0
            ret0=0
#        deltaLCC[:,iLCC]=ret*2*np.pi/LCCwl
        for iwl in range(Nwl):
            if (iwl<Vwl2-Vwl1):
                Meas[iwl,iWG,iLCC]=spectrum[iwl]-DC[iwl]+VDCC+driftM-driftDC
            else:
                Meas[iwl,iWG,iLCC]=spectrum[iwl]  
            i+=1    
            II[i]+=Meas
            Q1=np.max(Q1,Meas)
            Q2=np.min(Q2,Meas)
            
    II=2*II/len(caldata)        
    QQ=np.min(Q2-II,-Q1+II)          # positive or negative???
#    cosdelta[iwl,iLCC]=(Meas[iwl,0,iLCC]-II)/QQ
#   sindelta=np.sqrt(1.0-cosdelta**2)
#    sineps=(Meas[iwl,1,iLCC]-II)/(QQ*sindelta)
    for dat in caldata:
        ret,wga,spectrum,driftM=dat
        iLCC=np.int(ret/RetStep)
        deltaLCC[:,iLCC]=SpectralRetardances(ret,wls)*2*np.pi/LCCwl
       
        for iwl in range(Nwl):
            Q,a,b,c=fscipy.optimize.curve_fit(Qsincos,Meas[iwl,iWG,:],deltaLCC[iwl,:])
            i+=1    
            if (wga==0.0):
                cosdelta[iwl,iLCC]=(2*Meas[iwl,iWG,iLCC]-II)/QQ
            elif (wga==45.0):   
                sineps[iwl]=(2*Meas[iwl,iWG,iLCC]-II)/(QQ*sindelta)
            elif (wga==90.0):
                cosdelta[iwl,iLCC]-=(2*Meas[iwl,iWG,iLCC]-II)/QQ
            elif (wga==135.0):   
                sineps[iwl]-=(2*Meas[iwl,iWG,iLCC]-II)/(QQ*sindelta) 
    deltaLCC=np.acos2(cosdelta,sindelta)
    deltaMWP=np.acos2(coseps,sineps)
    #return deltaLCC,deltaMWP
        
def MakeAA(subdata):     
    AA=np.zeros((Nwl,len(subdata),4))  
    i=0
    for dat in subdata:
        ret,wga,spectrum,driftM=dat  
        print(ret,wga,ret/LCCwl*2*np.pi)
        #deltaLCC0=np.load('RetardanceTable.npy')*2*np.pi/wls
        #deltaLCC0=SpectralRetardances(ret,wls)*2*np.pi/wls
        deltaLCC0=ret*2*np.pi/wls*(LCCwl/wls)**0.84  # just a very bad guess
        M1=np.array([1.0,np.cos(2*wga*deg),np.sin(2*wga*deg),0.0])
        for iwl in range(Nwl):  
            M2=MullerRetarder0(deltaLCC0[iwl])#,0.0)                     
            AA[iwl,i,:]=np.matmul(M1,M2)
        i+=1
    return AA

def MakeAA44(subdata):     
    AA44=np.zeros((Nwl,len(subdata),4*4))  
    i=0
    for dat in subdata:
        ret,wga,lsa,spectrum,driftM=dat  
        print(ret,wga,lsa,ret/LCCwl*2*np.pi)
        #deltaLCC0=np.load('RetardanceTable.npy')*2*np.pi/wls
        #deltaLCC0=SpectralRetardances(ret,wls)*2*np.pi/wls
        deltaLCC0=ret*2*np.pi/wls*(LCCwl/wls)**0.84  # just a very bad guess
        M1=np.array([1.0,np.cos(2*wga*deg),np.sin(2*wga*deg),0.0])
        M3=np.array([1.0,np.cos(2*lsa*deg),np.sin(2*lsa*deg),0.0])
        for iwl in range(Nwl):  
            M2=MullerRetarder0(deltaLCC0[iwl])#,0.0)                     
            AA44[iwl,i,:,:]=np.matmul(np.matmul(M1,M2),M3)
        i+=1
    return AA44

def MakeAA3(subdata):     
    AA3=np.zeros((Nwl,len(subdata),3))  
    i=0
    for dat in subdata:
        ret,wga,spectrum,driftM=dat  
        #print(ret)       
        M1=0.5*np.array([1.0,np.cos(2*wga*deg),np.sin(2*wga*deg)])
        for iwl in range(Nwl):                              
            AA3[iwl,i,:]=M1
        i+=1
    return AA3

def MakeAA4(subdata):     # DUPLICATE??
    AA4=np.zeros((Nwl,len(subdata),4))  
    i=0
    for dat in subdata:
        ret,wga,spectrum,driftM=dat  
        #print(ret)       
        M1=0.5*np.array([1.0,np.cos(2*wga*deg),np.sin(2*wga*deg),0.0])
        deltaLCC0=ret*2*np.pi/wls*(LCCwl/wls)**0.84 
        for iwl in range(Nwl):  
            M2=MullerRetarder0(deltaLCC0[iwl])               
            AA4[iwl,i,:]=np.matmul(M1,M2)
        i+=1
    return AA4

#def MakeAA3(subdata):     
#    AA=np.zeros((Nwl,len(subdata),4))
#    for iwl in range(Nwl):
#        i=0
#        for dat in subdata:
#            ret,wga,spectrum,driftM=dat
#            M1=np.array([1.0,np.cos(wga*deg),np.sin(wga*deg),0.0])
#            M2=MullerRetarder(deltaLCC[iwl,int(ret/100)]*deg,0.0)
#            M3=MullerRetarder(deltaMWP[iwl]*deg,thetaMWP*deg)
#           
#            AA[iwl,i,:]=np.matmul(M1,np.matmul(M2,M3))
#            i+=1
#    return AA

def MakeMuller(subdata,DC,driftDC,VDCC,AA):
    
    BB=np.zeros((len(subdata)))
    MM=np.zeros((4,4,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,lpol,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw<=Vwl2-Vwl1):
                BB[i]=spectrum[iw]-DC[iw]+VDCC-(driftM-driftDC)
            else:
                BB[i]=spectrum[iw]  
            i+=1    
        XX=scipy.linalg.lstsq(AA[iw,:,:],BB)
        #print('lstsq:',XX[1:])
        MM[:,:,iw]=XX[0][:].reshape((4,4))
    return MM

def MakeStokes(subdata,DC,driftDC,VDCC,AA,Vwl1=350,Vwl2=1000):
    
    BB=np.zeros((len(subdata)))
    IQUV=np.zeros((4,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw<=Vwl2-Vwl1):
                BB[i]=spectrum[iw]-DC[iw]+VDCC-(driftM-driftDC)
            else:
                BB[i]=spectrum[iw]  
            BB[i]=np.maximum(0.0,BB[i])    # NO negative values
            i+=1    
        try:
            XX=scipy.linalg.lstsq(AA[iw,:,:],BB)
        except scipy.linalg.LinAlgError:
            print('MakeStokes LinAlgError ')
            XX=[np.zeros(4)]
        #print('lstsq:',XX[1:])
        IQUV[:,iw]=XX[0][:]
    return IQUV


def MakeStokesIQU(subdata,DC,driftDC,VDCC,AA3):
    #STOP 
    BB=np.zeros((len(subdata)))
    IQU=np.zeros((3,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw<=Vwl2-Vwl1):
                BB[i]=spectrum[iw]-DC[iw]+VDCC+(driftM-driftDC)  
            else:
                BB[i]=spectrum[iw]  
            BB[i]=np.maximum(0.0,BB[i])    # NO negative values 
            i+=1    
        try:  # probably this fit allows arbitrary polarisation angles and fits then for Stokes
            XX=scipy.linalg.lstsq(AA3[iw,:,:3],BB)
            IQU[:,iw]=XX[0][:]
        except scipy.linalg.LinAlgError:
            print('MakeStokesIQUMatrixError not converging',iw)
            IQU[:,iw]=0.0    
        #print('lstsq:',XX[1:])

    return IQU

def MakeStokesIQUV(subdata,DC,driftDC,VDCC,AA4): # DUPLICXATE???
    #STOP 
    BB=np.zeros((len(subdata)))
    IQUV=np.zeros((4,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw<=Vwl2-Vwl1):
                BB[i]=spectrum[iw]-DC[iw]+VDCC+(driftM-driftDC)  
            else:
                BB[i]=spectrum[iw]  
            BB[i]=np.maximum(0.0,BB[i])    # NO negative values 
            i+=1    
        try:  # probably this fit allows arbitrary polarisation angles and fits then for Stokes
            XX=scipy.linalg.lstsq(AA4[iw,:,:3],BB)
            IQUV[:,iw]=XX[0][:]
        except scipy.linalg.LinAlgError:
            print('MakeStokesIQUV MatrixError not converging',iw)
            IQUV[:,iw]=0.0    
        #print('lstsq:',XX[1:])

    return IQUV

def MakeI(subdata,DC,driftDC,VDCC,Vwl1=350,Vwl2=1000):
    
    BB=np.zeros((len(subdata)))
    I=np.zeros((1,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw <= (Vwl2-Vwl1)):
                BB[i]=spectrum[iw]-DC[iw]+VDCC+(driftM-driftDC)
            else:
                BB[i]=spectrum[iw]  
            BB[i]=np.maximum(0.0,BB[i])    # NO negative values
            i+=1    
        I[:,iw]=np.sum(BB)/np.size(BB)


    return I

def MakeStokesIQUminus(subdata,DC,driftDC,VDCC,AA3):
    
    BB=np.zeros((len(subdata)))
    IQU=np.zeros((3,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw<=Vwl2-Vwl1):
                BB[i]=spectrum[iw]-DC[iw]+VDCC-(driftM-driftDC)  # KOKEILU, JOS SITTEKI MIINUS?
            else:
                BB[i]=spectrum[iw]  
            i+=1 
        BB=np.maximum(0.0,BB)    # NO negative values
        try:  # probably this fit allows arbitrary polarisation angles and fits then for Stokes
            XX=scipy.linalg.lstsq(AA3[iw,:,:3],BB)
            IQU[:,iw]=XX[0][:]
        except scipy.linalg.LinAlgError:
            print('MakeStokesIQUMatrixError not converging',iw)
            IQU[:,iw]=0.0    
        #print('lstsq:',XX[1:])

    return IQU

def MakeIminus(subdata,DC,driftDC,VDCC,Vwl1=350,Vwl2=1000):
    
    BB=np.zeros((len(subdata)))
    I=np.zeros((1,Nwl))
    for iw in range(Nwl):  # not yet very optimal order
        i=0
        for dat in subdata:
            ret,wga,spectrum,driftM=dat
            if iw==0:
                print(VDCC,driftM,driftDC)
            if (iw <= (Vwl2-Vwl1)):
                BB[i]=spectrum[iw]-DC[iw]+VDCC-(driftM-driftDC)
            else:
                BB[i]=spectrum[iw]  
            i+=1    
        I[:,iw]=np.sum(BB)/np.size(BB)


    return I


def MakeRef(IQUV,WR):
    Ref=IQUV*0.0
    for iw in range(Nwl):  
        Ref[:,iw]=IQUV[:,iw]/WR[0,iw]
    return Ref    

def MakeRef44(MM,WR):
    Ref=MM*0.0
    for iw in range(Nwl):  
        Ref[:,:,iw]=MM[:,:,iw]/WR[0,0,iw]
    return Ref    
