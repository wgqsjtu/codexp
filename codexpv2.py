# %%
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import os
import re
import json
import argparse
import glob

base_url = 'http://127.0.0.1:42024' # Set destination URL here

def post(addr, pf):
    request = Request(base_url+addr, urlencode(pf).encode())
    return urlopen(request).read().decode()

def get(addr):
    request = Request(base_url+addr)
    return urlopen(request).read().decode()

init_conf_vtm7 = {
    "manual": {
        "version": "VTM 7.0",
        "base": "~/VVCSoftware_VTM/",
        "encoder": "{base}/bin/EncoderAppStatic",
        "enccfg": "{base}/cfg/encoder_randomaccess_vtm.cfg",
        "seqpath": "~/data/darkset",
        "cfgpath": "~/data/darkset/cfg",
        "outpath": "~/endark/darkset/",
        "meta": {
            "InputBitDepth": "8",
            "InputChromaFormat": "420",
            "FrameRate": "30",
            "SourceWidth": "1920",
            "SourceHeight": "1080",
            "FramesToBeEncoded": "'300' if meta['FrameRate'] == '60' else '150'",
            "IntraPeriod": "'32' if meta['FrameRate'] == '30' else '64'",
            "Level": "'6.2' if meta['InputBitDepth'] == '10' else '3.1'"
        }
    },
    "exps": [
        {
            "title": "qp_test",
            "groups": [
                "Campfire.yuv  QPIF  32.7  32.8",
                "*.yuv QP 27 32"
            ],
            "outname": "{inname}_{mode}_{para}",
            "status": "wait"
        }
    ],
    "shell": [
        "{encoder} -c {enccfg} ",
        "-c {cfgpath}/{inname}.cfg --InputFile={seqpath}/{inname}.yuv ",
        "--BitstreamFile={outpath}/{outpath}.bin --ReconFile={outpath}/{outname}.yuv ",
        "{mode_cmd} > {outpath}/{outname}.log "
    ]
}

def loadconf():
    if not os.path.exists("experiments.json"):
        print("experiments.json don't exist. Use init.")
        exit(0)
    with open("experiments.json", "r") as f:
        conf = json.load(f)
    return conf


def saveconf(conf):
    with open("experiments.json", "w") as f:
        json.dump(conf, f, indent=4)

def getabspath(s):
    return os.path.abspath(os.path.expanduser(s.replace("{base}",".")))

def init(force=False):
    if os.path.exists("experiments.json") and not force:
        print("[ok] experiments.json already exists.")
        return
    print("[ok] experiments.json newly created.")
    with open("experiments.json", "w") as f:
        json.dump(init_conf_vtm7, f, indent=4)


def start(force=False):
    print('---Checking the json.---')
    init(force)
    conf = loadconf()
    manual = conf["manual"]

    print('\n---Checking the manual path.---')
    tmpdir = os.getcwd()
    basedir = os.path.expanduser(manual["base"])
    os.chdir(basedir)

    conf["path"] = {
        "encoder": getabspath(manual["encoder"]),
        "enccfg": getabspath(manual["enccfg"]),
        "seqpath": getabspath(manual["seqpath"]),
        "outpath": getabspath(manual["outpath"]),
        "cfgpath": getabspath(manual["cfgpath"])
    }

    os.chdir(tmpdir)
    saveconf(conf)
    print("[ok] Absolute path generated in experiments.json")

    print('\n---Checking the cfg.---')
    path = conf["path"]
    os.makedirs(path["outpath"], exist_ok=True)
    if os.path.exists(path["cfgpath"]) and os.listdir(path["seqpath"]):
        print("[ok] Cfg of sequence exists.")
    else:
        print("[warning] Cfg of sequence do not exists! Use meta.")
        if force:
            meta()

    tasks()

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

