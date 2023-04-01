#!/usr/bin/env python3
import time
import os
import sys
import signal

import nmap3
import logging
import json
from retry import retry

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


def logging_and_send(server_ip, group_id, port, port_status, notify, history, service_name):
    groups_name = sql.select_groups(id=group_id)
    for g in groups_name:
        group_name = g.name

    mes = " New port has been %s: %s on server %s for group: %s" % (port_status, port, server_ip, group_name)
    logging.info(mes)

    if notify:
        try:
            alerting.telegram_send_mess(mes, ip=server_ip)
        except Exception as e:
            error = str(e)
            logging.error(f'Cannot send a message {error}')
            pass

        try:
            alerting.slack_send_mess(mes, ip=server_ip)
        except Exception as e:
            error = str(e)
            logging.error(f'Cannot send a message {error}')
            pass

        try:
            json_for_sending = {"user_group": group_id, "message": 'info: ' + mes}
            alerting.send_message_to_rabbit(json.dumps(json_for_sending))
        except Exception as e:
            error = str(e)
            logging.error(f'Cannot send a message {error}')
            pass

    if history:
        try:
            if service_name:
                sql.insert_port_scanner_history(server_ip, port, port_status, service_name)
        except Exception as e:
            mes = "Cannot save to the history for: %s port: %s status: %s group: %s %s" % (server_ip, port, port_status, group_name, str(e))
            logging.error(mes)


def scanner(server_id, user_group_id, notify, history):
    server_ip = sql.select_servers(id=server_id)
    nmap = nmap3.NmapHostDiscovery()

    for s in server_ip:
        scan_ip = s[2]
        results = nmap.nmap_portscan_only(scan_ip)

    ports_json = json.dumps(results)
    ports = json.loads(ports_json)

    try:
        old_ports = sql.select_ports(scan_ip)
    except Exception as e:
        mes = "Cannot get the old ports "+str(e)
        logging.error(mes)
        pass

    try:
        sql.delete_ports(scan_ip)
    except Exception as e:
        mes = "Cannot delete the old ports " + str(e)
        logging.error(mes)
        return

    try:
        for p in ports[scan_ip]['ports']:
            port = p['portid']
            service_name = p['service']['name']
            try:
                sql.insert_port_scanner_port(scan_ip, user_group_id, port, service_name)
            except Exception as e:
                mes = "Cannot insert the new ports " + str(e)
                logging.error(mes)
                return
    except Exception as e:
        logging.error(str(e))
        pass

    try:
        new_ports = sql.select_ports(scan_ip)
    except Exception as e:
        mes = "Cannot get the new ports " + str(e)
        logging.error(mes)
        return

    opened_ports = list(set(new_ports) - set(old_ports))
    closed_ports = list(set(old_ports) - set(new_ports))

    if opened_ports:
        for port in opened_ports:
            print(port)
            service_name = sql.select_port_name(scan_ip, port[0])
            logging_and_send(scan_ip, user_group_id, port[0], 'opened', notify, history, service_name)

    if closed_ports:
        for port in closed_ports:
            print(port)
            service_name = sql.select_port_name(scan_ip, port[0])
            logging_and_send(scan_ip, user_group_id, port[0], 'closed', notify, history, service_name)


def main():
    scanners = sql.select_port_scanner_settings_for_service()

    for s in scanners:
        try:
            if s.enabled == 1:
                scanner(s.server_id, s.user_group_id, s.notify, s.history)
        except (KeyboardInterrupt, SystemExit):
            pass

    interval = sql.get_setting('port_scan_interval')
    interval = int(interval) * 60
    time.sleep(interval)

    history_range = sql.get_setting('portscanner_keep_history_range')
    sql.delete_portscanner_history(history_range)


@retry(delay=1, tries=6)
def check_user_status():
    return True
    if sql.select_user_status():
        return True
    else:
        return False


if __name__ == "__main__":
    logging.info('Port scanner service is started')
    killer = GracefulKiller()

    while not killer.kill_now:
        if check_user_status():
            main()
        else:
            logging.info('Your subscription has been finished. Please prolong your subscription. Exited')
            sys.exit(1)

        if killer.kill_now:
            break

    logging.info('Port scanner service is stopped')
