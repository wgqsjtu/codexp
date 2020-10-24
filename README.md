# codexp编码实验管理工具

## 批处理版本 cbatch.py

```
python cbatch.py verb inpath outpath --opt options
```

对inpath目录中的每个合适的文件，执行verb，输出到outpath目录，有时需手动修改代码。

针对YUV文件，会自动从文件名推断尺寸、位深等信息，如Campfire_1920x1080_10bit_420.yuv。

运行模式包括：本地快速运行，本地服务器模式，远程服务器模式。服务器模式下，可以一直提交新的任务(bug)。

快速任务verb包括：
- 格式转换类，使用ffmpeg进行格式转换
  - png2yuv, yuv2png, png2rgb, rgb2png
- 指标测量类，使用ffmpeg进行指标测量，从输入文件名匹配输出文件名，并汇总输出measure.csv到当前目录
  - psnr, ssim, vmaf
- vtmenc：使用 VVC VTM 编码器进行编码，需配置路径和命令行
- hpmenc：使用 AVS HPM 编码器进行编码，需配置路径和命令行
- hpmcrop：使用ffmpeg切去HPM编码后的自动padding
- show：分析输入目录的编码器log，输出enclog.csv到当前目录
- run： 检查并提交用户给定的任务列表


选项--opt包括：

- --cf：强制使用指定的色度采样格式，如 420|422|444
- --qps：编码类应用使用的QP列表，应为python中的列表或元组，如 27, | 27,32 | "range(27,43,5)" 
- --core：指定同时执行任务的多进程数量，默认 4，服务器上需另外设置
- --host：指定任务在哪台机器运行，默认off：本机快速运行，local：本机服务器模式，其他自定义服务器，需配置iptables和ssh无密码连接，并在远端运行python server.py
- --wait：服务器模式下，提交任务后定时检查运行情况的时间间隔秒数

使用注意：

- 无需安装任何python包
- 运行前请先修改 host.local 中的编码器路径信息
- 一般需使用绝对路径，可以软链接到你的实验目录，如`ln ~/codexp/cbatch.py ~/test/cbatch.py`，这样即可在实验目录使用相对路径。
- 目前server仅支持Linux发行版，使用server模式需先在代码里配置多线程数量，如`RunPool(32)`



## 开发计划

[todo] Server Enhance, const overload for time measurement
[todo] Data processing
[todo] Batch Pipeline
[201023] Dir-level batch operation
[200919] Adapter to diffenent codec
[200822] Grammer newly designed

### features
- show pid
- gallery and job template
- local server mode & remote mode
- Sample. run several shells to check.
- RD-plot

### Server
- server linux ?windows
- client linux ?windows
- file transfer
  - client2server 
  - master2slave scp
- 

## 复杂配置版本 codexp.py

管理任务，对每个Job起一个标识符，排序检索已完成的任务及其结果。清理运行的结果。

分为client和server，先在本地写好json/toml配置文件，之后运行：

- new: 创建实验配置`jobxxx.json`
- start：根据配置，补充生成tasks，获得yuv信息，编码帧数
- meta: 推断输入文件的基本信息，主要用来维护yuv
- run：将实验配置提交到服务器
- show：查看运行情况，分析运行结果，生成表格
- clean：清除某次任务


### new

生成序号自增的配置文件，例如`job001.json`，用户编辑文件，之后的命令将自动使用最新配置文件。gallery中提供了系列常用配置作为模板，也可以将自定义配置移入其中。new命令会自动匹配对应的文件，生成新的job，默认模板为`conf_pro.json`。

```shell
python codexp.py new
python codexp.py new HM
```

配置文件的语法进行了重新设计，借鉴前端Vue模板写法，将模板量分为once, iter, each三类，按照这个顺序进行计算，填充生成shell指令。以$开头的键，其值可以是单行的python语句。

为方便使用，系统提供了其他复杂功能：`$mode`中可以自定义编码实验模式，如QP/RATE/QPIF；`$meta`中指定了yuv文件的缺省信息，系统也会从.cfg或者yuv文件名中获取信息。

模板示例`linux-HMseq.json`：

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

### start

```shell
python codexp.py start test.json
```

检查`jobxxx.json`的语法，补充生成tasks，获得yuv的元信息，编码帧数等信息。

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

语法解析过程：

key_sys0为保留功能键,如`$mode`，`$meta`，实现较为复杂的功能。（未实现）key_sys1为默认功能键，如`$inname`获得输入文件`/seq/abc.yuv`的名称`abc`，这类含义是默认定义的，但是也可以被用户重写。需要检测值中所有涉及的键，现有模式是运行所有$键。state是状态字典，不断更新来填充字符串中的字段。

新：引入safe_subsitude。
TODO：给出未解析的字段

1. 占位：key_sys0, key_sys1, key_iter, key_each; state: 占位 + once 
2. 执行{$once}, 更新state, 填充{once}, 更新state, 
3. 获取iter_paras
4. 处理sys0
5. 参数迭代key_iter，计算{$each}, key_sys1, 处理sys0, 填充

尝试获得meta信息
- 必）从iter.input获取文件列表
- 选）推断shell中的-c **/*.cfg选项
- 选）使用meta方法推断文件名，默认{$meta}

尝试获得nframes编码帧数信息
- 必）初始化为0
- 选）从{meta}中获得
- 选）推断shell中的-f n选项

### meta

从文件名推断输入文件的基本信息。

### run

本地将`jobxxx.json`提交到服务器，服务器端会检查tasks中的任务status，然后加入运行队列。参数有：

- `--core 4` ：同时运行的任务数，初始设置为4。
- `--overload const`：负载恒定，队列不满时会填充假任务，直到所有指定任务运行结束
- `--retry 5`：自动运行失败的任务，最大5次。
- `--kill 1053`：结束某任务。


### show

检查task中的任务status，给出运行情况。如果任务全为success，则统计得出结果.csv。管理历史运行数据。参数有：

- `--type hm|vtm|hpm|x265|uavs3e`: 根据编码器类型解析log，或自定义数据解析方法。
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

### clean

清除某一次任务，传入标识符。