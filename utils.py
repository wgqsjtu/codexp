#%%
import os, sys, time
import re, glob, json
import argparse
import subprocess
from multiprocessing import Pool
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def post(addr, pf):
    request = Request(base_url+addr, urlencode(pf).encode())
    return urlopen(request).read().decode()

def get(addr):
    request = Request(base_url+addr)
    return urlopen(request).read().decode()

FFMPEG_KEYS = {
    "PSNR": ['y', 'u', 'v', 'avg', 'min', 'max'],
    "HM": ['Total Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Total Time'],
    "HPM": ['PSNR Y(dB)', 'PSNR U(dB)', 'PSNR V(dB)', 'MsSSIM_Y', 'Total bits(bits)', 'bitrate(kbps)', 'Encoded frame count', 'Total encoding time']
}

meta_dict =  {
    "InputBitDepth": "8",
    "InputChromaFormat": "420",
    "FrameRate": "",
    "SourceWidth": "",
    "SourceHeight": "",
    "AllFrames": "",
    "PixelFormat": ""
}

TASKS = []

def readyuv420(filename, bitdepth, W, H):
    if bitdepth == '8':
        bytesPerPixel = 1
    elif bitdepth == '10':
        bytesPerPixel = 2
    pixelsPerFrame = int(H) * int(W) * 3 // 2
    bytesPerFrame = bytesPerPixel * pixelsPerFrame
    fp = open(filename, 'rb')
    fp.seek(0,2)
    totalframe = fp.tell() // bytesPerFrame
    return str(totalframe)

def meta_fn(fn, calcFrames=False):
    filename = fn
    meta = meta_dict.copy()
    items = filename[:-4].split("_")[1:]
    for item in items:
        if re.match(r"^[0-9]*x[0-9]*$", item):
            meta["SourceWidth"], meta["SourceHeight"] = item.split("x")
        elif re.match(r"^[0-9]*fps$", item):
            meta["FrameRate"] = item.split("fps")[0]
        elif re.match(r"^[0-9]*bit", item):
            meta["InputBitDepth"] = item.split("bit")[0]
        elif item in ["444", "440", "422", "411", "420", "410", "311"]:
            meta["InputChromaFormat"] = item
        elif re.match(r"^[0-9]*$", item):
            meta["FrameRate"] = item
    if calcFrames:
        meta["AllFrames"] = readyuv420(fn, meta["InputBitDepth"], meta["SourceWidth"], meta["SourceHeight"])
    meta["PixelFormat"] = "yuv420p10le" if meta["InputBitDepth"] == "10" else "yuv420p"
    return meta
    

def ffmpegmeasure(enc, ref):
    yuvopt = " -s {SourceWidth}x{SourceHeight} -pix_fmt {PixelFormat} "
    opt_enc = "-i %s"%enc
    if enc.endswith(".yuv"):
        opt_enc = yuvopt.format(**meta_fn(enc)) + opt_enc
    opt_ref = "-i %s"%ref
    if enc.endswith(".yuv"):
        opt_ref = yuvopt.format(**meta_fn(ref)) + opt_ref

    cmd = 'ffmpeg -v info %s %s -filter_complex psnr -f null -y - 2>&1' % (opt_enc, opt_ref)
    print(cmd)
    ret = []
    for line in os.popen(cmd).readlines():
        if "PSNR" in line:
            tmp = line[:-1].split(' ')
            ret = [item.split(':')[1] for item in tmp if ':' in item]
    return ret

def psnr(enc_yuv, raw_yuv,w, h, bitdepth):
    w = str(w)
    h = str(h)
    fmt = "yuv420p10le" if bitdepth == 10 else "yuv420p"
    cmd = 'ffmpeg -v info -s %sx%s -pix_fmt %s -i %s -s %sx%s -pix_fmt %s -i %s -filter_complex psnr -f null -y - 2>&1' % (w,h,fmt,enc_yuv,w,h,fmt,raw_yuv)
    r = os.popen(cmd).readlines()
    ret = []
    for line in r:
        if "PSNR" in line:
            tmp = line[:-1].split(' ')
            for item in tmp:
                if ':' in item:
                    ret.append(item.split(':')[1])
    return ret

def ssim(enc_yuv, raw_yuv,w, h):
    w = str(w)
    h = str(h)
    cmd = 'ffmpeg -v info -s %sx%s -i %s -s %sx%s -i %s -filter_complex ssim -f null -y - 2>&1' % (w,h,enc_yuv,w,h,raw_yuv)
    r = os.popen(cmd).readlines()
    ret = []
    for line in r:
        if "SSIM" in line:
            tmp = line[:-1].split(' ')
            for item in tmp:
                if ':' in item:
                    ret.append(item.split(':')[1])
    return ret
            
def vmaf(enc_yuv, raw_yuv,w, h):
    w = str(w)
    h = str(h)
    cmd = 'vmafossexec yuv420p %s %s %s %s vmaf_v0.6.1.pkl'%(w,h,raw_yuv,enc_yuv)
    r = os.popen(cmd).readlines()
    ret = ''
    for line in r:
       if '=' in line:
          ret = line[:-1].split()[-1]
    return ret

def yuv1stframe(inpath, outpath):
    shell = "ffmpeg -y -f rawvideo -video_size {SourceWidth}x{SourceHeight} -pixel_format {PixelFormat} -i {fin} -vframes 1 {fout}.yuv"
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath,inname=inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)


