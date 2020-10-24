import os
import sys
import time
import re
import glob
import json
import argparse
import subprocess
from multiprocessing import Pool
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TASKS = []
HOST = {
    "host.local": {
        "ip": "127.0.0.1",
        "vtm.base": "/home/faymek/VTM"
    },
    "host.enc": {
        "ip": "172.16.7.84",
        "vtm.base": "/home/enc/faymek/VTM",
        "hpm.base": "/home/enc/faymek/hpm-phase-2"
    },
    "host.4gpu": {
        "ip": "10.243.65.72"
    }
}

TRANSLATE = {}
LOG_KEYS = {
    "VTM": ['Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Time'],
    "HM": ['Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Time'],
    "HPM": ['Y-PSNR', 'U-PSNR', 'V-PSNR', 'Y-MSSSIM', 'Bits', 'Bitrate', 'Frames', 'Time']
}

META = {
    "InputBitDepth": "8",
    "InputChromaFormat": "",
    "FrameRate": "",
    "SourceWidth": "",
    "SourceHeight": "",
    "AllFrames": "",
    "PixelFormat": ""
}


class BaseConf:
    def __init__(self):
        pass


def post(addr, pf, base=None):
    request = Request(Conf.baseurl+addr, urlencode(pf).encode())
    return urlopen(request).read().decode()


def get(addr):
    request = Request(Conf.baseurl+addr)
    return urlopen(request).read().decode()


# return status curframe results
def log_vtm(fn):
    with open(fn, "r") as f:
        lines = list(f.readlines())
        nline = len(lines)
        if nline < 10:
            return "wait", 0, None
        elif lines[-2] and lines[-2].split()[0] == "finished":
            values = lines[-4].split()
            values.append(lines[-1].split()[2])  # Total Time
            return "finish", nline-15, values
        else:
            return "excute", nline-10, None


def log_hm(fn):
    with open(fn, "r") as f:
        lines = list(f.readlines())
        nline = len(lines)
        if nline < 68:
            return "wait", 0, None
        elif lines[-1] and lines[-1].split()[-1] == "sec.":
            values = lines[-21].split()
            values.append(lines[-1].split()[2])  # Total Time
            return "finish", nline-92, values
        else:
            return "excute", nline-68, None


def log_hpm(fn):
    with open(fn, "r") as f:
        lines = list(f.readlines())
        nline = len(lines)
        if lines[0].startswith("Note"):
            nline -= 1
        if nline < 48:
            return "wait", 0, None
        elif lines[-2] and lines[-2].split()[-1] == "frames/sec":
            cl = lines[-12:-6] + lines[-5:-4]
            values = [v.split()[-1] for v in cl]
            values.append(lines[-4].split()[-2])  # Total Time
            return "finish", nline-62, values
        else:
            return "excute", nline-48, None


def log_getEnctype(fn):
    enctype = ""
    with open(fn, "r") as f:
        lines = list(f.readlines())
        nline = len(lines)
        if nline > 1:
            if lines[1].startswith("VVCSoftware: VTM Encoder Version"):
                enctype = "VTM"
            elif lines[1].startswith("HM software: Encoder Version"):
                enctype = "HM"
            elif lines[1].startswith("HPM version"):
                enctype = "HPM"
    return enctype


def log_adapter(fn, enctype=""):
    if not enctype:  # interpret
        enctype = log_getEnctype(fn)
    dict_func = {
        "VTM": log_vtm,
        "HM": log_hm,
        "HPM": log_hpm
    }
    return dict_func[enctype](fn)


def readyuv420(filename, bitdepth, W, H):
    if bitdepth == '8':
        bytesPerPixel = 1
    elif bitdepth == '10':
        bytesPerPixel = 2
    pixelsPerFrame = int(H) * int(W) * 3 // 2
    bytesPerFrame = bytesPerPixel * pixelsPerFrame
    fp = open(filename, 'rb')
    fp.seek(0, 2)
    totalframe = fp.tell() // bytesPerFrame
    return str(totalframe)


