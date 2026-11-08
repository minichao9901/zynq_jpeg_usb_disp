"""Simulate the DDR-to-DDR JPEG peripheral with Icarus Verilog and Pillow."""
import argparse
from dataclasses import dataclass
import io
import json
from pathlib import Path
import random
import re
import subprocess

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Case:
    name: str
    data: bytes
    size: tuple[int, int]
    origin: tuple[int, int] = (0, 0)
    fault: int = 0
    inject: int = 0
    max_error: int = 4
    mean_error: float = 1.25


def encode(image, **options):
    out = io.BytesIO()
    image.save(out, format='JPEG', **options)
    return out.getvalue()


def gradient(w, h):
    # Smooth chroma and nonuniform luma distinguish channel/coordinate errors
    # without requiring Pillow's fancy chroma interpolation in the RTL.
    pixels = bytes(channel for y in range(h) for x in range(w) for channel in
                   (40 + 130*x//w, 60 + 130*y//h, 190 - 80*x//w))
    return Image.frombytes('RGB', (w, h), pixels)


def fixtures(quick):
    source = gradient(127, 83)
    # y=1, x=564 starts at byte 4092: the first write burst must split.
    restart = encode(source, subsampling=2, optimize=True, quality=82, restart_marker_blocks=3)
    assert b'\xff\xd0' in restart
    valid = encode(source, subsampling=0, quality=91)
    rng = random.Random(98116)
    noise = Image.frombytes('L', (800, 480), rng.randbytes(800*480))
    cases = [
        Case('gray_single_pixel', encode(Image.new('L',(1,1),188)), (1,1)),
        Case('444_roi', valid, source.size, (13,17)),
        Case('422_optimized', encode(source, subsampling=1, optimize=True), source.size,
             (7,3), max_error=9, mean_error=2),
        Case('420_restart_page_split', restart, source.size, (564,1), max_error=9, mean_error=2),
        Case('gray_noise', encode(noise.crop((0,0,97,81)), quality=92, optimize=True), (97,81)),
        Case('read_error_recovery', valid, source.size, (3,2), inject=3),
        Case('write_error_recovery', valid, source.size, (3,2), inject=4),
        Case('abort_write_recovery', valid, source.size, (3,2), inject=6),
        Case('wrong_width', valid, (126,83), fault=2),
        Case('truncated_entropy', valid[:-43], source.size, fault=2),
        Case('premature_eoi', valid[:-43]+b'\xff\xd9', source.size, fault=2),
        Case('wrong_restart', restart.replace(b'\xff\xd0',b'\xff\xd3',1), source.size, fault=2),
        Case('progressive_rejected', encode(source, progressive=True), source.size, fault=2),
    ]
    if not quick:
        cases.extend([
            Case('800x480_color', encode(gradient(800,480), quality=84, subsampling=2), (800,480),
                 max_error=8, mean_error=2),
            Case('800x480_high_entropy', encode(noise.convert('RGB'), quality=85, subsampling=2), (800,480)),
        ])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick', action='store_true', help='skip 800x480 cases')
    parser.add_argument('--case', action='append', default=[], help='run only these named cases')
    parser.add_argument('--write-window', type=int, choices=range(1,9), default=8)
    parser.add_argument('--b-latency', type=int, default=0, help='extra cycles before DDR write responses')
    parser.add_argument('--out', type=Path, default=ROOT/'build/jpeg-rtl-sim')
    args = parser.parse_args()
    if args.b_latency<0:
        parser.error('Write response latency must be nonnegative.')
    out = args.out
    out.mkdir(parents=True,exist_ok=True)
    rtl = ROOT/'fpga/jpeg'
    sources = sorted(rtl.glob('*.v')) + sorted((rtl/'core').glob('*.v'))
    sim = out/'jpeg_dma.vvp'
    subprocess.run(['iverilog','-g2012','-s','jpeg_dma_tb','-o',str(sim),
                    str(rtl/'sim/jpeg_dma_tb.sv'),*map(str,sources)], check=True)
    results = {}
    for case in fixtures(args.quick):
        if args.case and case.name not in args.case:
            continue
        jpg, bgr = out/(case.name+'.jpg'), out/(case.name+'.bgr')
        jpg.write_bytes(case.data)
        w,h = case.size
        x,y = case.origin
        process = subprocess.run(['vvp',str(sim),f'+input={jpg}',f'+output={bgr}',
                                  f'+width={w}',f'+height={h}',f'+x={x}',f'+y={y}',
                                  f'+fault={case.fault}',f'+inject={case.inject}',
                                  f'+b_latency={args.b_latency}',f'+write_window={args.write_window}'],
                                 capture_output=True,text=True,timeout=300)
        (out/(case.name+'.log')).write_text(process.stdout+process.stderr,encoding='utf8')
        if process.returncode:
            raise RuntimeError(case.name+'\n'+process.stdout+process.stderr)
        status,pixels,cycles,aw,b_wait,peak = re.findall(
            r'RESULT status=(\w+) pixels=(\d+) cycles=(\d+) aw=(\d+) b_wait=(\d+) peak=(\d+)',
            process.stdout)[-1]
        result = {'status':status,'pixels':int(pixels),'cycles':int(cycles),'jpeg_bytes':len(case.data),
                  'write_bursts':int(aw),'b_wait_cycles':int(b_wait),'peak_writes':int(peak)}
        if not case.fault:
            expected = Image.open(jpg).convert('RGB')
            actual = Image.frombytes('RGB',case.size,bgr.read_bytes(),'raw','BGR')
            diff = ImageChops.difference(expected,actual)
            maximum = max(hi for _,hi in diff.getextrema())
            mean = sum(diff.tobytes())/(w*h*3)
            result.update(max_error=maximum,mean_error=round(mean,4))
            if maximum>case.max_error or mean>case.mean_error:
                raise AssertionError((case.name,result,case.max_error,case.mean_error))
        print(case.name,result,flush=True)
        results[case.name] = result
    if not results:
        parser.error('No matching cases.')
    report_name = 'selected.json' if args.case else 'quick.json' if args.quick else 'results.json'
    (out/report_name).write_text(
        json.dumps(results,indent=2)+'\n',encoding='utf8')


if __name__ == '__main__':
    main()
