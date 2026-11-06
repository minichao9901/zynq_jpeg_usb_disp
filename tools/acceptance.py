"""Board acceptance over MI_01. Disable IDD MI_00 for deterministic image checks."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import struct
import subprocess
import time
from usb_host import connect, stats, frame, pattern, fnv, rgb_to_bgr, wait_for, ROOT
import usb.util


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/acceptance')
    ap.add_argument('--frames',type=int,default=300)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'tests':[]}
    dev=connect()
    def save():
        (args.out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def send(payload,w,h,x=0,y=0,mode=0,parts=None):
        start=stats(dev)
        packet=frame(payload,w,h,x,y,len(report['tests'])+1,mode)
        if parts:
            at=0
            for size in parts:
                dev.write(2,packet[at:at+size],timeout=5000); at+=size
            if at<len(packet): dev.write(2,packet[at:],timeout=5000)
        else:
            dev.write(2,packet,timeout=5000)
        key='unsupported' if mode else 'ep2_frames'
        return wait_for(dev,key,start[key]+1)
    def check(name,s,expected):
        expected_fnv=fnv(expected)
        assert s['frame_fnv']==expected_fnv, (name,s,expected_fnv)
        assert s['display_errors']==0, s
        report['tests'].append({'name':name,'frame_fnv':s['frame_fnv'],'stats':s})
        save()
    try:
        baseline=stats(dev); time.sleep(.3)
        assert stats(dev)['ep1_frames']==baseline['ep1_frames'], 'Disable IDD MI_00 before this test'
        report['initial']=baseline
        w,h=baseline['width'],baseline['height']
        payload=pattern(w,h)
        expected=rgb_to_bgr(payload)
        check('full RGB565 color bars',send(payload,w,h),expected)
        payload=pattern(w,h,1)
        expected=rgb_to_bgr(payload)
        check('fragmented header and payload, short USB transfers',
              send(payload,w,h,parts=[1,2,4,8,1,31,512,1000,4096,16384,65536]),expected)
        # Region update must preserve the rest of the preceding image.
        x,y,rw,rh=13,17,123,79
        patch=struct.pack('<H',0x1234)*(rw*rh)
        bgr=rgb_to_bgr(patch)
        for row in range(rh):
            expected[((y+row)*w+x)*3:((y+row)*w+x+rw)*3]=bgr[row*rw*3:(row+1)*rw*3]
        check('unaligned rectangle / BGR888 row stride',send(patch,rw,rh,x,y),expected)
        # Multiple frames in one host transfer exercise stream boundaries.
        start=stats(dev)
        p1=pattern(w,h,2); p2=pattern(w,h,3)
        dev.write(2,frame(p1,w,h,frame_id=900)+frame(p2,w,h,frame_id=901),timeout=5000)
        expected=rgb_to_bgr(p2)
        check('two concatenated frames',wait_for(dev,'ep2_frames',start['ep2_frames']+2),expected)
        # A rejected RGB rectangle is drained without overwriting scanout.
        start=stats(dev)
        dev.write(2,frame(b'\x00\x00'*16,4,4,w-1,h-1),timeout=3000)
        s=wait_for(dev,'bad',start['bad']+1)
        check('reject out-of-bounds rectangle',s,expected)
        assert s['ep2_frames']==start['ep2_frames']
        s=send(b'\xff\xd8\xff\xd9',w,h,mode=3)
        check('reject unsupported JPEG, retain displayed image',s,expected)
        start=stats(dev)
        dev.write(2,frame(b'\x00\x00'*16,4,4)[:7],timeout=3000)
        wait_for(dev,'rx_timeouts',start['rx_timeouts']+1,timeout=3)
        payload=pattern(w,h,4); expected=rgb_to_bgr(payload)
        check('truncated-header timeout and next-frame recovery',send(payload,w,h),expected)
        start=stats(dev)
        dev.write(2,b'\x5a'*2049,timeout=3000)
        payload=pattern(w,h,5); expected=rgb_to_bgr(payload)
        check('recover a new frame after mid-payload garbage',send(payload,w,h),expected)
        assert stats(dev)['resync_bytes']>=start['resync_bytes']+2049
        # Sustained paced transport, measured after all frames reach scanout.
        packet=bytearray(frame(payload,w,h))
        start=stats(dev); t0=time.monotonic()
        for i in range(args.frames):
            struct.pack_into('<I',packet,12,(len(payload)<<10)|(i&1023))
            dev.write(2,packet,timeout=5000)
            delay=(i+1)/30-(time.monotonic()-t0)
            if delay>0: time.sleep(delay)
        s=wait_for(dev,'ep2_frames',start['ep2_frames']+args.frames,timeout=10)
        elapsed=time.monotonic()-t0
        check('sustained 800x480 RGB565, paced at 30 fps',s,expected)
        assert s['bad']==start['bad'] and s['rx_timeouts']==start['rx_timeouts'],s
        report['stream']={'frames':args.frames,'seconds':elapsed,'fps':args.frames/elapsed,
                          'MBps':args.frames*len(packet)/elapsed/1e6,'stats':s}
        # Verify actual physical DDR through MEM-AP0, bypassing CPU caches.
        binary=args.out/'scanout.bgr'
        script=args.out/'read-scanout.tcl'
        script.write_text('connect -url tcp:127.0.0.1:3121\n'
            'targets -set -filter {name =~ "APU"}\n'
            'foreach {name address} {cr 0x43000000 sr 0x43000004 vsize 0x43000050 hsize 0x43000054 stride 0x43000058 start 0x4300005c} {\n'
            'puts "VDMA_$name [mrd -address-space AP0 -value -force $address]"\n}\n'
            f'mrd -address-space AP0 -force -bin -file {{{binary.resolve().as_posix()}}} '
            f'{s["front"]:#x} {len(expected)//4}\ndisconnect\nexit\n')
        proc=subprocess.run(['python',str(ROOT/'tools/run_xsct.py'),str(script)],capture_output=True,text=True)
        (args.out/'read-scanout.log').write_text(proc.stdout+proc.stderr)
        assert proc.returncode==0,proc.stdout+proc.stderr
        regs={name:int(value,0) for name,value in re.findall(r'VDMA_(\w+)\s+(0x[0-9a-fA-F]+|\d+)',proc.stdout)}
        assert regs['cr']&1 and not regs['sr']&0xff1, regs
        assert regs['start']==s['front'] and regs['vsize']==h and regs['hsize']==w*3 and regs['stride']&0xffff==w*3,regs
        report['physical_vdma_registers']=regs
        actual=binary.read_bytes()
        assert actual==expected,'Physical DDR differs from expected BGR888 image'
        (args.out/'expected.bgr').write_bytes(expected)
        report['physical_ddr']={'address':hex(s['front']),'bytes':len(actual),
            'sha256':hashlib.sha256(actual).hexdigest(),'matches_expected':True}
        from PIL import Image
        Image.frombytes('RGB',(w,h),actual,'raw','BGR').save(args.out/'scanout.png')
        report['final']=stats(dev)
        report['passed']=True
        save()
        print(json.dumps(report,indent=2))
    finally:
        save()
        usb.util.dispose_resources(dev)


if __name__=='__main__':
    main()