def meta_fn(fn, calcFrames=False):
    meta = META.copy()
    items = fn[:-4].split("_")[1:]
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
        meta["AllFrames"] = readyuv420(
            fn, meta["InputBitDepth"], meta["SourceWidth"], meta["SourceHeight"])
    if not meta["InputChromaFormat"]:
        meta["InputChromaFormat"] = Conf.cf
    meta["PixelFormat"] = "yuv{}p".format(meta["InputChromaFormat"])
    if meta["InputBitDepth"] == "10":
        meta["PixelFormat"] = meta["PixelFormat"]+"10le"
    return meta


def getabspath(s):
    return os.path.abspath(os.path.expanduser(s))


def yuvopt(fn):
    opt = "-i %s" % fn
    if fn.endswith(".yuv"):
        yuvinfo = " -s {SourceWidth}x{SourceHeight} -pix_fmt {PixelFormat} "
        opt = yuvinfo.format(**meta_fn(fn)) + opt
    return opt


def metric(enc, ref, mode='psnr', onlykey=False):
    shellmap = {
        "psnr": "ffmpeg -v info %s %s -filter_complex psnr -f null -y - 2>&1",
        "ssim": "ffmpeg -v info %s %s -filter_complex ssim -f null -y - 2>&1",
        "vmaf": "ffmpeg -v info %s %s -filter_complex libvmaf -f null -y - 2>&1",
    }
    cmd = shellmap[mode] % (yuvopt(enc), yuvopt(ref))
    line = list(os.popen(cmd).readlines())[-1]
    line = line.replace("score: ", "vmaf:")
    items = line[:-1].split(' ')[4:]
    if onlykey:
        return [item.split(':')[0] for item in items if ':' in item]
    data = [item.split(':')[1] for item in items if ':' in item]
    info = ""
    if "PSNR" in line:
        info = ' '.join(items[:3])
    elif "SSIM" in line:
        info = ' '.join(items[0:5:2])
    elif "VMAF" in line:
        info = items[-1]
    return data, info


def measure(inpath, outpath, mode='psnr'):
    results = []
    inglob = inpath + "/*"
    for fin in sorted(glob.glob(inglob)):
        inname = '_'.join(os.path.basename(fin).split('_')[:-1])
        outglob = "{}/{}*".format(outpath, inname)
        for fout in sorted(glob.glob(outglob)):
            outname = os.path.basename(fout)
            data, info = metric(fin, fout, mode)
            results.append([outname]+data)
            print("%-48s %s" % (outname, info))
    with open("measure.csv", "w") as f:
        if results:
            keys = metric(fin, fout, mode, onlykey=True)
            f.write('fn,'+','.join(keys)+'\n')
            f.writelines([','.join(item)+'\n' for item in results])
        else:
            print("No matches.")


def yuv1stframe(inpath, outpath):
    shell = "ffmpeg -y -f rawvideo -video_size {SourceWidth}x{SourceHeight} -pixel_format {PixelFormat} -i {fin} -vframes 1 {fout}.yuv"
    inglob = "{inpath}/*.yuv".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{outpath}/{inname}".format(outpath=outpath, inname=inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)


def convert(inpath, outpath, mode="png2yuv"):
    fmtmap = {
        "png2yuv": "ffmpeg -y -i {fin} -pix_fmt {PixelFormat} {fout}.yuv",
        "png2rgb": "ffmpeg -y -i {fin} -pix_fmt rgb24 {fout}.rgb",
        "yuv2png": "ffmpeg -y -f rawvideo -pixel_format {PixelFormat} -video_size {SourceWidth}x{SourceHeight} -i {fin} -vframes 1 {fout}.png",
        "rgb2png": "ffmpeg -y -f rawvideo -pixel_format rgb24 -video_size {SourceWidth}x{SourceHeight} -i {fin} -vframes 1 {fout}.png"
    }
    shell = fmtmap[mode]
    fmt1, fmt2 = mode.split('2')
    inglob = "{}/*.{}".format(inpath, fmt1)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        fout = "{}/{}".format(outpath, inname)
        meta = meta_fn(fin)
        cmd = shell.format(fin=fin, **meta, fout=fout)
        print(cmd)
        TASKS.append(cmd)


