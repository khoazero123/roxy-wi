#!/usr/bin/env python3
import subprocess
from subprocess import check_output, CalledProcessError
import time
import os
import sys
import signal
import logging

import requests
import argparse

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql

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
    killer = GracefulKiller()
    apache_user = sql.get_setting('apache_stats_user')
    apache_pass = sql.get_setting('apache_stats_password')
    stats_page = sql.get_setting('apache_stats_page')

    while not killer.kill_now:
        try:
            response = requests.get(f'http://{serv}:{port}/{stats_page}?auto', auth=(apache_user, apache_pass))
        except Exception as e:
            print(f'error: {e}')
            mes = f'Cannot get metrics {e}'
            logging.error(mes)
            sql.insert_apache_metrics(serv, '0')
        else:
            data = response.content
            for k in data.decode('utf-8').split('\n'):
                if 'ConnsTotal' in k:
                    k = k.split('ConnsTotal:')[1]
                    print(k)
                    sql.insert_apache_metrics(serv, k.strip())

        time.sleep(30)

        if killer.kill_now:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Metrics Apache service.', prog='metrics_apache_worker.py',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('IP', help='Start to get metrics from Apache service at this ip', nargs='?', type=str)
    parser.add_argument('--port', help='Start to get metrics from Nginx service at this port', nargs='?', default=1999,
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
