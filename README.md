# codexp编码实验管理工具

管理任务，对每个任务起一个标识符，排序检索已完成的任务及其结果。清理运行的结果。

## start

```shell
codexp start test1.toml
```

配置文件的选用考虑：多行字符串，表格数组，纠结yaml还是toml

https://blog.csdn.net/paladinzh/article/details/88951763

解析test1.toml中的配置信息，创建task。

```
title = ""
basedir: "~/VVCSoftware_VTM/"

[codec.vtm7]
version: "VTM 7.0"
encoder: "./bin/EncoderAppStatic"
cfg: "./cfg/encoder_randomaccess_vtm.cfg",

[sequence]
path: "~/data/",
cfg: "./test/cfg/",

[output]
path: "./test/out/"
name: ""

[mode]
QP: "--QP=%d"
RATE: "--RateControl=1 --TargetBitrate=%d000"
QPIF: ""

[[exp]]
title: "exp 01"
status: "finished"
mode: "csv"
csv: """
	S1.yuv	QP		27 32 37 42
	S2.yuv	RATE	50k 100k
"""

[task]
log: []
status: []
shell: []


[history]


```

## run

检查task中的任务status，如果任务为wait或fail，则后台执行shell中的内容。（执行完毕修改为success。）管理同时运行的任务数。参数有：

- `--core 4` ：同时运行的任务数，初始设置为4。
- `--autofix true`：自动运行失败的任务，并且设置core减1。
- `--kill 1053`：结束任务。

## analyze

检查task中的任务status，如果任务为success，则统计得出结果.csv。管理历史运行数据。参数有：

- `--sort name|time`：按时间或文件名顺序排列结果。
- `--grep String`：检索包含String的结果。

## status

检查task中的任务status，给出运行情况。

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
