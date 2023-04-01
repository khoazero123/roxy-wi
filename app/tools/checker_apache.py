#!/usr/bin/env python3
import time
import signal
import os
import sys
import logging

import argparse
import socket
from contextlib import closing

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.alerting.alerting as alerting

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logging.getLogger("pika").setLevel(logging.WARNING)


class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        self.kill_now = True


def send_and_logging(mes, service_status, service_ip, alert_type):
    if service_status == 'DOWN':
        level = 'warning'
    else:
        level = 'info'

    logging.info(f' {mes}')
    serv_group = sql.select_servers(server=service_ip)

    for s in serv_group:
        group = s[3]

    sql.insert_alerts(group, level, service_ip, 'N/A', mes, 'Checker')

    try:
        alerting.alert_routing(service_ip, 4, group, level, mes, alert_type)
    except Exception as e:
        error = str(e)
        logging.error(f'Cannot send alert: {error}')


def main(serv, port):
    first_run = True
    old_stat = ''
    service_id = 4
    server_id = ''
    killer = GracefulKiller()

    while True:
        if first_run:
            service_id = sql.select_service_id_by_slug('apache')
            server_id = sql.select_server_id_by_ip(serv)

            try:
                service_status = sql.select_checker_service_status(server_id, service_id, 'service')
            except Exception:
                service_status = ''

            if not service_status:
                old_stat = 0
            else:
                old_stat = 1

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(5)

            try:
                if sock.connect_ex((serv, port)) == 0:
                    current_stat = 1
                    if old_stat != 1:
                        status = 'UP'
                        alert = "Apache service is " + status + " at " + serv
                        send_and_logging(alert, status, serv, 'service')
                        sql.inset_or_update_service_status(server_id, service_id, 'service', 1)
                else:
                    current_stat = 0
                    if old_stat != 0:
                        status = 'DOWN'
                        alert = "Apache service is " + status + " at " + serv
                        send_and_logging(alert, status, serv, 'service')
                        sql.inset_or_update_service_status(server_id, service_id, 'service', 0)
            except Exception:
                current_stat = 0
                if old_stat != 0:
                    status = 'DOWN'
                    alert = "Apache service is " + status + " at " + serv
                    send_and_logging(alert, status, serv, 'service')
                    sql.inset_or_update_service_status(server_id, service_id, 'service', 0)

        first_run = False
        old_stat = current_stat
        current_stat = ''
        interval = sql.get_setting('checker_check_interval')
        interval = int(interval) * 60
        time.sleep(interval)

        if killer.kill_now:
            break

    logging.info(f' Apache worker has been shutdown for: {serv}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check Apache servers state.', prog='checker_apache.py', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('IP', help='Start check Apache server state at this ip', nargs='?', type=str)
    parser.add_argument('--port', help='Start check Apache server state at this port', nargs='?', default=8086, type=int)

    args = parser.parse_args()
    if args.IP is None:
        parser.print_help()
        import sys
        sys.exit()
    else:
        try:
            main(args.IP, args.port)
        except KeyboardInterrupt:
            pass
