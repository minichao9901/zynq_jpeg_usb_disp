"""Select Windows IDD RGB565/JPEG mode, keeping the physical primary monitor."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import winreg
import usb.util
from usb_host import connect,stats,ROOT

KEY=r'SYSTEM\CurrentControlSet\Services\xfz1986_usb_graphic\Parameters'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=['rgb565','jpeg'])
    ap.add_argument('--quality',type=int,choices=range(1,11),default=8)
    args=ap.parse_args()
    raw=subprocess.check_output(['powershell','-NoProfile','-Command',
        "@(Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\\VID_303A&PID_2986&MI_00\\*'} | Select-Object -ExpandProperty InstanceId) | ConvertTo-Json"],text=True)
    nodes=json.loads(raw)
    if isinstance(nodes,str): nodes=[nodes]
    if not nodes or len(nodes)!=1: raise RuntimeError('Connect exactly one Zynq USB Display')
    dev=connect()
    before=stats(dev)
    usb.util.dispose_resources(dev)
    product=f'zynq_R800x480_Ejpg{args.quality}_Ergb16_Fps30_Bl4096' if args.mode=='jpeg' else 'zynq_R800x480_Ergb16_Ejpg8_Fps30_Bl4096'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,KEY,0,winreg.KEY_READ|winreg.KEY_SET_VALUE) as key:
        try: old,old_type=winreg.QueryValueEx(key,'udisp')
        except FileNotFoundError: old=None;old_type=winreg.REG_SZ
        backup=ROOT/'build/host-backup';backup.mkdir(parents=True,exist_ok=True)
        (backup/f'mode-{time.time_ns()}.json').write_text(json.dumps({'key':KEY,'udisp':old,'type':old_type},indent=2))
        subprocess.run(['pnputil','/disable-device',nodes[0]],check=True)
        winreg.SetValueEx(key,'udisp',0,winreg.REG_SZ,product)
        try:
            subprocess.run(['python',str(ROOT/'tools/enable_display.py')],check=True)
        except Exception:
            if old is None: winreg.DeleteValue(key,'udisp')
            else: winreg.SetValueEx(key,'udisp',0,old_type,old)
            raise
    dev=connect()
    try:
        end=time.monotonic()+8
        while time.monotonic()<end:
            after=stats(dev)
            if after['ep1_frames']>before['ep1_frames'] and after['last_type']==(3 if args.mode=='jpeg' else 0): break
            time.sleep(.1)
        else: raise RuntimeError('IDD did not deliver the selected wire mode: '+str(after))
        report={'mode':args.mode,'product':product,'before':before,'after':after}
        out=ROOT/'build'/('idd-'+args.mode+'.json');out.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally: usb.util.dispose_resources(dev)


if __name__=='__main__': main()