def hpmenc(inpath, outpath, qplist=[]):
    base = Conf.host["hpm.base"]
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
            fout = "{}/{}_{:02d}".format(outpath, inname, qp)
            cmd = shell.format(base=base, fin=fin, **meta, fout=fout, qp=qp)
            #print(cmd)
            TASKS.append(cmd)


def vtmenc(inpath, outpath, qplist=[56]):
    base = Conf.host["vtm.base"]
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
            fout = "{}/{}_{:02d}".format(outpath, inname, qp)
            cmd = shell.format(base=base, fin=fin, **meta, fout=fout, qp=qp)
            TASKS.append(cmd)


def vtmencrgb(inpath, outpath, qplist=[56]):
    base = Conf.host["vtm.base"]
    shell = ' '.join([
        "{base}/bin/EncoderAppStatic",
        "-c {base}/cfg/encoder_intra_vtm.cfg",
        "-i {fin} -wdt {SourceWidth} -hgt {SourceHeight} -fr 30 -f 1 -q {qp} --InputChromaFormat=444",
        "--InputBitDepth={InputBitDepth} --OutputBitDepth={InputBitDepth} --ConformanceMode",
        "--InputColourSpaceConvert=RGBtoGBR --SNRInternalColourSpace=1 --OutputInternalColourSpace=0",  # improve ~0.05dB
        "-b {fout}.bin -o {fout}.rgb > {fout}.log"
    ])
    inglob = "{inpath}/*.rgb".format(inpath=inpath)
    for fin in glob.glob(inglob):
        inname = os.path.basename(fin).split('.')[0]
        meta = meta_fn(fin)
        for qp in qplist:
            fout = "{}/{}_{:02d}".format(outpath, inname, qp)
            cmd = shell.format(base=base, fin=fin, **meta, fout=fout, qp=qp)
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
        fout = "{outpath}/{inname}".format(outpath=outpath, inname=inname)
        meta = meta_fn(fin)
        meta["TrueWidth"] = -(int(meta['SourceWidth'])//-8)*8
        meta["TrueHeight"] = -(int(meta['SourceHeight'])//-8)*8
        cmd = shell.format(fin=fin, **meta, fout=fout)
        TASKS.append(cmd)


def show(inpath, outpath):
    print('--- Analyze encode logs. ---')
    tasks = sorted(glob.glob(inpath+"/*.log"))
    count = {"wait": 0, "excute": 0, "finish": 0}
    enctype = log_getEnctype(tasks[0])
    results = []
    for fn in tasks:
        inname = os.path.basename(fn).split('.')[0]
        status, cur, result = log_adapter(fn, enctype)
        if result:
            results.append([inname]+result)
        count[status] += 1
        if status != "finish":
            print("[{}] {}.log".format(status, inname))
    print('Total %d tasks, %d wait, %d excute, %d finish.' %
          (len(tasks), count["wait"], count["excute"], count["finish"]))
    with open("enclog.csv", "w") as f:
        f.write('fn,'+','.join(LOG_KEYS[enctype])+"\n")
        for result in results:
            f.write(','.join(result)+'\n')
    print("enclog.csv generated.")


def netop(inpath, outpath, op):
    cmds = [
        "rm /home/medialab/faymek/iir/datasets/cli/*",
        "mv %s/* /home/medialab/faymek/iir/datasets/cli/" % inpath,
        "/home/medialab/miniconda3/envs/iir/bin/python /home/medialab/faymek/iir/codes/test_%s.py -opt ~/faymek/iir/codes/options/test/%s.yml" % (
            op[-1], op),
        "mv /home/medialab/faymek/iir/results/test/%s/* %s/" % (op, outpath)
    ]
    TASKS.extend(cmds)


def call_script(script):
    desc = script.split('/')[-1]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] start :" % stamp, desc)
    re = subprocess.run(script, shell=True, capture_output=True)
    # print(re.stderr)
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] finish:" % stamp, desc)


