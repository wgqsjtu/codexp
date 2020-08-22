# codexp编码实验管理工具

管理任务，对每个Job起一个标识符，排序检索已完成的任务及其结果。清理运行的结果。

分为client和server，先在本地写好json/toml配置文件，之后运行：

- new: 创建实验配置`jobxxx.json`
- start：根据配置，补充生成tasks，获得yuv信息，编码帧数
- run：将实验配置提交到服务器
- status：查看运行情况
- analyze：分析运行结果，生成表格
- clean：清除某次任务


## new

生成序号自增的配置文件，例如`job001.json`，用户修改文件，为一次Job生成一系列Task，之后的命令将自动使用最新配置文件。

配置文件的语法进行了重新设计，借鉴前端Vue模板写法，将模板量分为once, iter, each三类，按照这个顺序进行计算，填充生成shell指令。字典值可以是单行的python语句。

为方便使用，系统提供了其他复杂功能，`$mode`中可以自定义实验模式，`$meta`中可以利用缺省值和条件来生成yuv文件的cfg。

生成模板，gallery中提供了系列常用配置，可以自建常用的配置，用命令来匹配，生成新的job。

```shell
python codexp.py new HM
```

例如`exp-win-x265.json`：

```json
{
    "once": {
        "exe_name": "CUBayeP",
        "base": "~/HM",
        "inpath": "/home/medialab/workspace/HDD/HMSeq",
        "$timestamp": "time.strftime('%y_%m_%d_%H_%M_%S', time.localtime(time.time()))",
        "LocBinfiles": "{base}/result/{$timestamp}_{exe_name}",
        "output": "{$inname}_{para}"
    },
    "iter": [
        "input | mode | para",
        "{inpath}/**/*.yuv | QP | 22,27,32,37"
    ],
    "each": {
        "$inname": "os.path.basename(state['input']).split('.')[0]",
        "$cfgname": "os.path.basename(state['input']).split('.')[0].split('_')[0]"
    },
    "shell": [
        "{base}/exe/{exe_name} -c {base}/cfg/encoder_intra_main.cfg",
        "-c {base}/cfg/per-sequence/{$cfgname}.cfg",
        "--InputFile={input} --BitstreamFile={LocBinfiles}/yuvbin/{output}_{exe_name}.hevc",
        "--QP={para}",
        "> {LocBinfiles}/logs/{output}.log",
        " -f 10"
    ]
}
```

## start

```shell
python codexp.py start test.json
```

检查test.json的语法，补充生成tasks，获得yuv信息，编码帧数等信息。

```json
"meta": {
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

语法解析：

key_sys0, key_sys1
-. 占位：key_sys0, key_sys1, key_iter, key_each; state: 占位 + once 
1. 执行{$once}, 更新state, 填充{once}, 更新state, 
2. 获取iter_paras
-. 处理sys0
3. 参数迭代key_iter，计算{$each}, key_sys1, 处理sys0, 填充

尝试获得meta信息
- 必）从iter.input获取文件列表
- 选）推断shell中的-c **/*.cfg选项
- 选）使用meta方法推断文件名，默认{$meta}

尝试获得nframes编码帧数信息
- 必）初始化为0
- 选）从{meta}中获得
- 选）推断shell中的-f n选项


## run

本地将`jobxxx.json`提交到服务器，服务器端会检查tasks中的任务status，然后加入运行队列。参数有：

- `--core 4` ：同时运行的任务数，初始设置为4。
- `--autofix true`：自动运行失败的任务，并且设置core减1。
- `--kill 1053`：结束某任务。



## show

检查task中的任务status，给出运行情况。如果任务全为为success，则统计得出结果.csv。管理历史运行数据。参数有：

- `--sort name|time`：按时间或文件名顺序排列结果。
- `--grep string`：检索包含string的结果。

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