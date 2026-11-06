"""Generate the USB+LCD BSP and build the bare-metal application (SDK 2018.3)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from sdk_runtime import prepare

ROOT = Path(__file__).resolve().parents[1]
SDK = Path('E:/Xilinx/SDK/2018.3')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bsp', action='store_true', help='regenerate BSP from prebuilt/system.hdf')
    args = ap.parse_args()
    out = ROOT/'build/software'
    out.mkdir(parents=True, exist_ok=True)
    bsp = out/'bsp/ps7_cortexa9_0'
    env = os.environ.copy()
    env['RDI_PLATFORM'] = 'win64'
    env['SHELL'] = 'cmd.exe'
    env['PATH'] = str(SDK/'gnu/aarch32/nt/gcc-arm-none-eabi/bin')+';'+str(SDK/'gnuwin/bin')+';'+env['PATH']

    def run(command, name, **kwargs):
        p = subprocess.run(list(map(str, command)), capture_output=True, text=True, errors='replace', **kwargs)
        (out/name).write_text(p.stdout+p.stderr, encoding='utf8')
        if p.returncode:
            raise RuntimeError(name+'\n'+p.stdout[-4000:]+p.stderr[-4000:])

    if args.bsp or not (bsp/'lib/libxil.a').exists():
        hw = out/'hardware'
        hw.mkdir(exist_ok=True)
        shutil.copy2(ROOT/'prebuilt/system.hdf', hw/'system.hdf')
        script = out/'bsp.tcl'
        script.write_text('open_hw_design {'+(hw/'system.hdf').as_posix()+'}\n'
            'create_sw_design display_bsp -proc ps7_cortexa9_0 -os standalone\n'
            'generate_bsp -dir {'+(out/'bsp').as_posix()+'}\nexit\n')
        exe, hsi_env = prepare(SDK, 'hsi')
        run([exe, '-mode', 'batch', '-source', script], 'hsi.log', env=hsi_env, cwd=out)
        run([SDK/'gnuwin/bin/make.exe', '-C', out/'bsp', '-j1', 'SHELL=cmd.exe'], 'bsp-build.log', env=env)
        shutil.copy2(hw/'ps7_init.tcl', ROOT/'prebuilt/ps7_init.tcl')
    gcc = SDK/'gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    flags = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard', '-O3', '-g3',
             '-ffunction-sections', '-fdata-sections', '-Wall', '-Wextra', '-std=gnu11',
             '-I'+str(bsp/'include'), '-I'+str(ROOT/'firmware')]
    objects = []
    for source in sorted((ROOT/'firmware').rglob('*.c')):
        obj = out/(source.relative_to(ROOT/'firmware').as_posix().replace('/', '_')+'.o')
        run([gcc, *flags, '-c', source, '-o', obj], obj.name+'.log', env=env)
        objects.append(obj)
    elf = ROOT/'prebuilt/usb_display.elf'
    run([gcc, *flags, '-specs='+str(ROOT/'firmware/Xilinx.spec'), '-Wl,--build-id=none', '-Wl,--gc-sections',
         '-Wl,-T,'+str(ROOT/'firmware/lscript.ld'), '-Wl,-Map,'+str(out/'usb_display.map'),
         '-L'+str(bsp/'lib'), '-o', elf, *objects, '-Wl,--start-group', '-lxil', '-lm', '-lgcc', '-lc', '-Wl,--end-group'], 'link.log', env=env)
    files = [*sorted((ROOT/'firmware').rglob('*')), ROOT/'prebuilt/system.hdf',
             ROOT/'prebuilt/ps7_init.tcl', elf, bsp/'lib/libxil.a']
    manifest = {'compiler': str(gcc), 'flags': flags, 'sha256': {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}}
    bit = ROOT/'prebuilt/usb_display.bit'
    if bit.exists():
        manifest['sha256']['prebuilt/usb_display.bit'] = hashlib.sha256(bit.read_bytes()).hexdigest()
    (ROOT/'prebuilt/manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(elf)


if __name__ == '__main__':
    main()
