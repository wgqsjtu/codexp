# %%
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import os
import re
import json
import argparse
import glob

base_url = 'http://127.0.0.1:42024' # Set destination URL here

conf_pro = {
    "variable": {
        "base": "/home/faymek/codexp",
        "inpath": "{base}/seq",
        "output": "{base}/result/{$inname}_{$modename}_{para}"
    },
    "iterate": [
        "input | $mode | para",
        "{inpath}/*.yuv | QP | 27,32,37,42"
    ],
    "auto": {
        "$inname": "os.path.basename(state['input']).split('.')[0]",
        "$modename": "state['$mode'].replace('$','')",
        "$mode": {
            "QP": "-q {para}",
            "RATE": "--RateControl=1 --TargetBitrate={para}000",
            "$QPIF": "modeQPIF(state)"
        },
        "$meta": {
            "InputBitDepth": "8",
            "InputChromaFormat": "420",
            "FrameRate": "30",
            "SourceWidth": "1920",
            "SourceHeight": "1080",
            "$FramesToBeEncoded": "str(calcAllFrames(state))",
            "$IntraPeriod": "'32' if meta['FrameRate'] == '30' else '64'",
            "Level": "3.1"
        }
    },
    "shell": [
        "x265 --preset fast",
        "--input {input} --fps 25 --input-res 3840x2160",
        "--output {output}.bin",
        "--psnr --ssim --csv {output}.csv --csv-log-level 2",
        " -f 250 {$mode}"
    ]
}

default_auto = {
    "$inname": "os.path.basename(state['input']).split('.')[0]",
    "$modename": "state['$mode'].replace('$','')"
}

def calcAllFrames(state):
    meta = state['meta'][state['input']]
    return readyuv420(state['input'], \
            meta["InputBitDepth"], meta["SourceWidth"], meta["SourceHeight"])

def modeQPIF(state):
    # QPIF 32.7 -> QP32 qpif0.3*nframes
    if not "FramesToBeEncoded" in state['meta'][state['input']]:
        print("In QPIF mode, no meta information find. Use meta.")
        return ""
    nframes = eval(state['meta'][state['input']]["FramesToBeEncoded"])
    para = float(state['para'])
    qp = int(para)
    qpif = int((qp + 1 - para)*nframes)
    return "--QP={} --QPIncrementFrame={}".format(qp, qpif)

def post(addr, pf):
    request = Request(base_url+addr, urlencode(pf).encode())
    return urlopen(request).read().decode()

def get(addr):
    request = Request(base_url+addr)
    return urlopen(request).read().decode()

def loadconf(fn=None):
    if not fn:
        fn = getlatestjob() 
    if not os.path.exists(fn):
        print("The Job doesn't exist. Use init.")
        exit(0)
    with open(fn, "r") as f:
        conf = json.load(f)
    return conf

def saveconf(conf, fn=None):
    if not fn:
        fn = getlatestjob() 
    with open(fn, "w") as f:
        json.dump(conf, f, indent=4)

def getabspath(s):
    return os.path.abspath(os.path.expanduser(s))

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

def getlatestjob():
    jobs = sorted(glob.glob("job*.json"))
    return jobs[-1] if jobs else ""

def readcfg(fn):
    meta = {}
    with open(fn, "r") as f:
        for line in f:
            k,v = line.replace(':',' ').split()
            meta[k] = v
    return meta



def init(template="conf_win_x265"):
    lastjob = getlatestjob()
    idx = int(lastjob[3:7]) + 1 if lastjob else 1  # get next job id
    curjob = "job%04d.json"%idx
    with open(curjob, "w") as f:
        json.dump(conf_pro, f, indent=4)
    print("[ok] %s newly created."%curjob)


