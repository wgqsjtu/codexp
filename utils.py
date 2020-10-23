#%%
import os, sys, time
import re, glob, json
import argparse
import subprocess
from multiprocessing import Pool
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASEPF = "420"

def post(addr, pf, base=None):
    
    request = Request(base_url+addr, urlencode(pf).encode())
    return urlopen(request).read().decode()

def get(addr):
    request = Request(base_url+addr)
    return urlopen(request).read().decode()

LOG_KEYS = {
    "PSNR": ['y', 'u', 'v', 'avg', 'min', 'max'],
    "HM": ['Total Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Total Time'],
    "HPM": ['PSNR Y(dB)', 'PSNR U(dB)', 'PSNR V(dB)', 'MsSSIM_Y', 'Total bits(bits)', 'bitrate(kbps)', 'Encoded frame count', 'Total encoding time']
}

meta_dict =  {
    "InputBitDepth": "8",
    "InputChromaFormat": "",
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
    if not meta["InputChromaFormat"]:
        meta["InputChromaFormat"] = BASEPF
    meta["PixelFormat"] = "yuv{}p".format(meta["InputChromaFormat"])
    if meta["InputBitDepth"] == "10":
        meta["PixelFormat"] = meta["PixelFormat"]+"10le"
    return meta
    
def getabspath(s):
    return os.path.abspath(os.path.expanduser(s))\

def yuvopt(fn):
    opt = "-i %s"%fn
    if fn.endswith(".yuv"):
        yuvinfo = " -s {SourceWidth}x{SourceHeight} -pix_fmt {PixelFormat} "
        opt = yuvinfo.format(**meta_fn(fn)) + opt
    return opt

def psnr(enc, ref):
    cmd = 'ffmpeg -v info %s %s -filter_complex psnr -f null -y - 2>&1' % (yuvopt(enc), yuvopt(ref))
    ret = []
    for line in os.popen(cmd).readlines():
        if "PSNR" in line:
            tmp = line[:-1].split(' ')
            info = ' '.join(tmp[4:7])
            data = [item.split(':')[1] for item in tmp if ':' in item]
    return info, data

def ssim(enc, ref):
    cmd = 'ffmpeg -v info %s %s -filter_complex ssim -f null -y - 2>&1' % (yuvopt(enc), yuvopt(ref))
    ret = []
    for line in os.popen(cmd).readlines():
        if "SSIM" in line:
            tmp = line[:-1].split(' ')
            ret = tmp[4:]
            #ret = [item.split(':')[1] for item in tmp if ':' in item]
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

def measure(inpath, outpath, metric='psnr'):
    #for ext in ('*.yuv', '*.png', '*.jpg'):
    #    files.extend(glob(join("path/to/dir", ext)))
    inglob = inpath + "/*"
    for fin in glob.glob(inglob):
        inname = '_'.join(os.path.basename(fin).split('_')[:-1])
        outglob = "{outpath}/{inname}*".format(outpath=outpath,inname=inname) 
        results = []
        for fout in sorted(glob.glob(outglob)):
            outname = os.path.basename(fout)
            info, data = psnr(fin,fout)
            results.append(data)
            print("%-48s %s"%(outname, info))
        if not results:
            print("No matches.")
        with open("measure.csv", "w") as f:
            f.write('fn,'+','.join(LOG_KEYS["PSNR"])+'\n')
            f.writelines([outname+','+','.join(item)+'\n' for item in results])


            


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
        #print(cmd)
        TASKS.append(cmd)


def yuv2png(inpath, outpath):
    shell = "ffmpeg -y -f rawvideo -video_size {SourceWidth}x{SourceHeight} -pixel_format {PixelFormat} -i {fin} -vframes 1 {fout}.png"
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath,inname=inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        print(cmd)
        TASKS.append(cmd)


def hpmenc(inpath, outpath, qplist=[]):
    base = "/home/enc/faymek/hpm-phase-2" # path of HPM encoder
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

def vtmenc(inpath, outpath, qplist=[56]):
    base = "/home/enc/faymek/VTM" # path of HPM encoder
    if not base:
        print("please set encoder path")
        return
    shell = ' '.join([
        "{base}/bin/EncoderAppStatic",
        "-c {base}/cfg/encoder_intra_vtm.cfg",
        "-i {fin} -wdt {SourceWidth} -hgt {SourceHeight} -fr 30 -f 1 -q {qp} --InputChromaFormat={InputChromaFormat}",
        "--InputBitDepth={InputBitDepth} --OutputBitDepth={InputBitDepth} --ConformanceMode ",
        "-b {fout}.bin -o {fout}.yuv > {fout}.log"
    ])
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        meta = meta_fn(fin)
        for qp in qplist:
            fout = "{outpath}/{inname}_{qp}".format(outpath=outpath,inname=inname,qp=qp)
            cmd = shell.format(base=base,fin=fin, **meta, fout=fout, qp=qp)
            TASKS.append(cmd)


def hpmcrop(inpath, outpath):
    shell = ' '.join([
        "ffmpeg -y -f rawvideo -pixel_format yuv420p10le -video_size {TrueWidth}x{TrueHeight}",
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

def netop(inpath, outpath, op):
    cmds = [
        "rm /home/medialab/faymek/iir/datasets/cli/*",
        "mv %s/* /home/medialab/faymek/iir/datasets/cli/"%inpath,
        "/home/medialab/miniconda3/envs/iir/bin/python /home/medialab/faymek/iir/codes/test_%s.py -opt ~/faymek/iir/codes/options/test/%s.yml"%(op[-1], op),
        "mv /home/medialab/faymek/iir/results/test/%s/* %s/"%(op, outpath)
    ]
    TASKS.extend(cmds) 


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
    funcMap = {'yuv1stframe':yuv1stframe,'topng': yuv2png, 'toyuv': png2yuv,
                 'hpmenc': hpmenc, 'hpmcrop': hpmcrop, 'psnr': measure, 'netop':netop, 'vtmenc':vtmenc}

    parser = argparse.ArgumentParser(
        description='Media Encoding Utils. Copyright @ 2016-2020')
    parser.add_argument(
        "verb", choices=list(funcMap.keys()))
    parser.add_argument("inpath")
    parser.add_argument("outpath")
    parser.add_argument("--host", type=str, default="off",
                        help="run in which machine")
    parser.add_argument("--core", type=int, default=4,
                        help="run with n concurrent process")
    parser.add_argument("--wait", type=int, default=5,
                        help="check for every n seconds")
    parser.add_argument("--qps", type=str, default="56,",
                        help="encode qp list")
    parser.add_argument("--op", type=str, default="x2d", choices=["x2d", "x2u", "x4d", "x4u"],
                        help="network operation")
    parser.add_argument("--pf", type=str, default="420", choices=["420", "422", "444"],
                        help="pixel format")
    

    args = parser.parse_args()
    args.inpath = getabspath(args.inpath)
    args.outpath = getabspath(args.outpath)
    args.qps = eval(args.qps)
    BASEPF = args.pf

    os.makedirs(args.outpath, exist_ok=True)
    if args.verb in ['hpmenc', 'vtmenc']:
        funcMap[args.verb](args.inpath, args.outpath, args.qps)
    elif args.verb == 'netop':
        netop(args.inpath, args.outpath, args.op)
    else:
        funcMap[args.verb](args.inpath, args.outpath)
    with open("tasks.json","w") as f:
        json.dump(TASKS, f, indent=4)
    
    if args.host == "off": # run instant, without server
        print('Excute the %d shell script with %d process.\n' % \
            (len(TASKS), args.core))
        RunPool = Pool(args.core)
        RunPool.map_async(call_script, TASKS)
        RunPool.close()
        RunPool.join()

    else:  # server mode, check server
        iptables = {
            "local": "127.0.0.1",
            "enc": "172.16.7.84",
            "4gpu": "10.243.65.72",
        }
        base_url = 'http://{}:42024'.format(iptables[args.host])
        try:
            print("Host %s : "%args.host+get("/id"))
        except:
            print("Host %s : Server Not Running!"%args.host)
            sys.exit()

        remdir = get("/path")
        key = remdir.split('/')[-1]
        print("Job key: %s"%key)
        remin = remdir + "/inpath"
        remout = remdir + "/outpath"
        
        if args.host != "local":
            for i in range(len(TASKS)):
                TASKS[i] = TASKS[i].replace(args.inpath, remin).replace(args.outpath, remout)
            with open("tasks.json","w") as f:
                json.dump(TASKS, f, indent=4)
            print("\n--- SCP uploading ---\n")
            os.system("scp tasks.json {}:{}/".format(args.host,remdir))
            os.system("scp -r {}/* {}:{}/".format(args.inpath,args.host,remin))
        else:
            os.system("cp tasks.json {}/".format(remdir))
        
        pf = {'fpath':remdir+"/tasks.json",'core':args.core, 'key':key}
        print(post("/add", pf))
        while True:
            left = get("/busy?"+key)
            stamp = time.strftime("%m-%d %H:%M", time.localtime())
            print("- [%s]: %s jobs left"%(stamp, left))
            if left == "0":
                break
            time.sleep(args.wait)
        
        if args.host != "local":
            print("\n--- SCP downloading ---\n")
            os.system("scp -r {}:{}/* {}".format(args.host,remout,args.outpath))

    print("\n--- Job done. ---")

