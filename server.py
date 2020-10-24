from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import parse
import logging
import subprocess
from multiprocessing import Pool
import os
import time
import json


class Result:
    def __init__(self):
        self.result = {}
        self.last = None

    def busy(self, key=None):
        if self.last:
            if not key:
                key = self.last
            return self.result[key]._number_left
        else:
            return 0


class Conf:
    def __init__(self):
        self.conf = {}

    def load(self, fpath):
        if not os.path.exists(fpath):
            return -1
        with open(fpath, "r") as f:
            self.conf = json.load(f)

    def save(self, fpath):
        with open(fpath, "w") as f:
            json.dump(self.conf, f, indent=4)


class S(BaseHTTPRequestHandler):

    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        #logging.info("GET request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
        if self.path == '/id':
            self._set_response()
            self.wfile.write("Codexp v2 Running.".encode('utf-8'))
        elif self.path == '/path':
            cwd = os.getcwd()
            stamp = time.strftime("%m%d%H%M", time.localtime())
            res = "{}/{}".format(cwd, stamp)
            os.makedirs(res+"/inpath", exist_ok=True)
            os.makedirs(res+"/outpath", exist_ok=True)
            self._set_response()
            self.wfile.write(res.encode('utf-8'))
        elif self.path.startswith('/busy'):
            if '?' in self.path:
                key = self.path.split('?')[-1]
            else:
                key = None
            self._set_response()
            self.wfile.write(str(RunResult.busy(key)).encode('utf-8'))

    def do_POST(self):
        # <--- Gets the size of data
        content_length = int(self.headers['Content-Length'])
        # <--- Gets the data itself
        post_data = self.rfile.read(content_length)
        # logging.info("POST request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
        #        str(self.path), str(self.headers), post_data.decode('utf-8'))
        if self.path == '/add':
            data = parse.parse_qs(post_data.decode('utf-8'))
            # print(data)
            fpath = data['fpath'][0]
            core = int(data['core'][0])
            key = data['key'][0]
            logging.info("POST /add %s", data)
            if RunConf.load(fpath) == -1:
                self._set_response()
                self.wfile.write("Invalid Configure File".encode('utf-8'))
            else:
                res = run(core, key)
                print(res)
                self._set_response()
                self.wfile.write(res.encode('utf-8'))


def serve(server_class=HTTPServer, handler_class=S, port=42024):
    logging.basicConfig(level=logging.INFO)
    server_address = ('0.0.0.0', port)
    httpd = server_class(server_address, handler_class)
    logging.info('Starting httpd at %s:%s \n' % ('0.0.0.0', port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping httpd...\n')


def call_script(script):
    desc = script.split('/')[-1]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] start :" % stamp, desc)
    subprocess.run(script, shell=True)
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] finish:" % stamp, desc)


def run(core=4, key=None):
    conf = RunConf.conf
    scripts = []
    if type(conf) is list:
        scripts = conf
        res = '\n'.join([
            '\n---Excute specified tasks.---',
            'Excute the %d shell script with %d process.\n' %
            (len(scripts), core)
        ])
    elif type(conf) is dict:
        tasks = conf["tasks"]
        stamp = time.strftime("%m-%d %H:%M", time.localtime())
        HistoryConf.conf[stamp] = tasks
        HistoryConf.save("history.json")
        count = {"wait": 0, "excute": 0, "finish": 0}
        for tvalue in tasks.values():
            cur, total = tvalue["status"].split('/')
            cur, total = int(cur), int(total)
            if cur == 0:
                status = "wait"
            elif cur == total:
                status = "finish"
            else:
                status = "excute"
            count[status] += 1
            if status != "finish":
                scripts.append(tvalue["shell"])

        res = '\n'.join([
            '\n---Excute specified tasks.---',
            'Total %d tasks, %d wait, %d fail, %d success.' %
            (len(tasks), count["wait"], count["excute"], count["finish"]),
            'Excute the %d shell script with %d process.\n' %
            (len(scripts), core)
        ])
    RunResult.last = key
    RunResult.result[key] = RunPool.map_async(call_script, scripts)
    print(RunResult.result)
    return res


if __name__ == '__main__':

    RunPool = Pool(4)
    RunResult = Result()
    RunConf = Conf()
    HistoryConf = Conf()

    from sys import argv
    port = int(argv[1]) if len(argv) == 2 else 42024
    serve(port=port)
