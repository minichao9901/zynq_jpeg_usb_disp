"""Build the RTL JPEG firmware and package it with the matching Vivado outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from sdk_runtime import prepare
from mode_config import DRIVER_FPS,ENCODINGS,product_for

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get('XILINX_SDK','E:/Xilinx/SDK/2018.3')).resolve()
HARDWARE = ROOT/'build/fpga-jpeg-rtl'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bsp', action='store_true', help='force BSP regeneration from the RTL hardware handoff')
    ap.add_argument('--mode',choices=['all','rgb','jpeg'],default='all',help='build both unrestricted release profiles by default')
    args = ap.parse_args()
    out = ROOT/'build/software-jpeg-rtl'
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['RDI_PLATFORM'] = 'win64'
    env['SHELL'] = 'cmd.exe'
    env['PATH'] = str(SDK/'gnu/aarch32/nt/gcc-arm-none-eabi/bin')+';'+str(SDK/'gnuwin/bin')+';'+env['PATH']

    def run(command, name, **kwargs):
        p = subprocess.run(list(map(str, command)), capture_output=True, text=True, errors='replace', **kwargs)
        (out/name).write_text(p.stdout+p.stderr, encoding='utf8')
        if p.returncode:
            raise RuntimeError(name+'\n'+p.stdout[-4000:]+p.stderr[-4000:])

    hardware = HARDWARE if (HARDWARE/'system.hdf').is_file() else ROOT/'prebuilt/jpeg-rtl'
    handoff = hardware/'system.hdf'
    if not handoff.is_file():
        ap.error('Run fpga/build_jpeg_rtl.tcl in Vivado to generate the RTL hardware handoff.')
    handoff_hash = digest(handoff)
    hw = out/'hardware'/handoff_hash
    bsp_dir = hw/'bsp'
    bsp = bsp_dir/'ps7_cortexa9_0'
    if args.bsp or not (bsp/'lib/libxil.a').exists() or not (hw/'ps7_init.tcl').exists():
        hw.mkdir(parents=True, exist_ok=True)
        shutil.copy2(handoff, hw/'system.hdf')
        script = out/'bsp.tcl'
        script.write_text('open_hw_design {'+(hw/'system.hdf').as_posix()+'}\n'
            'create_sw_design display_bsp -proc ps7_cortexa9_0 -os standalone\n'
            'generate_bsp -dir {'+bsp_dir.as_posix()+'}\nexit\n')
        exe, hsi_env = prepare(SDK, 'hsi')
        run([exe, '-mode', 'batch', '-source', script], 'hsi.log', env=hsi_env, cwd=out)
        run([SDK/'gnuwin/bin/make.exe', '-C', bsp_dir, '-j1', 'SHELL=cmd.exe'], 'bsp-build.log', env=env)
    bit = hardware/'usb_display.bit'
    if not bit.is_file():
        ap.error('RTL BSP is ready. Complete Vivado implementation to generate its bitstream.')
    gcc = SDK/'gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    flags = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard', '-O3', '-g3',
             '-ffunction-sections', '-fdata-sections', '-Wall', '-Wextra', '-std=gnu11',
             '-I'+str(bsp/'include'), '-I'+str(ROOT/'firmware')]
    files = [*sorted((ROOT/'firmware').rglob('*')),ROOT/'tools/build.py',ROOT/'tools/mode_config.py']
    inputs={p.relative_to(ROOT).as_posix():digest(p) for p in files if p.is_file()}
    inputs.update({f'hardware/{p.name}':digest(p) for p in
                   (bsp/'lib/libxil.a',bit,handoff,hw/'ps7_init.tcl')})
    modes=['rgb','jpeg'] if args.mode=='all' else [args.mode]
    for mode in modes:
        variant_out=out/mode;variant_out.mkdir(exist_ok=True)
        package=ROOT/'prebuilt'/(mode+'-rtl')
        identity=hashlib.sha256(json.dumps({'mode':mode,'fps':DRIVER_FPS,'inputs':inputs},sort_keys=True).encode()).hexdigest()[:8]
        mode_flags=flags+[f'-DUDISP_DEFAULT_ENCODING={ENCODINGS[mode]}',f'-DUDISP_DRIVER_FPS={DRIVER_FPS}',f'-DUDISP_BUILD_ID=0x{identity}U']
        objects=[]
        for source in sorted((ROOT/'firmware').rglob('*.c')):
            obj=variant_out/(source.relative_to(ROOT/'firmware').as_posix().replace('/','_')+'.o')
            run([gcc,*mode_flags,'-c',source,'-o',obj],mode+'-'+obj.name+'.log',env=env)
            objects.append(obj)
        elf=variant_out/'usb_display.elf'
        run([gcc,*mode_flags,'-specs='+str(ROOT/'firmware/Xilinx.spec'),'-Wl,--build-id=none','-Wl,--gc-sections',
             '-Wl,-T,'+str(ROOT/'firmware/lscript.ld'),'-Wl,-Map,'+str(variant_out/'usb_display.map'),
             '-L'+str(bsp/'lib'),'-o',elf,*objects,'-Wl,--start-group','-lxil','-lm','-lgcc','-lc','-Wl,--end-group'],mode+'-link.log',env=env)
        package.mkdir(exist_ok=True)
        artifacts = [elf, bit, hw/'ps7_init.tcl', hw/'system.hdf']
        for artifact in artifacts:
            target = package/artifact.name
            if artifact.resolve() != target.resolve():
                shutil.copy2(artifact,target)
        manifest={'schema':1,'mode':mode,'default_encoding':ENCODINGS[mode],
            'fps_limit':None,'driver_fps_token':DRIVER_FPS,'normal_profile_flags':2,
            'display_update':'frame-boundary-shadow','software_frame_buffers':5,
            'product':product_for(mode),'build_id':'0x'+identity,'compiler':str(gcc),'flags':mode_flags,
            'jpeg_decoder':'pl-rtl','hardware_validation':'offline-only','inputs_sha256':inputs,
            'sha256':{p.name:digest(package/p.name) for p in artifacts}}
        (package/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(package/'usb_display.elf')


if __name__ == '__main__':
    main()
