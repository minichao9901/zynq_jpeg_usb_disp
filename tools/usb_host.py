"""USB Display WinUSB diagnostic transport, independent of the IDD driver."""
import argparse
import ctypes.util
import json
from pathlib import Path
import struct
import time
import usb.core
import usb.util
import usb.backend.libusb1

ROOT = Path(__file__).resolve().parents[1]
KEYS = 'magic version configured resets width height panel usb_bytes chunks frames bad unsupported display_errors last_id last_type last_x last_y last_width last_height last_length front vdma frame_fnv ep1_frames ep2_frames rx_timeouts setup stalls speed stage session resync_bytes'.split()


def connect(dll=None):
    candidates = [dll, ctypes.util.find_library('usb-1.0'),
        str(ROOT/'tools/libusb-1.0.dll'),
        'E:/zynqlinkPRO/prebuilt/golden/host/openocd/libusb-1.0.dll']
    backend = None
    for path in candidates:
        if path:
            backend = usb.backend.libusb1.get_backend(find_library=lambda _: str(path))
            if backend:
                break
    if backend is None:
        raise RuntimeError('libusb-1.0.dll not found; use --dll')
    matches = usb.core.find(find_all=True,idVendor=0x303a, idProduct=0x2986, backend=backend)
    dev = None
    for candidate in matches:
        if candidate.serial_number == 'ZYNQ-UDISP-RGB-001':
            dev = candidate
            break
    if dev is None:
        raise RuntimeError('Zynq USB display 303A:2986 not found')
    usb.util.claim_interface(dev, 1)
    return dev


def stats(dev):
    data = bytes(dev.ctrl_transfer(0xc1,0x30,0,1,128,timeout=3000))
    if len(data)!=128:
        raise RuntimeError('Short diagnostic snapshot')
    result = dict(zip(KEYS, struct.unpack('<32I', data)))
    if result['magic']!=0x31504455:
        raise RuntimeError('Diagnostic ABI mismatch')
    return result


def frame(payload, w, h, x=0, y=0, frame_id=0, mode=0):
    if len(payload)>0x3fffff:
        raise ValueError('Payload exceeds wire length field')
    return struct.pack('<HBBHHHHI',0,mode,0,x,y,w,h,(len(payload)<<10)|(frame_id&1023))+payload


def fnv(data):
    result = 2166136261
    for v in data:
        result = ((result ^ v)*16777619)&0xffffffff
    return result


def rgb_to_bgr(payload):
    out = bytearray(len(payload)//2*3)
    for i,(c,) in enumerate(struct.iter_unpack('<H',payload)):
        r,g,b=c>>11,(c>>5)&63,c&31
        out[3*i:3*i+3] = bytes(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)))
    return out


def pattern(w,h,phase=0):
    colors=[0xf800,0x07e0,0x001f,0xffff,0xffe0,0x07ff,0xf81f,0]
    return b''.join(struct.pack('<H',colors[((x*8//w)+phase)%8]) for y in range(h) for x in range(w))


def wait_for(dev, key, target, timeout=4):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        s=stats(dev)
        if s[key]>=target:
            return s
        time.sleep(.01)
    raise RuntimeError(f'Timed out waiting for {key}>={target}: {s}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['stats','colorbars','test'])
    ap.add_argument('--dll')
    ap.add_argument('--out',type=Path,default=ROOT/'build/usb-test.json')
    args = ap.parse_args()
    dev = connect(args.dll)
    try:
        before = stats(dev)
        if args.command=='stats':
            print(json.dumps(before,indent=2)); return
        w,h=before['width'],before['height']
        payload=pattern(w,h)
        target=before['ep2_frames']+1
        dev.write(2,frame(payload,w,h,frame_id=1),timeout=5000)
        after=wait_for(dev,'ep2_frames',target)
        report={'before':before,'after':after,'expected_fnv':fnv(rgb_to_bgr(payload))}
        if args.command=='test':
            assert after['frame_fnv']==report['expected_fnv'], report
            assert after['display_errors']==0, after
            report['passed']=True
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        usb.util.dispose_resources(dev)


if __name__=='__main__':
    main()