def start(force=False):
    conf = loadconf()

    # get {var} completed except key_tofill.
    # -  key_auto: {$var} are system preserved to be computed.
    # -  key_it: iterate keys are kept to be filled by paras.
    key_auto = ['$inname', '$mode', '$meta', '$modename']
    
    it_sheet = []
    for v in conf["iterate"]:
        it_sheet.append( v.replace(' ', '').split('|') )
    key_it = it_sheet[0]

    state = {k:"{%s}"%k for k in key_it+key_auto} # keep the same after format
    state.update(conf["variable"])

    for k, v in conf["variable"].items():
        t = v.format(**state)
        if '\\' in v or '/' in v:
            t = getabspath(t)
            os.makedirs(os.path.dirname(t), exist_ok=True)
        state[k] = t
    
    # get sheet(2D) -> table(3D)
    it_table = [] # 3D array
    for p1 in it_sheet[1:]:
        t1 = []
        for p2 in p1:
            t2 = []
            for p3 in p2.split(','):
                p3 = p3.format(**state)
                if '*' in p3:
                    t2.extend(sorted(glob.glob(p3)))
                else:
                    t2.append(p3)
            t1.append(t2)
        it_table.append(t1)
    
    # get table(3D) ->paras(2D), using eval trick
    # 1,2|3,4,5|6|7,8 -> 1367,1368,1467,1468,...
    paras = []
    for p in it_table:
        tuples = ','.join(["t%d"%t for t in range(len(p))])
        fors = ' '.join(['for t{0} in p[{0}]'.format(t) for t in range(len(p))])
        trick = "[({}) {}]".format(tuples,fors)
        paras.extend(eval(trick,{"p":p}))

    # get meta information
    if 'meta' not in conf:
        meta = []
        for p in it_table:
            meta.extend(p[0])
        conf['meta'] = {k:{} for k in list(set(meta))}
        saveconf(conf)
    state['meta'] = conf['meta']

    # get tasks iterately by using it_dict
    tasks = {}
    cmd = ' '.join(conf["shell"]).format(**state)
    default_auto.update(conf["auto"])
    compute = default_auto
    for values in paras:
        context = {k:v for k,v in zip(key_it,values)}
        state.update(context)
        
        # compute $inname, $modename, if exists
        for k,v in compute.items():
            if k.startswith('$') and type(v) is str:
                state[k] = eval(v)
        # read cfg from .cfg, guess from shell, if exists
        cfgs = re.findall(r"-c +([^ ]+.cfg)", cmd.format(**state))
        for cfg in cfgs:
            cfgname = os.path.basename(cfg).split('.')[0]
            if (cfgname.split('_')[0]) == (state['$inname'].split('_')[0]):
                state['meta'][state['input']] = readcfg(cfg)


        if '$mode' in key_it:
            key = state['$mode']
            value = compute['$mode'][key]
            if "$" in key:
                state['$mode'] = eval(value)
            else:
                state['$mode'] = value.format(**state)
            
        shell = cmd.format(**state)
        output = state["output"].format(**state)
        tasks[output] = {"status": "0", "shell": shell}
    
    conf["tasks"] = tasks
    saveconf(conf)
    print("[task+%3d] Tasks generated." % len(tasks))


def meta():
    conf = loadconf()
    
    for file in conf['meta']:
        filename = os.path.basename(file)
        meta = conf["auto"]["$meta"].copy()

        for item in filename.split("_"):
            if re.match(r"^[0-9]*x[0-9]*$", item):
                meta["SourceWidth"], meta["SourceHeight"] = item.split("x")
            elif re.match(r"^[0-9]*fps$", item):
                meta["FrameRate"] = item.split("fps")[0]
            elif re.match(r"^[0-9]*bit", item):
                meta["InputBitDepth"] = item.split("bit")[0]
            elif item in ["444", "440", "422", "411", "420", "410", "311"]:
                meta["InputChromaFormat"] = item
        
        state = {'input':file,'meta':{file:meta}}
        new_meta = {}
        for key,value in meta.items():
            if "$" in key:
                new_meta[key[1:]] = str(eval(value))
            else:
                new_meta[key] = value
        conf["meta"][file] = new_meta

        cfg = file.replace(".yuv", ".cfg")
        with open(cfg, "w") as autocfg:
            for key, value in new_meta.items():
                autocfg.write('{0:30}: {1}\n'.format(key, value))
    
    saveconf(conf)
    print("[meta+%3d] Auto parsing finished. Please check."%len(conf["meta"]))


def run(core=4):
    try:
        print(get("/id"))
        full_path = os.path.abspath("experiments.json")
        pf = {'fpath':full_path,'core':core}
        print(post("/add", pf))
    except:
        print("Server Not Running. Try python3 server.py")

def show():
    history = loadconf(fn="history.json")
    recent = sorted(history.keys(),reverse=True)
    tasks = history[recent[0]]
    count = {"wait": 0, "excute": 0, "finish": 0}
    print('\n---Analyze recent tasks.---')
    print("EXP @",recent[0])
    
    # read log
    results = []
    for tkey, tvalue in tasks.items():
        with open(tkey, "r") as f:
            lines = list(f.readlines())
            nline = len(lines)
            cur, total = tvalue["status"].split('/')
            cur, total = int(cur), int(total)
            if nline < 10:
                cur = 0
                status = "wait"
            else:
                if lines[-2] and lines[-2].split()[0] == "finished":
                    cur = total
                    status = "finish"
                    items = lines[-4].split()
                    results.append([tkey, items[2], items[6]])
                else:
                    status = "excute"
                    cur = min(nline-10,total)
        tvalue["status"] = "%3d/%3d"%(cur, total)
        count[status] += 1
        print("[{}] {}".format(tvalue["status"],tkey.split("/")[-1]))
    print('Total %d tasks, %d wait, %d excute, %d finish.' %
          (len(tasks), count["wait"], count["excute"], count["finish"]))
    with open("result.csv","w") as f:
        f.write("file,bitrate,YUV-PSNR\n")
        for result in results:
            f.write(','.join(result)+'\n')
    print("result.csv generated.")
    saveconf(history, fn="history.json")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Media Encoding Experiment Manager. Copyright @ 2016-2020')
    parser.add_argument(
        "verb", choices=['start', 'init', 'meta', 'run', 'show'])
    parser.add_argument("--force", action='store_true', default=False,
                        help="init force overwrite experiments.json")
    parser.add_argument("--core", type=int, default=4,
                        help="run with n concurrent process")
    args = parser.parse_args()
    dict_func = {'init': init, 'start': start,
                 'meta': meta, 'run': run, 'show':show}
    if args.verb == 'start':
        start(args.force)
    elif args.verb == 'run':
        run(args.core)
    else:
        dict_func[args.verb]()

# %%
