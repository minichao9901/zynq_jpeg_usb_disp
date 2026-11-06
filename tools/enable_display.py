"""Enable this Zynq display in extended mode, preserving the original main screen."""
import json
import subprocess
import time
from pathlib import Path
import win32api
import win32con
from display_layout import extend,primary_snapshot
from idd_probe import topology

ROOT=Path(__file__).resolve().parents[1]


def main():
    raw=subprocess.check_output(['powershell','-NoProfile','-Command',
        "@(Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\\VID_303A&PID_2986&MI_00\\*'} | Select-Object -ExpandProperty InstanceId) | ConvertTo-Json"],text=True)
    instance=json.loads(raw)
    if isinstance(instance,list):
        if len(instance)!=1: raise RuntimeError('Connect exactly one 303A:2986 display')
        instance=instance[0]
    if not instance: raise RuntimeError('Zynq display not connected')
    primary=primary_snapshot()
    if 'xfz1986' in next(x['device'] for x in topology() if x['name']==primary[0]):
        raise RuntimeError('Select the physical monitor as primary first')
    report={'before':topology()}
    try:
        subprocess.run(['pnputil','/enable-device',instance],check=True)
        time.sleep(1)
        report['on_attach']=topology()
        report['extended']=extend(*primary)
        external=next(x for x in report['extended'] if x['device'].startswith('xfz1986_usb_graphic'))
        modes=[]
        for i in range(128):
            try: m=win32api.EnumDisplaySettings(external['name'],i)
            except Exception: break
            modes.append((m.PelsWidth,m.PelsHeight,m.DisplayFrequency))
        report['usb_available_modes']=modes
        # Use native dimensions if the installed driver exposes them.
        if (800,480,60) in modes:
            m=win32api.EnumDisplaySettings(external['name'],-1)
            m.PelsWidth=800; m.PelsHeight=480; m.DisplayFrequency=60
            m.Fields=win32con.DM_PELSWIDTH|win32con.DM_PELSHEIGHT|win32con.DM_DISPLAYFREQUENCY
            report['native_mode_result']=win32api.ChangeDisplaySettingsEx(external['name'],m,win32con.CDS_UPDATEREGISTRY)
        report['after']=topology()
        main=next(x for x in report['after'] if x['name']==primary[0])
        assert main['flags']&5==5 and main['mode']['width']==primary[1].PelsWidth and main['mode']['height']==primary[1].PelsHeight
    except Exception:
        subprocess.run(['pnputil','/disable-device',instance])
        raise
    finally:
        out=ROOT/'build/display-enabled.json'
        out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([x for x in report['after'] if x['flags']&1],indent=2))


if __name__=='__main__': main()
