TRANSLATE = {}
LOG_KEYS = {
    "VTM": ['Total Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Total Time'],
    "HM": ['Total Frames', '|', 'Bitrate', 'Y-PSNR', 'U-PSNR', 'V-PSNR', 'YUV-PSNR', 'Total Time'],
    "HPM": ['PSNR Y(dB)', 'PSNR U(dB)', 'PSNR V(dB)', 'MsSSIM_Y', 'Total bits(bits)', 'bitrate(kbps)', 'Encoded frame count', 'Total encoding time']
}

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
        if nline < 49:
            return "wait", 0, None
        elif lines[-2] and lines[-2].split()[-1] == "frames/sec":
            cl = lines[-12:-6] + lines[-5:-4]
            values = [v.split()[-1] for v in cl]
            values.append(lines[-4].split()[-2])  # Total Time
            return "finish", nline-63, values
        else:
            return "excute", nline-49, None

def log_getEnctype(fn):
    enctype = ""
    with open(fn, "r") as f:
        lines = list(f.readlines())
        nline = len(lines)
        if nline>1:
            if lines[1].startswith("VVCSoftware: VTM Encoder Version"):
                enctype = "VTM"
            elif lines[1].startswith("HM software: Encoder Version"):
                enctype = "HM"
            elif lines[1].startswith("HPM version"):
                enctype = "HPM"
    return enctype

def log_adapter(fn, enctype=""):
    if not enctype: # interpret
        enctype = log_getEnctype(fn)
    dict_func = {
        "VTM": log_vtm,
        "HM": log_hm,
        "HPM": log_hpm
    }
    return dict_func[enctype](fn)