def png2yuv(inpath, outpath):
    shell = "ffmpeg -y -i {fin} -pix_fmt {PixelFormat} {fout}.yuv"
    inglob = "{inpath}/*.png".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath,inname=inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)


def yuv2png(inpath, outpath):
    shell = "ffmpeg -y -f rawvideo -video_size {SourceWidth}x{SourceHeight} -pixel_format {PixelFormat} -i {fin} -vframes 1 {fout}.png"
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath,inname=inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)


def hpmenc(inpath, outpath, qplist=[]):
    base = "Some" # path of HPM encoder
    if not base:
        print("please set encoder path")
        return
    shell = ' '.join([
        "{base}/bin/app_encoder",
        "--config {base}/cfg/encode_AI.cfg",
        "-i {fin} -w {SourceWidth} -h {SourceHeight} -z 50 -f 1 -d {InputBitDepth} -q {qp} ",
        "-o {fout}.bin -r {fout}.yuv > {fout}.log"
    ])
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        meta = meta_fn(fin)
        for qp in qplist:
            fout = "{outpath}/{inname}_{qp}".format(outpath=outpath,inname=inname,qp=qp)
            cmd = shell.format(base=base,fin=fin, **meta, fout=fout, qp=qp)
            #print(cmd)
            TASKS.append(cmd)


def hpmcrop(inpath, outpath):
    shell = ' '.join([
        "ffmpeg -y -f rawvideo -pixel_format yuv420p -video_size {TrueWidth}x{TrueHeight}",
        "-i {fin} -filter:v 'crop={SourceWidth}:{SourceHeight}:0:0' -vframes 1",
        "-f rawvideo -pix_fmt {PixelFormat} -s {SourceWidth}x{SourceHeight} {fout}.yuv"
    ])
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath,inname=inname)
        meta = meta_fn(fin)
        meta["TrueWidth"] = -(int(meta['SourceWidth'])//-8)*8
        meta["TrueHeight"] = -(int(meta['SourceHeight'])//-8)*8
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)

def call_script(script):
    desc = script.split('/')[-1]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] start :"%stamp, desc)
    #time.sleep(5)
    re = subprocess.run(script, shell=True, capture_output=True)
    # print(re.stderr)
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] finish:"%stamp, desc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Media Encoding Utils. Copyright @ 2016-2020')
    parser.add_argument(
        "verb", choices=['topng', 'toyuv', 'hpmenc', 'hpmcrop', 'yuv1stframe'])

    parser.add_argument("inpath")
    parser.add_argument("outpath")
    parser.add_argument("--host", type=str, default="local",
                        help="run in which machine")
    parser.add_argument("--core", type=int, default=4,
                        help="run with n concurrent process")
    

    args = parser.parse_args()
    dict_func = {'yuv1stframe':yuv1stframe,'topng': yuv2png, 'toyuv': png2yuv,
                 'hpmenc': hpmenc, 'hpmcrop': hpmcrop}

    os.makedirs(args.outpath, exist_ok=True)
    
    if args.host == "local":
        if args.verb == 'hpmenc':
            hpmenc(args.inpath, args.outpath, list(range(4,6)))
        else:
            dict_func[args.verb](args.inpath, args.outpath)
        print('Excute the %d shell script with %d process.\n' % \
                (len(TASKS), args.core))
        RunPool = Pool(args.core)
        RunPool.map_async(call_script, TASKS)
        RunPool.close()
        RunPool.join()
    else:
        iptables = {
            "enc": "172.16.7.84"
        }
        remip = iptables[args.host]
        base_url = 'http://{}:42024'.format(remip)

        try:
            print("Host %s > "%args.host+get("/id"))
        except:
            print("Host %s > Server Not Running."%args.host)
            sys.exit()

        remdir = get("/path")
        remin = remdir + "/inpath"
        remout = remdir + "/outpath"
        key = remdir.split('/')[-1]
        print("Job key: %s"%key)
        if args.verb == 'hpmenc':
            hpmenc(args.inpath, remout, list(range(4,6)))
        else:
            dict_func[args.verb](args.inpath, remout)
        for i in range(len(TASKS)):
            TASKS[i] = TASKS[i].replace(args.inpath, remin)

        print('Excute the %d shell script with %d process.' % \
                (len(TASKS), args.core))
        
        with open("tasks.json","w") as f:
            json.dump(TASKS, f, indent=4)
        print("\n--- SCP uploading ---\n")
        os.system("scp tasks.json {}:{}/".format(args.host,remdir))
        os.system("scp -r {}/* {}:{}/".format(args.inpath,args.host,remin))
        pf = {'fpath':remdir+"/tasks.json",'core':args.core, 'key':key}
        print(post("/add", pf))

        while True:
            left = get("/busy?"+key)
            stamp = time.strftime("%m-%d %H:%M", time.localtime())
            print("- [%s]: %s jobs left"%(stamp, left))
            if left == '0':
                break
            else:
                time.sleep(5)
        
        print("\n--- SCP downloading ---\n")
        os.system("scp -r {}:{}/* {}".format(args.host,remout,args.outpath))

        print("\n--- Job done. ---\n")

    
# %%

