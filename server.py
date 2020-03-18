#!/usr/bin/env python3
"""
Very simple HTTP server in python for logging requests
Usage::
    ./server.py [<port>]
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import subprocess
from multiprocessing import Pool
import time
import json
from urllib import parse
import os.path as op

class Conf:
    def __init__(self):
        self.conf ={}

    def load(self, fpath):
        if not op.exists(fpath):
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

    def do_POST(self):
        content_length = int(self.headers['Content-Length']) # <--- Gets the size of data
        post_data = self.rfile.read(content_length) # <--- Gets the data itself
        #logging.info("POST request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
        #        str(self.path), str(self.headers), post_data.decode('utf-8'))
        if self.path == '/add':
            data = parse.parse_qs(post_data.decode('utf-8'))
            #print(data)
            fpath = data['fpath'][0]
            core = int(data['core'][0])
            logging.info("POST /add %s",data)
            if RunConf.load(fpath) == -1:
                self._set_response()
                self.wfile.write("Invalid Configure File".encode('utf-8'))
            else:
                res = run(core)
                print(res)
                self._set_response()
                self.wfile.write(res.encode('utf-8'))

def serve(server_class=HTTPServer, handler_class=S, port=42024):
    logging.basicConfig(level=logging.INFO)
    server_address = ('127.0.0.1', port)
    httpd = server_class(server_address, handler_class)
    logging.info('Starting httpd at %s:%s \n'%('127.0.0.1', port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping httpd...\n')


def call_script(script):
    desc = script.split('/')[-1]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] start :"%stamp, desc)
    #time.sleep(5)
    subprocess.run(script, shell=True)
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    print("- [%s] finish:"%stamp, desc)
    #subprocess.run(script, shell=True)

def run(core=4):
    conf = RunConf.conf
    tasks = conf["tasks"]
    stamp = time.strftime("%m-%d %H:%M", time.localtime())
    HistoryConf.conf[stamp] = tasks
    HistoryConf.save("history.json")

    scripts = []
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
        'Total %d tasks, %d wait, %d fail, %d success.' % \
            (len(tasks), count["wait"], count["fail"], count["success"]),
        'Excute the %d shell script with %d process.\n' % \
            (len(scripts), core)
    ])
    
    RunPool.map_async(call_script, scripts)
    return res


if __name__ == '__main__':

    RunPool = Pool(4)
    RunConf = Conf()
    HistoryConf = Conf()

    from sys import argv
    port = int(argv[1]) if len(argv) == 2 else 42024
    serve(port=port)

