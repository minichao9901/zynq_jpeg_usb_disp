"""Download the verified unrestricted RGB/JPEG bit+ELF pair through JTAG/RAM.

Examples: python tools/flash.py rgb
          python tools/flash.py jpeg --build
          python tools/flash.py rgb --dry-run
QSPI is never written. Requires Windows administrator rights for IDD control.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from mode_config import ENCODINGS,DRIVER_FPS,normalize_mode,product_for

ROOT=Path(__file__).resolve().parents[1]
REGISTRY_KEY=r'SYSTEM\CurrentControlSet\Services\xfz1986_usb_graphic\Parameters'
FILES={'usb_display.bit','usb_display.elf','ps7_init.tcl','system.hdf'}


def validate_package(package,mode):
    package=Path(package).resolve();mode=normalize_mode(mode)
    manifest=json.loads((package/'manifest.json').read_text(encoding='utf8'))
    if manifest.get('schema')!=1 or manifest.get('mode')!=mode or manifest.get('default_encoding')!=ENCODINGS[mode]:
        raise ValueError('Package mode/schema does not match the requested mode')
    if manifest.get('fps_limit','missing') is not None or manifest.get('driver_fps_token')!=DRIVER_FPS or manifest.get('normal_profile_flags')!=2:
        raise ValueError('Package does not declare the unrestricted optimized release policy')
    if manifest.get('product')!=product_for(mode): raise ValueError('Unexpected USB product string')
    if not 0<=int(manifest['build_id'],0)<=0xffffffff: raise ValueError('Invalid build identity')
    hashes=manifest.get('sha256',{})
    if set(hashes)!=FILES: raise ValueError('Package must contain exactly the four expected artifact hashes')
    for name,expected in hashes.items():
        path=(package/name).resolve()
        if not path.is_relative_to(package): raise ValueError('Artifact escapes package directory')
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=expected: raise ValueError(f'SHA-256 mismatch: {path}')
    return manifest


def display_node():
    # Scope host changes to this board's serial number, not another ESP32 with
    # the same VID/PID. The parent identity is independent of MI instance IDs.
    script=r"""Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\VID_303A&PID_2986&MI_00\*'} | ForEach-Object {
    $parent=(Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Parent).Data
    if ($parent -ieq 'USB\VID_303A&PID_2986\ZYNQ-UDISP-RGB-001') {
        [pscustomobject]@{InstanceId=$_.InstanceId;Status=$_.Status}
    }
} | ConvertTo-Json -Compress
"""
    result=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,errors='replace',check=True)
    if not result.stdout.strip(): return None
    nodes=json.loads(result.stdout)
    if isinstance(nodes,list):
        if len(nodes)!=1: raise RuntimeError('Multiple matching Zynq display interfaces')
        nodes=nodes[0]
    return nodes


def run_logged(command,log):
    result=subprocess.run(list(map(str,command)),cwd=ROOT,capture_output=True,text=True,errors='replace')
    log.write_text(result.stdout+result.stderr,encoding='utf8')
    if result.returncode: raise RuntimeError(f'{Path(str(command[0])).name} failed; see {log}\n'+(result.stdout+result.stderr)[-1800:])


def wait_for_board(manifest):
    import usb.util
    from usb_host import connect,stats,firmware_info
    deadline=time.monotonic()+12;last='not enumerated'
    while time.monotonic()<deadline:
        dev=None
        try:
            dev=connect();info=firmware_info(dev);state=stats(dev)
            if (info['default_encoding']!=manifest['default_encoding'] or info['driver_fps_token']!=DRIVER_FPS or
                info['build_id']!=int(manifest['build_id'],0) or info['profile_flags']!=2 or dev.product!=manifest['product']):
                raise RuntimeError('Running firmware identity does not match the requested package')
            if state['configured']!=1 or state['speed']!=480 or state['stage']!=3:
                raise RuntimeError('USB high-speed configuration is not ready')
            return info,state
        except Exception as e:
            last=str(e);time.sleep(.2)
        finally:
            if dev is not None: usb.util.dispose_resources(dev)
    raise RuntimeError('Downloaded board verification failed: '+last)


def flash(mode,package,manifest,no_display):
    import winreg
    import usb.util
    from usb_host import connect,stats,firmware_info
    logdir=ROOT/'build/flash'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    logdir.mkdir(parents=True,exist_ok=False)
    report={'passed':False,'mode':mode,'transport':'JTAG/RAM','qspi_written':False,
        'package':str(package),'artifacts':manifest['sha256'],'product':manifest['product']}
    backup=None;registry=None
    try:
        try:
            registry=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,REGISTRY_KEY,0,winreg.KEY_READ|winreg.KEY_SET_VALUE)
        except FileNotFoundError:
            if not no_display: raise RuntimeError('IDD driver registry key not found; install the display driver or use --no-display')
        if registry is not None:
            try: old,kind=winreg.QueryValueEx(registry,'udisp');backup={'exists':True,'value':old,'type':kind}
            except FileNotFoundError: backup={'exists':False}
            (logdir/'registry-backup.json').write_text(json.dumps(backup,indent=2)+'\n')
        node=display_node()
        if node and node['Status']=='OK':
            run_logged(['pnputil','/disable-device',node['InstanceId']],logdir/'disable-idd.log')
        if registry is not None: winreg.SetValueEx(registry,'udisp',0,winreg.REG_SZ,manifest['product'])
        print(f'Downloading {mode.upper()} bit + ELF through JTAG/RAM...',flush=True)
        run_logged([sys.executable,ROOT/'tools/run_xsct.py',ROOT/'tools/load.tcl',package/'usb_display.elf',
                    package/'usb_display.bit',package/'ps7_init.tcl'],logdir/'download.log')
        info,before=wait_for_board(manifest)
        report['firmware']=info;report['before_display']=before
        node=display_node()
        if no_display:
            if node and node['Status']=='OK': run_logged(['pnputil','/disable-device',node['InstanceId']],logdir/'disable-idd-final.log')
        else:
            run_logged([sys.executable,ROOT/'tools/enable_display.py'],logdir/'enable-idd.log')
            dev=connect()
            try:
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    after=stats(dev)
                    if after['ep1_frames']>before['ep1_frames'] and after['last_type']==ENCODINGS[mode]: break
                    time.sleep(.1)
                else: raise RuntimeError('IDD did not deliver the requested RGB/JPEG frame type')
                report['after_display']=after
                report['firmware_after_display']=firmware_info(dev)
            finally: usb.util.dispose_resources(dev)
            layout=ROOT/'build/display-enabled.json'
            if layout.exists(): report['display_layout']=json.loads(layout.read_text())
        report['passed']=True
    except BaseException as e:
        report['error']=str(e)
        try:
            node=display_node()
            if node and node['Status']=='OK': run_logged(['pnputil','/disable-device',node['InstanceId']],logdir/'disable-idd-on-error.log')
            if registry is not None and backup:
                if backup['exists']: winreg.SetValueEx(registry,'udisp',0,backup['type'],backup['value'])
                else: winreg.DeleteValue(registry,'udisp')
        except Exception as cleanup: report['cleanup_error']=str(cleanup)
        raise
    finally:
        if registry is not None: winreg.CloseKey(registry)
        (logdir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Report:',logdir/'report.json')
    print(f"OK: {mode}, USB 480 Mbps, Fps{DRIVER_FPS} unrestricted, FNV off; QSPI unchanged.")
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode',choices=['rgb','rgb565','jpeg'])
    ap.add_argument('--build',action='store_true',help='compile the selected package before downloading')
    ap.add_argument('--dry-run',action='store_true',help='verify artifact hashes and print the exact pair, without hardware or registry access')
    ap.add_argument('--no-display',action='store_true',help='keep MI_00 disabled for diagnostic/throughput testing')
    args=ap.parse_args();mode=normalize_mode(args.mode)
    if args.build:
        subprocess.run([sys.executable,str(ROOT/'tools/build.py'),'--mode',mode],cwd=ROOT,check=True)
    package=ROOT/'prebuilt'/mode
    manifest=validate_package(package,mode)
    if args.dry_run:
        print(json.dumps({'mode':mode,'transport':'JTAG/RAM','fps_limit':None,'product':manifest['product'],
            'build_id':manifest['build_id'],'files':{name:{'path':str(package/name),'sha256':digest} for name,digest in manifest['sha256'].items()}},indent=2))
    else: flash(mode,package,manifest,args.no_display)


if __name__=='__main__':
    try: main()
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
