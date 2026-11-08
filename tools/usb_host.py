"""USB Display WinUSB diagnostic transport, independent of the IDD driver."""
import argparse
import ctypes.util
import json
import os
from pathlib import Path
import struct
import time
import usb.core
import usb.util
import usb.backend.libusb1

ROOT = Path(__file__).resolve().parents[1]
KEYS = 'magic version configured resets width height panel usb_bytes chunks frames bad unsupported display_errors last_id last_type last_x last_y last_width last_height last_length front vdma frame_fnv ep1_frames ep2_frames rx_timeouts setup stalls speed stage session resync_bytes'.split()


def connect(dll=None):
    dll = dll or os.environ.get('ZYNQ_LIBUSB_DLL')
    if dll:
        path = Path(dll).expanduser().resolve(strict=True)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: str(path))
    else:
        try:
            import libusb_package
        except ImportError:
            libusb_package = None
        backend = libusb_package.get_libusb1_backend() if libusb_package else None
        if backend is None:
            backend = usb.backend.libusb1.get_backend(find_library=ctypes.util.find_library)
    if backend is None:
        raise RuntimeError('libusb unavailable; install requirements.txt or set ZYNQ_LIBUSB_DLL')
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


def firmware_info(dev):
    raw=bytes(dev.ctrl_transfer(0xc1,0x34,0,1,36,timeout=3000))
    if len(raw)!=36: raise RuntimeError('Short firmware identity reply')
    result=dict(zip('magic version default_encoding driver_fps_token profile_flags build_id features width height'.split(),struct.unpack('<9I',raw)))
    if result['magic']!=0x32445055: raise RuntimeError('Invalid firmware identity')
    return result


DISPLAY_KEYS='magic version buffers frame_events programmed latest ready drawing retired_mask decoded published replaced vdma frame_event_age_ms halted_seen error_seen no_buffer published_seq latest_seq guard_events settled control quarantined_mask'.split()


def display_status(dev):
    raw=bytes(dev.ctrl_transfer(0xc1,0x35,0,1,128,timeout=3000))
    result=dict(zip(DISPLAY_KEYS,struct.unpack('<32I',raw)))
    if result['magic']!=0x31505344: raise RuntimeError('Invalid display telemetry')
    return result


def wait_display(dev,timeout=2):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        status=display_status(dev)
        if status['settled'] and status['published_seq']==status['latest_seq']:
            return stats(dev)
        time.sleep(.005)
    raise RuntimeError('Display did not settle: '+str(status))


PROFILE_KEYS='version flags frames convert_us jpeg_us flush_us wait_us fnv_us copy_us frame_us last_us max_us jpeg_errors neon sink_frames hz jpeg_rtl jpeg_hw_status jpeg_hw_cycles'.split()


def profile(dev):
    data=bytes(dev.ctrl_transfer(0xc1,0x31,0,1,128,timeout=3000))
    return dict(zip(PROFILE_KEYS,struct.unpack('<32I',data)))


def set_profile(dev,flags):
    dev.ctrl_transfer(0x41,0x33,flags,1,b'',timeout=3000)


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
    diagnostics = {'stats': stats, 'info': firmware_info, 'display': display_status, 'profile': profile}
    ap.add_argument('command', choices=[*diagnostics,'colorbars','test'])
    ap.add_argument('--dll', help='override the bundled/system libusb with a specific DLL')
    ap.add_argument('--out',type=Path,default=ROOT/'build/usb-test.json')
    args = ap.parse_args()
    dev = connect(args.dll)
    restore_flags = None
    try:
        if args.command in diagnostics:
            print(json.dumps(diagnostics[args.command](dev),indent=2))
            return
        if args.command=='test':
            before = stats(dev)
            time.sleep(.2)
            if stats(dev)['ep1_frames'] != before['ep1_frames']:
                raise RuntimeError('Pause MI_00 or download with --no-display before testing')
            restore_flags = profile(dev)['flags']
            set_profile(dev,0)
        before = stats(dev)
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
        try:
            if restore_flags is not None:
                set_profile(dev,restore_flags)
        finally:
            usb.util.dispose_resources(dev)


if __name__=='__main__':
    main()
