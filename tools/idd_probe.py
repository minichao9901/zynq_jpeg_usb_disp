"""Brief IDD topology check. Always disable this device's MI_00 on exit."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import win32api

ROOT=Path(__file__).resolve().parents[1]


def topology():
    items=[]
    for i in range(64):
        try: d=win32api.EnumDisplayDevices(None,i,0)
        except Exception: break
        item={'name':d.DeviceName,'device':d.DeviceString,'flags':d.StateFlags}
        try:
            m=win32api.EnumDisplaySettings(d.DeviceName,-1)
            item['mode']={'width':m.PelsWidth,'height':m.PelsHeight,'x':m.Position_x,'y':m.Position_y,'hz':m.DisplayFrequency}
        except Exception: pass
        items.append(item)
    return items


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds',type=int,default=10)
    ap.add_argument('--instance',required=True)
    ap.add_argument('--extend',action='store_true',help='apply extended layout preserving the current primary monitor')
    args=ap.parse_args()
    if not args.instance.upper().startswith('USB\\VID_303A&PID_2986&MI_00\\'):
        raise ValueError('Expected this device MI_00 instance')
    if not 1<=args.seconds<=15: raise ValueError('Probe duration must be 1..15s')
    report={'before':topology(),'samples':[]}
    out=ROOT/'build/idd-topology-probe.json'
    primary=None
    if args.extend:
        from display_layout import primary_snapshot,extend
        primary=primary_snapshot()
    try:
        subprocess.run(['pnputil','/enable-device',args.instance],check=True)
        if primary:
            time.sleep(1)
            report['extended']=extend(*primary)
        end=time.monotonic()+args.seconds
        while time.monotonic()<end:
            report['samples'].append(topology())
            time.sleep(.5)
    finally:
        subprocess.run(['pnputil','/disable-device',args.instance],check=True)
        report['after']=topology()
        out.write_text(json.dumps(report,indent=2)+'\n')
    print(out)


if __name__=='__main__': main()
