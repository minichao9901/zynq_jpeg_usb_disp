"""Unpaced USB OUT/display benchmark. Pause MI_00 before running."""
import argparse
import json
from pathlib import Path
import time
import usb.util
from usb_host import connect,stats,frame,pattern,wait_for,ROOT,profile,set_profile,display_status,wait_display


def run(dev, payload, mode, frames, batch, fps=0):
    before=stats(dev)
    target=before['ep2_frames']+frames
    packet=frame(payload,before['width'],before['height'],mode=mode)
    transfer=packet*batch
    started=time.perf_counter(); sent=0
    while sent<frames:
        count=min(batch,frames-sent)
        data=transfer if count==batch else packet*count
        assert dev.write(2,data,timeout=30000)==len(data)
        sent+=count
        if fps:
            delay=sent/fps-(time.perf_counter()-started)
            if delay>0: time.sleep(delay)
    submitted=time.perf_counter()
    after=wait_for(dev,'ep2_frames',target,timeout=20)
    elapsed=time.perf_counter()-started
    assert after['ep2_frames']==target,(before,after)
    assert all(after[k]==before[k] for k in ['bad','display_errors','rx_timeouts']), (before,after)
    wait_display(dev)
    display=display_status(dev)
    assert display['control']&1 and not display['halted_seen'] and not display['error_seen'] and not display['no_buffer'],display
    return {'direction':'host to device USB OUT','mode':mode,'frames':frames,'batch':batch,
            'paced_fps':fps,'payload_bytes_per_frame':len(payload),'wire_bytes':len(packet)*frames,
            'submit_seconds':submitted-started,'complete_seconds':elapsed,'fps':frames/elapsed,
            'wire_MBps':len(packet)*frames/elapsed/1e6,'before':before,'after':after,'display':display}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames',type=int,default=128)
    ap.add_argument('--batch',type=int,default=8)
    ap.add_argument('--fps',type=float,default=0)
    ap.add_argument('--jpeg',type=Path)
    ap.add_argument('--flags',type=int,choices=[0,1,2],default=None,help='0=verify FNV; 1=receive only; 2=display without FNV')
    ap.add_argument('--out',type=Path,default=ROOT/'build/benchmark.json')
    args=ap.parse_args();dev=connect()
    try:
        s=stats(dev);time.sleep(.2)
        assert stats(dev)['ep1_frames']==s['ep1_frames'],'Pause MI_00 first'
        if args.flags is not None: set_profile(dev,args.flags)
        payload=args.jpeg.read_bytes() if args.jpeg else pattern(s['width'],s['height'])
        result=run(dev,payload,3 if args.jpeg else 0,args.frames,args.batch,args.fps)
        if args.flags is not None:
            result['profile']=profile(dev)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ['before','after']},indent=2))
    finally:
        if args.flags is not None: set_profile(dev,2)
        usb.util.dispose_resources(dev)


if __name__=='__main__': main()
