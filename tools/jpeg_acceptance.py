"""JPEG decode and physical DDR validation through the diagnostic USB interface."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time
import usb.util
from PIL import Image,ImageChops
from usb_host import connect,stats,frame,wait_for,set_profile,profile,ROOT,wait_display
from benchmark import run as benchmark
from jpeg_rtl_sim import gradient


def read_ddr(address,w,h,out):
    script=out.with_suffix('.tcl')
    script.write_text('connect -url tcp:127.0.0.1:3121\ntargets -set -filter {name =~ "APU"}\n'
        f'mrd -address-space AP0 -force -bin -file {{{out.resolve().as_posix()}}} {address:#x} {(w*h*3+3)//4}\ndisconnect\nexit\n')
    p=subprocess.run(['python',str(ROOT/'tools/run_xsct.py'),str(script)],capture_output=True,text=True)
    out.with_suffix('.log').write_text(p.stdout+p.stderr)
    if p.returncode: raise RuntimeError(p.stdout+p.stderr)
    return out.read_bytes()[:w*h*3]


def fixture(w,h):
    im=Image.new('RGB',(w,h))
    im.putdata([((x*255)//max(1,w-1),(y*255)//max(1,h-1),((x//32+y//32)%2)*255) for y in range(h) for x in range(w)])
    return im


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'build/jpeg-acceptance')
    ap.add_argument('--fps',type=float,default=0,help='optional test pacing; default is unrestricted')
    args=ap.parse_args();out=args.out;out.mkdir(parents=True,exist_ok=True)
    dev=connect();report={'passed':False,'images':[],'negative_tests':[]}
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def send(data,w,h,x=0,y=0):
        before=stats(dev)
        dev.write(2,frame(data,w,h,x,y,frame_id=before['ep2_frames']&1023,mode=3),timeout=5000)
        wait_for(dev,'ep2_frames',before['ep2_frames']+1)
        return wait_display(dev)
    try:
        start=stats(dev);time.sleep(.2)
        assert stats(dev)['ep1_frames']==start['ep1_frames'],'Pause IDD MI_00 first'
        set_profile(dev,0)
        report['initial']=stats(dev)
        decoder=profile(dev)
        rtl=decoder['jpeg_rtl']==1
        assert decoder['neon']==int(not rtl)
        report['jpeg_decoder']='pl-rtl' if rtl else 'neon'
        w,h=start['width'],start['height'];source=gradient(w,h) if rtl else fixture(w,h)
        variants=[('420_q80',source,{'subsampling':2,'quality':80}),
                  ('422_q95',source,{'subsampling':1,'quality':95}),
                  ('444_q90',source,{'subsampling':0,'quality':90}),
                  ('grayscale',source.convert('L'),{'quality':85})]
        progressive=out/'progressive.jpg'
        if rtl:
            source.save(progressive,subsampling=2,quality=80,progressive=True)
        else:
            variants.append(('progressive',source,{'subsampling':2,'quality':80,'progressive':True}))
        for name,im,options in variants:
            path=out/(name+'.jpg');im.save(path,**options);data=path.read_bytes()
            expected=Image.open(io.BytesIO(data)).convert('RGB')
            s=send(data,w,h)
            actual_data=read_ddr(s['front'],w,h,out/(name+'.bgr'))
            actual=Image.frombytes('RGB',(w,h),actual_data,'raw','BGR')
            diff=ImageChops.difference(expected,actual)
            max_error=max(v[1] for v in diff.getextrema())
            mean_error=sum(diff.tobytes())/(w*h*3)
            maximum,mean=(8,2) if rtl else (3,.25)
            assert max_error<=maximum and mean_error<=mean,(name,max_error,mean_error)
            actual.save(out/(name+'.png'))
            item={'name':name,'jpeg_bytes':len(data),'max_channel_error':max_error,'mean_channel_error':mean_error,
                  'ddr_sha256':hashlib.sha256(actual_data).hexdigest(),'stats':s,'profile':profile(dev)}
            report['images'].append(item);save();print(name,'PASS',max_error,mean_error,flush=True)
        # A non-aligned rectangle verifies row addressing and preservation outside the JPEG.
        rw,rh,x,y=127,83,13,17;patch=gradient(rw,rh) if rtl else fixture(rw,rh)
        path=out/'rectangle.jpg';patch.save(path,quality=90,subsampling=0)
        before_data=actual_data
        s=send(path.read_bytes(),rw,rh,x,y)
        actual_data=read_ddr(s['front'],w,h,out/'rectangle.bgr')
        expected=Image.frombytes('RGB',(w,h),before_data,'raw','BGR')
        expected.paste(Image.open(path).convert('RGB'),(x,y))
        actual=Image.frombytes('RGB',(w,h),actual_data,'raw','BGR')
        error=max(v[1] for v in ImageChops.difference(expected,actual).getextrema())
        assert error<=(4 if rtl else 3),error
        report['images'].append({'name':'rectangle','max_channel_error':error});save()
        # Broken images never replace the displayed frame; next valid JPEG still works.
        valid=(out/'420_q80.jpg').read_bytes()
        cases=[('truncated',valid[:-20],w,h),('bad entropy',b'\xff\xd8'+b'garbage'*16+b'\xff\xd9',w,h),
               ('SOF/header dimensions mismatch',valid,w-1,h),('empty JPEG',b'\xff\xd8\xff\xd9',w,h)]
        if rtl:
            cases.append(('progressive JPEG',progressive.read_bytes(),w,h))
            # Preserve EOI so the corrupted scan reaches RTL and fails after
            # it has already issued writes to the unpublished frame buffer.
            cases.append(('premature EOI',valid[:-43]+b'\xff\xd9',w,h))
        for name,data,cw,ch in cases:
            before=stats(dev)
            dev.write(2,frame(data,cw,ch,mode=3),timeout=5000)
            s=wait_for(dev,'bad',before['bad']+1)
            assert s['ep2_frames']==before['ep2_frames'] and s['front']==before['front'],(name,s)
            report['negative_tests'].append(name)
            send(valid,w,h)
        set_profile(dev,2)
        report['stream']=benchmark(dev,valid,3,300,1,args.fps)
        report['stream']['profile']=profile(dev)
        set_profile(dev,2)
        report['unpaced']=benchmark(dev,valid,3,128,8,0)
        report['unpaced']['profile']=profile(dev)
        report['final']=stats(dev);report['passed']=True;save()
        print(json.dumps({k:v for k,v in report.items() if k not in ['images','initial','final']},indent=2))
    finally:
        save();set_profile(dev,2);usb.util.dispose_resources(dev)


if __name__=='__main__': main()
