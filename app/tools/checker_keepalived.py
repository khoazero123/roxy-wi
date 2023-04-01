#!/usr/bin/env python3
import time
import argparse
import os
import sys
sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.alerting.alerting as alerting
import modules.server.server as server_mod
import signal
import logging


logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logging.getLogger("paramiko").setLevel(logging.WARNING)
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

    logging.info(f'{mes}')
    serv_group = sql.select_servers(server=service_ip)

    for s in serv_group:
        group = s[3]

    sql.insert_alerts(group, level, service_ip, 'N/A', mes, 'Checker')

    try:
        alerting.alert_routing(service_ip, 3, group, level, mes, alert_type)
    except Exception as e:
        error = str(e)
        logging.error(f'Cannot send alert: {error}')


def main(serv):
    first_run = True
    service_state = ''
    old_stat = ''
    master_state = ''
    old_master_state = ''
    service_id = 3
    server_id = ''
    killer = GracefulKiller()

    while True:
        if first_run:
            service_id = sql.select_service_id_by_slug('keepalived')
            server_id = sql.select_server_id_by_ip(serv)

            try:
                service_status = sql.select_checker_service_status(server_id, service_id, 'service')
            except Exception:
                service_status = ''

            if not service_status:
                old_stat = 'error'
            else:
                old_stat = 'active'

        start_command = ['sudo systemctl is-active keepalived && sudo kill -USR1 `cat /var/run/keepalived.pid` && sudo grep State /tmp/keepalived.data -m 1 |awk -F"=" \'{print $2}\'|tr -d \'[:space:]\' && sudo rm -f /tmp/keepalived.data']
        try:
            current_stat = server_mod.ssh_command(serv, start_command)
            time.sleep(1)
            current_stat = current_stat.split('\n')
            service_state = current_stat[0]
            service_state = service_state.strip()
            master_state = current_stat[1]
        except Exception as e:
            error = str(e)
            logging.error(f'Cannot get status: {error}')

        if service_state != old_stat:
            if service_state != 'active':
                status = 'DOWN'
                sql.inset_or_update_service_status(server_id, service_id, 'service', 0)
            else:
                status = 'UP'
                sql.inset_or_update_service_status(server_id, service_id, 'service', 1)
            alert = "Keepalived service is " + status + " at " + serv
            send_and_logging(alert, status, serv, 'service')

        if not first_run and master_state != old_master_state:
            if master_state != 'MASTER' and 'No such file or directory' not in master_state:
                status = 'DOWN'
            else:
                status = 'UP'
            master_state_nice = master_state
            old_master_state_nice = old_master_state
            if 'No such file or directory' in master_state:
                master_state_nice = 'None'
            elif 'No such file or directory' in old_master_state:
                old_master_state_nice = 'None'
            alert = "Keepalived service on " + serv + " has changed state from " + old_master_state_nice + " to " + master_state_nice
            send_and_logging(alert, status, serv, 'backend')

        first_run = False
        old_stat = service_state
        old_master_state = master_state
        service_state = ''
        master_state = ''
        interval = sql.get_setting('checker_check_interval')
        interval = int(interval) * 60
        time.sleep(interval)

        if killer.kill_now:
            break

    logging.info(f'Keepalived worker has been shutdown for: {serv}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Check Keepalived servers state.', prog='checker_keepalived.py', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('IP', help='Start check Keepalived server state at this ip', nargs='?', type=str)

    args = parser.parse_args()
    if args.IP is None:
        parser.print_help()
        import sys
        sys.exit()
    else:
        try:
            main(args.IP)
        except KeyboardInterrupt:
            pass
