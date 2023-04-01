#!/usr/bin/env python3
import subprocess
from subprocess import check_output, CalledProcessError
import time
import argparse
import os
import sys

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))
import modules.db.sql as sql
import signal
import logging

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)


class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        self.kill_now = True


def main(serv, port):
    port = str(port)
    readstats = ""
    killer = GracefulKiller()

    while not killer.kill_now:
        try:
            cmd = f"echo 'show stat' |nc {serv} {port} | cut -d ',' -f 1-2,5 |grep waf |grep BACKEND |awk -F',' '{{print $3}}'"
            readstats = subprocess.check_output([cmd], shell=True)
        except OSError as e:
            mes = f'Cannot get metrics {f}'
            logging.error(mes)
            sql.insert_waf_metrics(serv, '0')

        readstats = readstats.decode(encoding='UTF-8')
        metric = readstats.splitlines()

        try:
            sql.insert_waf_metrics(serv, metric[0])
        except Exception as e:
            mes = f'Cannot insert metrics {e}'
            logging.error(mes)
            sql.insert_waf_metrics(serv, '0')

        time.sleep(30)

        if killer.kill_now:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Metrics HAProxy WAF service.', prog='metrics_waf_worker.py',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('IP', help='Start get metrics from HAProxy WAF service at this ip', nargs='?', type=str)
    parser.add_argument('--port', help='Start get metrics from HAProxy WAF service at this port', nargs='?', default=1999,
                        type=int)

    args = parser.parse_args()
    if args.IP is None:
        parser.print_help()
        sys.exit()
    else:
        try:
            main(args.IP, args.port)
        except KeyboardInterrupt:
            pass
