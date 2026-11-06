"""Compare verification, normal display and receive-only throughput, unpaced."""
import argparse
import json
from pathlib import Path
import statistics
import time
import usb.util
from usb_host import connect,stats,profile,set_profile,pattern,ROOT
from benchmark import run


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repeat',type=int,default=3)
    ap.add_argument('--frames',type=int,default=128)
    ap.add_argument('--out',type=Path,default=ROOT/'build/throughput-final.json')
    args=ap.parse_args();dev=connect();results=[]
    try:
        before=stats(dev);time.sleep(.2)
        assert stats(dev)['ep1_frames']==before['ep1_frames'],'Pause IDD MI_00 first'
        payload=pattern(before['width'],before['height'])
        for trial in range(args.repeat):
            for flags in [0,2,1]:
                set_profile(dev,flags)
                r=run(dev,payload,0,args.frames,8)
                r.update(trial=trial,profile=profile(dev));results.append(r)
                print(trial,flags,round(r['wire_MBps'],3),flush=True)
        report={'results':results,'median_MBps':{str(f):statistics.median(r['wire_MBps'] for r in results if r['profile']['flags']==f) for f in [0,2,1]}}
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+'\n')
    finally: set_profile(dev,2);usb.util.dispose_resources(dev)


if __name__=='__main__': main()
