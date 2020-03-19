# %%
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import sys
import os.path as op
import os
import subprocess
import re
import time
import json
from subprocess import check_call
from multiprocessing import Pool
import argparse
import shlex

base_url = 'http://127.0.0.1:42024' # Set destination URL here
post_fields = {'foo': 'bar'}     # Set POST fields here

def post(pf):
    request = Request(base_url+"/add", urlencode(pf).encode())
    json = urlopen(request).read().decode()
    print(json)

def get():
    request = Request(base_url+"/id")
    json = urlopen(request).read().decode()
    print(json)

init_conf_hm1620 = {
    "version": "HM 16.20",
    "basedir": "~/HM-16.20/",
    "enc": "./bin/TAppEncoderStatic",
    "seq": "~/data/",
    "out": "./test/out/",
    "cfg_pre": "./cfg/encoder_randomaccess_main10.cfg",
    "cfg_seq": "./test/cfg/",
    "mode": "",  # QP or RATE, override all exps
    "extra": "",
    "exps": [
        {
            "title": "endark qp",  # empty for auto
            "items": [],  # empty for auto
            "mode": "QP",  # or "RATE"
            "paras": [27, 32, 37, 42]
        }
    ]
}

init_conf_vtm7 = {
    "version": "VTM 7.0",
    "basedir": "~/VVCSoftware_VTM/",
    "enc": "./bin/EncoderAppStatic",
    "seq": "~/data/",
    "out": "./test/out/",
    "cfg_pre": "./cfg/encoder_randomaccess_vtm.cfg",
    "cfg_seq": "./test/cfg/",
    "mode": "",
    "extra": "",
    "exps": [
        {
            "title": "qp S5",
            "items": [
                "Campfire_1920x1080_30fps_10bit_420.yuv"
            ],
            "mode": "QPIF",
            "paras": [
                32.7,
                32.8
            ]
        }
    ]
}

def loadconf():
    if not op.exists("experiments.json"):
        print("experiments.json don't exist. Use init.")
        exit(0)
    with open("experiments.json", "r") as f:
        conf = json.load(f)
    return conf


def saveconf(conf):
    with open("experiments.json", "w") as f:
        json.dump(conf, f, indent=4)


def init(force=False):
    if op.exists("experiments.json") and not force:
        print("[ok] experiments.json already exists.")
        return
    print("[ok] experiments.json newly created.")
    with open("experiments.json", "w") as f:
        json.dump(init_conf_vtm7, f, indent=4)


def start(force=False):
    print('---Checking the json.---')
    init(force)
    conf = loadconf()

    print('\n---Checking the path.---')
    tmpdir = os.getcwd()
    basedir = op.expanduser(conf["basedir"])
    os.chdir(basedir)
    enc = op.abspath(op.expanduser(conf["enc"]))
    seq = op.abspath(op.expanduser(conf["seq"]))
    out = op.abspath(op.expanduser(conf["out"]))
    cfg_pre = op.abspath(op.expanduser(conf["cfg_pre"]))
    cfg_seq = op.abspath(op.expanduser(conf["cfg_seq"]))
    os.chdir(tmpdir)
    conf["path"] = {"encoder": enc, "sequence": seq,
                    "output": out, "cfg_pre": cfg_pre, "cfg_seq": cfg_seq}
    saveconf(conf)
    print("[ok] Absolute path generated in experiments.json")

    print('\n---Checking the cfg.---')
    os.makedirs(out, exist_ok=True)
    if op.exists(cfg_seq) and os.listdir(seq):
        print("[ok] Cfg of sequence exists.")
    else:
        print("[warning] Cfg of sequence do not exists! Use fix.")
        if force:
            fix()

    tasks()
    with open('start.lock','w') as f:
        f.write("experiments.json")


def fix():
    conf = loadconf()
    seq = conf["path"]["sequence"]
    cfg_seq = conf["path"]["cfg_seq"]

    print("--Try to create cfg of sequence.--")
    conf["yuvmeta"] = {}
    os.makedirs(cfg_seq, exist_ok=True)
    for filename in os.listdir(seq):
        if not filename.endswith(".yuv"):
            continue
        meta = {
            "InputFile": op.join(seq, filename),
            "InputBitDepth": "8",
            "InputChromaFormat": "420",
            "FrameRate": "30",
            "SourceWidth": "0",
            "SourceHeight": "0",
            "FramesToBeEncoded": "0",
            "Level": "3.1"
        }
        for item in filename.split("_"):
            if re.match(r"^[0-9]*x[0-9]*$", item):
                meta["SourceWidth"], meta["SourceHeight"] = item.split("x")
            elif re.match(r"^[0-9]*fps$", item):
                meta["FrameRate"] = item.split("fps")[0]
            elif re.match(r"^[0-9]*bit", item):
                meta["InputBitDepth"] = item.split("bit")[0]
            elif item in ["444", "440", "422", "411", "420", "410", "311"]:
                meta["InputChromaFormat"] = item
        meta["IntraPeriod"] = "32" if meta["FrameRate"] == "30" else "64"
        meta["FramesToBeEncoded"] = "300" if meta["FrameRate"] == "60" else "150"
        meta["Level"] = "6.2" if meta["InputBitDepth"] == "10" else "3.1"
        conf["yuvmeta"][filename] = meta

        cfgname = filename.replace(".yuv", ".cfg")
        with open(op.join(cfg_seq, cfgname), "w") as autocfg:
            for key, value in meta.items():
                autocfg.write('{0:30}: {1}\n'.format(key, value))

    saveconf(conf)
    print("[ok] Auto parsing finished. Please check.")


