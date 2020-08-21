# codexp编码实验管理工具

管理任务，对每个Job起一个标识符，排序检索已完成的任务及其结果。清理运行的结果。

分为client和server，先在本地写好json/toml配置文件，之后运行：

- start：辅助生成实验配置`experiments.json`
- run：将实验配置提交到服务器
- status：查看运行情况
- analyze：分析运行结果，生成
- clean：清除某次任务



## init

根据日期生成配置文件，例如`job0001.json`，用户打开该文件进行配置，为一次Job生成一系列Task，之后的命令将自动使用最新配置文件。

配置文件的语法及格式考虑：多行字符串，表格数组，纠结json、[yaml还是toml](https://blog.csdn.net/paladinzh/article/details/88951763)。

借鉴前端Vue模板写法，将模板量分为const，iterate，compute三类，按照这个顺序进行计算，填充生成shell指令。compute中的字典值可以是单行的python语句。

为方便使用，还在compute属性中还补充了功能，其中`auto_mode`中可以自定义实验模式，`auto_meta`中可以利用缺省值和条件来生成yuv文件的cfg。

例如`exp-win-x265.json`：

```json
{
    "const": {
        "base": "C:\\Users\\313\\Desktop\\user1",
        "inpath": "{base}\\seq"
    },
    "iterate": [
        "input | mode | para",
        "{inpath}\\*.yuv | -q | 27,32,37,42"
    ],
    "compute": {
        "output": "{base}\\result\\{inname}_{mode}_{para}"
    },
    "shell": [
        "x265 --preset fast",
        "--input {input} --fps 25 --input-res 3840x2160",
        "--output {output}.bin",
        "--psnr --ssim --csv {output}.csv --csv-log-level 2",
        " -f 250 {mode} {para}"
    ]
}
```



例如`exp-linux-vtm.json`：

```json
{
    "const": {
        "version": "linux VTM-7.0",
        "base": "~/VVCSoftware_VTM/",
        "encoder": "{base}/bin/EncoderAppStatic",
        "enccfg": "{base}/cfg/encoder_randomaccess_vtm.cfg",
        "seqpath": "~/data/darkset",
        "cfgpath": "~/data/darkset/cfg",
        "outpath": "~/endark/darkset/"
    },
    "iterate": [
        "input | mode | para",
        "052.yuv | QP | 32"
    ],
    "compute": {
        "output": "{outpath}/{inname}_{mode}_{para}",
        "auto_mode": {
            "QP": "-q {para}",
            "RATE": "--RateControl=1 --TargetBitrate={para}000"
        },
        "auto_meta": {
            "InputBitDepth": "8",
            "InputChromaFormat": "420",
            "FrameRate": "30",
            "SourceWidth": "1920",
            "SourceHeight": "1080",
            "FramesToBeEncoded": "",
            "IntraPeriod": "'32' if meta['FrameRate'] == '30' else '64'",
            "Level": "3.1"
        }
    },
    "shell": [
        "{encoder} -c {enccfg} ",
        "-c {cfgpath}/{inname}.cfg --InputFile={input} ",
        "--BitstreamFile={output}.bin --ReconFile={output}.yuv ",
        "{mode_cmd} > {output}.log "
    ]
}
```



## start

```shell
python codexp.py start test.json
```

检查test.json的语法，生成实验用的shell，保存相关信息在`experiments.json`中。会自动保存yuvmeta，tasks。

```json
"yuvmeta": {
        "055.yuv": {
            "SourceWidth": "1920",
            "SourceHeight": "1080",
            "FramesToBeEncoded": "150",
        }
},
"tasks": {
    "052_QP_32.log": {
        "status": "0/150",
        "shell": "EncoderAppStatic -c vtm.cfg  -c 052.cfg > 052_QP_32.log "
    }
}
```



## run

本地将`experiments.json`提交到服务器，服务器端会检查tasks中的任务status，然后加入运行队列。参数有：

- `--core 4` ：同时运行的任务数，初始设置为4。
- `--autofix true`：自动运行失败的任务，并且设置core减1。
- `--kill 1053`：结束某任务。



## show

检查task中的任务status，给出运行情况。如果任务全为为success，则统计得出结果.csv。管理历史运行数据。参数有：

- `--sort name|time`：按时间或文件名顺序排列结果。
- `--grep String`：检索包含String的结果。

```
title: exp 01
date: 2020-03-09 10:00:00 -> 2020-03-10 08:30:17
pid		status		frame		log
1033	success		[300/300]	Campfire_QP27
1034	excuting	[75/300]	Campfire_QP32
1035	wait		[0/300]		Campfire_QP37
1036	fail		[158/300]	Campfire_QP42
------
1 success, 1 excuting, 1 wait, 1 fail.
```

## clean

清除某一次任务，传入标识符。