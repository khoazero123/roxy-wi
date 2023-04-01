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
    http_error_old = []
    killer = GracefulKiller()

    while not killer.kill_now:
        try:
            cmd = "echo show info | nc " + serv + " " + port + " |grep -e 'CurrConns\|CurrSslConns\|MaxSessRate:\|SessRate:'|awk '{print $2}'"
            readstats = subprocess.check_output([cmd], shell=True)
        except CalledProcessError as e:
            mes = 'Cannot get metrics %s from %s' % (str(e), serv)
            logging.error(mes)
            sql.insert_metrics(serv, '0', '0', '0', '0')
            time.sleep(30)
            continue
        except OSError as e:
            mes = 'Cannot get metrics %s from %s' % (str(e), serv)
            logging.error(mes)
            sql.insert_metrics(serv, '0', '0', '0', '0')
            time.sleep(30)
            continue

        try:
            readstats = readstats.decode(encoding='UTF-8')
            metric = readstats.splitlines()
            metrics = []
            for i in range(0, len(metric)):
                metrics.append(metric[i])

            sql.insert_metrics(serv, metrics[0], metrics[1], metrics[2], metrics[3])
        except Exception as e:
            mes = 'Cannot insert metrics %s for %s' % (str(e), serv)
            logging.error(mes)
            sql.insert_metrics(serv, '0', '0', '0', '0')

        try:
            read_http_errors = subprocess.check_output([
                                                           "echo show stat | nc " + serv + " " + port + "|awk -F\",\" '{print $1,$41,$42,$43,$44,$74}' |grep -ve 'per_ip_and_url_rates\|per_ip_rates\|#'"],
                                                       shell=True)
        except Exception as e:
            mes = 'Cannot connect to HAProxy %s to %s' % (str(e), serv)
            logging.error(mes)
            time.sleep(30)
            continue

        http_error = read_http_errors.splitlines()

        http_2xx = 0
        http_3xx = 0
        http_4xx = 0
        http_5xx = 0

        for i in range(0, len(http_error)):
            http_error[i] = http_error[i].decode(encoding='UTF-8')
            splitted_http_error = http_error[i].split(' ')

            try:
                splitted_http_error_old = http_error_old[i].split(' ')
            except Exception as e:
                print(str(e))

            try:
                if splitted_http_error[5] != '':
                    pass
                else:
                    continue
            except Exception:
                continue

            try:
                if splitted_http_error[1] != '' and splitted_http_error_old[1] != '':
                    http_2xx = http_2xx + (int(splitted_http_error[1]) - int(splitted_http_error_old[1]))
                elif splitted_http_error[1] != '':
                    http_2xx = http_2xx + int(splitted_http_error[1])
            except Exception as e:
                print('Cannot get 200: ' + str(e))

            try:
                if splitted_http_error[2] != '' and splitted_http_error_old[2] != '':
                    http_3xx = http_3xx + (int(splitted_http_error[2]) - int(splitted_http_error_old[2]))
                elif splitted_http_error[2] != '':
                    http_2xx = http_3xx + int(splitted_http_error[2])
            except Exception:
                print('Cannot get 300')

            try:
                if splitted_http_error[3] != '' and splitted_http_error_old[3] != '':
                    http_4xx = http_4xx + (int(splitted_http_error[3]) - int(splitted_http_error_old[3]))
                elif splitted_http_error[3] != '':
                    http_2xx = http_4xx + int(splitted_http_error[3])
            except Exception:
                print('Cannot get 400')

            try:
                if splitted_http_error[4] != '' and splitted_http_error_old[4] != '':
                    http_5xx = http_5xx + (int(splitted_http_error[4]) - int(splitted_http_error_old[4]))
                elif splitted_http_error[4] != '':
                    http_2xx = http_5xx + int(splitted_http_error[4])
            except Exception:
                print('Cannot get 500')

        try:
            sql.insert_metrics_http(serv, http_2xx, http_3xx, http_4xx, http_5xx)
        except Exception as e:
            print(str(e))
            pass

        http_error_old = []
        http_error_old = http_error

        time.sleep(30)

        if killer.kill_now:
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Metrics HAProxy service.', prog='metrics_worker.py',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('IP', help='Start to get metrics from HAProxy service at this ip', nargs='?', type=str)
    parser.add_argument('--port', help='Start to get metrics from HAProxy service at this port', nargs='?',
                        default=1999, type=int)

    args = parser.parse_args()
    if args.IP is None:
        parser.print_help()
        sys.exit()
    else:
        try:
            main(args.IP, args.port)
        except KeyboardInterrupt:
            pass