def meta():
    conf = loadconf()
    seqpath = conf["path"]["seqpath"]
    cfgpath = conf["path"]["cfgpath"]

    print("--Try to create cfg of sequence.--")
    conf["yuvmeta"] = {}
    os.makedirs(cfgpath, exist_ok=True)
    for filename in glob.glob(seqpath+"/*.yuv"):

        # from experiments.json
        meta = conf["manual"]["meta"].copy()
        for key,value in meta.items():
            if "if" in value:
                meta[key] = str(eval(value))

        # from filename
        for item in filename.split("_"):
            if re.match(r"^[0-9]*x[0-9]*$", item):
                meta["SourceWidth"], meta["SourceHeight"] = item.split("x")
            elif re.match(r"^[0-9]*fps$", item):
                meta["FrameRate"] = item.split("fps")[0]
            elif re.match(r"^[0-9]*bit", item):
                meta["InputBitDepth"] = item.split("bit")[0]
            elif item in ["444", "440", "422", "411", "420", "410", "311"]:
                meta["InputChromaFormat"] = item
        
        # from .yuv
        if meta["FramesToBeEncoded"] == "":
            meta["FramesToBeEncoded"] = readyuv420(filename, \
                    meta["InputBitDepth"], meta["SourceWidth"], meta["SourceHeight"])

        conf["yuvmeta"][filename] = meta

        cfgname = filename.split("/")[-1].replace(".yuv", ".cfg")
        #print(os.path.join(cfgpath, cfgname))
        with open(os.path.join(cfgpath, cfgname), "w") as autocfg:
            for key, value in meta.items():
                autocfg.write('{0:30}: {1}\n'.format(key, value))

    saveconf(conf)
    print("[meta+%3d] Auto parsing finished. Please check."%len(conf["yuvmeta"]))


def tasks():
    conf = loadconf()
    print('\n---Generate shell script.---')
    seqpath = conf["path"]["seqpath"]
    yuvmeta = conf["yuvmeta"]

    conf["tasks"] = {}
    for count, exp in enumerate(conf["exps"]):
        print("# exp%02d: %s" % (count, exp["title"]))
        for group in exp["groups"]:
            gitem, mode, *paras = group.split()
            items = glob.glob(os.path.join(seqpath,gitem))
            
            count = 0
            for item in items:
                inname = item.split('/')[-1].split(".")[0]
                for para in paras:
                    if mode == "RATE":
                        mode_cmd = "--RateControl=1 --TargetBitrate={}000".format(para)
                    elif mode == "QP":
                        mode_cmd = "--QP={}".format(para)
                    elif mode == "QPIF":
                        # QPIF 32.7 -> QP32 qpif0.3*nframes
                        nframes = int(yuvmeta[item]["FramesToBeEncoded"])
                        para = float(para)
                        qp = int(para)
                        qpif = int((qp + 1 - para)*nframes)
                        mode_cmd = "--QP={} --QPIncrementFrame={}".format(qp, qpif)

                    outname = exp["outname"].format(inname=inname,mode=mode,para=para)
                    shell = ' '.join(conf["shell"]).format(inname=inname, \
                            outname=outname, mode_cmd=mode_cmd, **conf["path"])

                    log = shell.split()[-1]
                    conf["tasks"][log] = {"status": "wait", "shell": shell}
                    count = count+1
            
            print("[task+%3d] %s" % (count,group))
    saveconf(conf)

def run(core=4):
    try:
        print(get("/id"))
        full_path = os.path.abspath("experiments.json")
        pf = {'fpath':full_path,'core':core}
        print(post("/add", pf))
    except:
        print("Server Not Running. Try python3 server.py")

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
        description='Media Encoding Experiment Manager. Copyright @ 2016-2020')
    parser.add_argument(
        "verb", choices=['start', 'init', 'check', 'meta', 'shell', 'run', 'analyze'])
    parser.add_argument("--force", action='store_true', default=False,
                        help="init force overwrite experiments.json")
    parser.add_argument("--core", type=int, default=4,
                        help="run with n concurrent process")
    args = parser.parse_args()
    dict_func = {'init': init, 'start': start,
                 'meta': meta, 'tasks': tasks, 'run': run,'analyze':analyze}
    if args.verb == 'start':
        start(args.force)
    elif args.verb == 'run':
        run(args.core)
    else:
        dict_func[args.verb]()

# %%
