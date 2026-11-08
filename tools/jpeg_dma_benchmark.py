"""Measure HP1 JPEG writeback on the board with matching full-frame fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import usb.util

from benchmark import run
from flash import display_node
from jpeg_acceptance import read_ddr
from usb_host import ROOT, connect, display_status, firmware_info, profile, set_profile, stats


FIXTURES = ('800x480_color', '800x480_high_entropy')
REGISTERS = ('id', 'status', 'src', 'length', 'dst', 'size', 'cycles', 'pixels',
             'write_bursts', 'aw_wait', 'w_wait', 'b_wait', 'pixel_wait', 'input_wait',
             'peak_writes', 'write_window')


def registers(out, window=None):
    script = out/'hp1-registers.tcl'
    commands = ['connect -url tcp:127.0.0.1:3121', 'targets -set -filter {name =~ "APU"}']
    if window is not None:
        commands.append(f'mwr -force 0x43c1003c {window}')
    commands.extend(['puts [mrd -force 0x43c10000 16]', 'disconnect', 'exit'])
    script.write_text('\n'.join(commands)+'\n', encoding='ascii')
    result = subprocess.run([sys.executable, ROOT/'tools/run_xsct.py', script],
                            capture_output=True, text=True, check=True)
    words = {int(address, 16): int(value, 16) for address,value in
             re.findall(r'^([0-9a-fA-F]{8}):\s+([0-9a-fA-F]{8})', result.stdout, re.M)}
    regs = {name: words[0x43c10000+4*i] for i,name in enumerate(REGISTERS)}
    if regs['id'] != 0x4a504701 or (window is not None and regs['write_window'] != window):
        raise RuntimeError(f'Unexpected JPEG DMA registers: {regs}')
    return regs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, default=ROOT/'build/jpeg-rtl-sim')
    parser.add_argument('--window', type=int, choices=range(1,9), action='append',
                        help='test write window(s), default uses the loaded bitstream setting')
    parser.add_argument('--frames', type=int, default=128)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error('Frames must be positive.')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    node = display_node()
    restore_display = node is not None and node['Status'] == 'OK'
    report = {'runs': []}
    dev = None
    restore_window = None
    try:
        if restore_display:
            subprocess.run(['pnputil', '/disable-device', node['InstanceId']], check=True)
        dev = connect()
        report['firmware'] = firmware_info(dev)
        if not report['firmware']['features']&8:
            raise RuntimeError('Board is not running the RTL JPEG decoder.')
        before = stats(dev)
        time.sleep(.2)
        if stats(dev)['ep1_frames'] != before['ep1_frames']:
            raise RuntimeError('The IDD interface is still sending frames.')
        initial_window = registers(out)['write_window']
        if args.window:
            if not initial_window:
                raise RuntimeError('The loaded bitstream does not support the write window register.')
            restore_window = initial_window
        for window in args.window or [None]:
            if window is not None:
                registers(out, window)
            for name in FIXTURES:
                set_profile(dev,2)
                fixture = args.fixtures/(name+'.jpg')
                jpeg = fixture.read_bytes()
                scanout_before = display_status(dev)
                result = run(dev,jpeg,3,args.frames,8)
                result['name'] = name
                result['jpeg_sha256'] = hashlib.sha256(jpeg).hexdigest()
                result['profile'] = profile(dev)
                result['registers'] = registers(out)
                result['published_delta'] = result['display']['published']-scanout_before['published']
                if (result['registers']['status'] != 2 or result['registers']['pixels'] != 800*480
                        or result['registers']['cycles'] != result['profile']['jpeg_hw_cycles']):
                    raise RuntimeError(f'Invalid completed JPEG job: {result["registers"]}')
                bgr = read_ddr(result['display']['programmed'],800,480,
                               out/f'{name}-w{window or initial_window}.bgr')
                reference = fixture.with_suffix('.bgr').read_bytes()
                if bgr != reference:
                    raise RuntimeError(f'Board DDR differs from the RTL reference for {name}.')
                result['bgr_sha256'] = hashlib.sha256(bgr).hexdigest()
                report['runs'].append(result)
                print(f'{name} window={window or initial_window or "original"} '
                      f'{result["fps"]:.2f} fps, {result["registers"]["cycles"]} PL cycles',flush=True)
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        try:
            if restore_window is not None:
                registers(out, restore_window)
        finally:
            try:
                if dev is not None:
                    try:
                        set_profile(dev,2)
                    finally:
                        usb.util.dispose_resources(dev)
            finally:
                if restore_display:
                    subprocess.run([sys.executable, ROOT/'tools/enable_display.py'], check=True)


if __name__ == '__main__':
    main()