if __name__ == '__main__':
    funcMap = {'yuv1stframe': yuv1stframe, 'netop': netop,
               'hpmenc': hpmenc, 'hpmcrop': hpmcrop,
               'vtmenc': vtmenc, 'vtmencrgb': vtmencrgb, 'show': show}

    parser = argparse.ArgumentParser(
        description='Media Encoding Batch Utils. Copyright @ 2016-2020')
    parser.add_argument("verb")
    parser.add_argument("inpath")
    parser.add_argument("outpath", default="./")
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
    parser.add_argument("--cf", type=str, default="420", choices=["420", "422", "444"],
                        help="chroma format")

    args = parser.parse_args()
    args.inpath = getabspath(args.inpath)
    args.outpath = getabspath(args.outpath)
    args.qps = eval(args.qps)
    Conf = BaseConf()
    Conf.cf = args.cf
    if args.host == "off":
        Conf.host = HOST["host.local"]
    else:
        Conf.host = HOST["host."+args.host]

    os.makedirs(args.outpath, exist_ok=True)
    if '2' in args.verb:
        convert(args.inpath, args.outpath, args.verb)
    elif args.verb in ['psnr', 'ssim', 'vmaf']:
        measure(args.inpath, args.outpath, args.verb)
        sys.exit()
    elif args.verb in ['show']:
        funcMap[args.verb](args.inpath, args.outpath)
        sys.exit()
    elif args.verb in ['hpmenc', 'vtmenc', 'vtmencrgb']:
        funcMap[args.verb](args.inpath, args.outpath, args.qps)
    elif args.verb == 'netop':
        netop(args.inpath, args.outpath, args.op)
    else:
        funcMap[args.verb](args.inpath, args.outpath)
    with open("tasks.json", "w") as f:
        json.dump(TASKS, f, indent=4)

    if args.host == "off":  # run instant, without server
        print('Excute the %d shell script with %d process.\n' %
              (len(TASKS), args.core))
        RunPool = Pool(args.core)
        RunPool.map_async(call_script, TASKS)
        RunPool.close()
        RunPool.join()

    else:  # server mode, check server
        Conf.baseurl = 'http://{}:42024'.format(Conf.host["ip"])
        try:
            print("Host %s : " % args.host+get("/id"))
        except:
            print("Host %s : Server Not Running!" % args.host)
            sys.exit()

        remdir = get("/path")
        key = remdir.split('/')[-1]
        print("Job key: %s" % key)
        remin = remdir + "/inpath"
        remout = remdir + "/outpath"

        if args.host != "local":
            for i in range(len(TASKS)):
                TASKS[i] = TASKS[i].replace(
                    args.inpath, remin).replace(args.outpath, remout)
            with open("tasks.json", "w") as f:
                json.dump(TASKS, f, indent=4)
            print("\n--- SCP uploading ---\n")
            os.system("scp tasks.json {}:{}/".format(args.host, remdir))
            os.system("scp -r {}/* {}:{}/".format(args.inpath, args.host, remin))
        else:
            os.system("cp tasks.json {}/".format(remdir))

        pf = {'fpath': remdir+"/tasks.json", 'core': args.core, 'key': key}
        print(post("/add", pf))
        while True:
            left = get("/busy?"+key)
            stamp = time.strftime("%m-%d %H:%M", time.localtime())
            print("- [%s]: %s jobs left" % (stamp, left))
            if left == "0":
                break
            time.sleep(args.wait)

        if args.host != "local":
            print("\n--- SCP downloading ---\n")
            os.system("scp -r {}:{}/* {}".format(args.host, remout, args.outpath))

    print("--- Job done. ---")