def tasks():
    conf = loadconf()
    print('\n---Generate shell script.---')
    enc = conf["path"]["encoder"]
    seq = conf["path"]["sequence"]
    out = conf["path"]["output"]
    cfg_pre = conf["path"]["cfg_pre"]
    cfg_seq = conf["path"]["cfg_seq"]
    yuvmeta = conf["yuvmeta"]

    exps = conf["exps"]
    conf["tasks"] = {}
    for count, exp in enumerate(exps):
        print("# exp%02d: %s" % (count, exp["title"]))
        if not exp["items"]:
            exp["items"] = os.listdir(seq)
        
        for item in exp["items"]:
            name = item.split(".yuv")[0]
            yuvpath = op.join(seq, item)
            cfgpath = op.join(cfg_seq, name)+".cfg"
            for para in exp["paras"]:

                if exp["mode"] == "RATE":
                    mode_cmd = "--RateControl=1 --TargetBitrate=%d000"%para
                elif exp["mode"] == "QP":
                    mode_cmd = "--QP=%d"%para
                elif exp["mode"] == "QPIF":
                    integer = int(para)
                    decimal = integer + 1 - para  # QPIF 32.7 -> QP32 qpif0.3
                    mode_cmd = "--QP=%d --QPIncrementFrame=%d"%(integer, \
                        int(int(yuvmeta[item]["FramesToBeEncoded"])*decimal)  )

                outname = op.join(out, name)+"_"+str(para)
                binpath = outname + ".bin"
                recpath = outname + ".yuv"
                logpath = outname + ".log"
                shell = "{} -c {} -c {} --InputFile={} --BitstreamFile={} --ReconFile={} {} > {}".format(
                    enc, cfg_pre, cfgpath, yuvpath, binpath, recpath, mode_cmd, logpath)
                # print(cmd)
                conf["tasks"][logpath] = {"status": "wait", "shell": shell}
        print("[ok] %d tasks have generated." % len(conf["tasks"]))
    saveconf(conf)


def call_script(script):
    print("---Task @", script.split()[-1])
    subprocess.run(script, shell=True)


def run(core=4):
    full_path = op.abspath("experiments.json")
    pf = {'fpath':full_path,'core':core}
    post(pf)


def analyze():
    conf = loadconf()
    tasks = conf["tasks"]
    count = {"wait": 0, "fail": 0, "success": 0}
    print('\n---Analyze specified tasks.---')
    results = []
    for tkey, tvalue in tasks.items():
        with open(tkey, "r") as f:
            brief = f.readlines()[-4:]
            if brief[-2].split()[0] == "finished":
                tvalue["status"] = "success"
                items = brief[0].split()
                results.append([tkey, items[2], items[6]])
            else:
                tvalue["status"] = "fail"
        count[tvalue["status"]] += 1
    print('Total %d tasks, %d wait, %d fail, %d success.' %
          (len(tasks), count["wait"], count["fail"], count["success"]))
    with open("result.csv","w") as f:
        f.write("file,bitrate,YUV-PSNR\n")
        for result in results:
            f.write(','.join(result)+'\n')
    print("result.csv generated.")
    saveconf(conf)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Media Encoding Experiment Script. Copyright @ 2016-2020')
    parser.add_argument(
        "verb", choices=['start', 'init', 'check', 'fix', 'shell', 'run', 'analyze'])
    parser.add_argument("--force", action='store_true', default=False,
                        help="init force overwrite experiments.json")
    parser.add_argument("--core", type=int, default=4,
                        help="run with n concurrent process")
    args = parser.parse_args()
    dict_func = {'init': init, 'start': start,
                 'fix': fix, 'tasks': tasks, 'run': run,'analyze':analyze}
    if args.verb == 'start':
        start(args.force)
    elif args.verb == 'run':
        run(args.core)
    else:
        dict_func[args.verb]()

# %%
