"""Generate the USB+LCD BSP and build the bare-metal application (SDK 2018.3)."""
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
SDK = Path('E:/Xilinx/SDK/2018.3')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bsp', action='store_true', help='regenerate BSP from prebuilt/system.hdf')
    ap.add_argument('--mode',choices=['all','rgb','jpeg'],default='all',help='build both unrestricted release profiles by default')
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
    jpeg_out=ROOT/'build/jpeg'
    run(['cmake','-S',ROOT/'third_party/libjpeg-turbo','-B',jpeg_out,'-G','Ninja',
         '-DCMAKE_TOOLCHAIN_FILE='+str(ROOT/'tools/arm-jpeg.cmake'),'-DCMAKE_BUILD_TYPE=Release',
         '-DENABLE_SHARED=OFF','-DWITH_TURBOJPEG=OFF','-DWITH_TOOLS=OFF','-DWITH_TESTS=OFF',
         '-DWITH_ARITH_DEC=OFF','-DWITH_ARITH_ENC=OFF','-DREQUIRE_SIMD=ON','-DHAVE_THREAD_LOCAL=0'],
        'jpeg-configure.log',env=env)
    run(['cmake','--build',jpeg_out,'--target','jpeg-static','-j','4'],'jpeg-build.log',env=env)
    flags = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard', '-O3', '-g3',
             '-ffunction-sections', '-fdata-sections', '-Wall', '-Wextra', '-std=gnu11',
             '-I'+str(bsp/'include'), '-I'+str(ROOT/'firmware'),
             '-I'+str(ROOT/'third_party/libjpeg-turbo/src'),'-I'+str(jpeg_out)]
    files = [*sorted((ROOT/'firmware').rglob('*')),bsp/'lib/libxil.a',jpeg_out/'libjpeg.a',
        ROOT/'tools/build.py',ROOT/'tools/mode_config.py',ROOT/'tools/arm-jpeg.cmake',
        jpeg_out/'jconfig.h',jpeg_out/'jconfigint.h',*sorted((ROOT/'third_party/libjpeg-turbo').rglob('*'))]
    inputs={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    modes=['rgb','jpeg'] if args.mode=='all' else [args.mode]
    for mode in modes:
        variant_out=out/mode;variant_out.mkdir(exist_ok=True)
        package=ROOT/'prebuilt'/mode;package.mkdir(exist_ok=True)
        identity=hashlib.sha256(json.dumps({'mode':mode,'fps':DRIVER_FPS,'inputs':inputs},sort_keys=True).encode()).hexdigest()[:8]
        mode_flags=flags+[f'-DUDISP_DEFAULT_ENCODING={ENCODINGS[mode]}',f'-DUDISP_DRIVER_FPS={DRIVER_FPS}',f'-DUDISP_BUILD_ID=0x{identity}U']
        objects=[]
        for source in sorted((ROOT/'firmware').rglob('*.c')):
            obj=variant_out/(source.relative_to(ROOT/'firmware').as_posix().replace('/','_')+'.o')
            run([gcc,*mode_flags,'-c',source,'-o',obj],mode+'-'+obj.name+'.log',env=env)
            objects.append(obj)
        elf=package/'usb_display.elf'
        run([gcc,*mode_flags,'-specs='+str(ROOT/'firmware/Xilinx.spec'),'-Wl,--build-id=none','-Wl,--gc-sections',
             '-Wl,-T,'+str(ROOT/'firmware/lscript.ld'),'-Wl,-Map,'+str(variant_out/'usb_display.map'),
             '-L'+str(bsp/'lib'),'-o',elf,*objects,'-Wl,--start-group',jpeg_out/'libjpeg.a','-lxil','-lm','-lgcc','-lc','-Wl,--end-group'],mode+'-link.log',env=env)
        for name in ['usb_display.bit','ps7_init.tcl','system.hdf']:
            shutil.copy2(ROOT/'prebuilt'/name,package/name)
        manifest={'schema':1,'mode':mode,'default_encoding':ENCODINGS[mode],
            'fps_limit':None,'driver_fps_token':DRIVER_FPS,'normal_profile_flags':2,
            'product':product_for(mode),'build_id':'0x'+identity,'compiler':str(gcc),'flags':mode_flags,
            'bit_source':'shared unchanged reference LCD PL','inputs_sha256':inputs,
            'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [elf,package/'usb_display.bit',package/'ps7_init.tcl',package/'system.hdf']}}
        (package/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(elf)
    # Preserve the old root entry as a documented JPEG compatibility alias.
    jpeg_manifest=ROOT/'prebuilt/jpeg/manifest.json'
    if jpeg_manifest.exists():
        default=json.loads(jpeg_manifest.read_text())
        shutil.copy2(ROOT/'prebuilt/jpeg/usb_display.elf',ROOT/'prebuilt/usb_display.elf')
        hashes=dict(default['inputs_sha256'])
        for mode in ENCODINGS:
            p=ROOT/'prebuilt'/mode/'manifest.json'
            if p.exists():
                m=json.loads(p.read_text())
                hashes.update({f'prebuilt/{mode}/{n}':v for n,v in m['sha256'].items()})
        for name in ['usb_display.elf','usb_display.bit','ps7_init.tcl','system.hdf']:
            hashes['prebuilt/'+name]=hashlib.sha256((ROOT/'prebuilt'/name).read_bytes()).hexdigest()
        catalog={'default_mode':'jpeg','packages':{m:f'prebuilt/{m}/manifest.json' for m in ENCODINGS},'sha256':hashes}
        (ROOT/'prebuilt/manifest.json').write_text(json.dumps(catalog,indent=2)+'\n')


if __name__ == '__main__':
    main()
