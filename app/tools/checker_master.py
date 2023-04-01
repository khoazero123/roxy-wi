#!/usr/bin/env python3
import time
import sys
import os

from retry import retry
import signal
import logging

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.server.server as server_mod

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)


class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        self.kill_now = True


def main():
    servers = sql.select_alert()
    started_workers = get_worker('haproxy')
    nginx_servers = sql.select_nginx_alert()
    nginx_started_workers = get_worker('nginx')
    apache_servers = sql.select_apache_alert()
    apache_started_workers = get_worker('apache')
    keepalived_servers = sql.select_keepalived_alert()
    keepalived_started_workers = get_worker('keepalived')
    servers_list = []
    nginx_servers_list = []
    apache_servers_list = []
    keepalived_servers_list = []

    for serv in servers:
        servers_list.append(serv.ip)

    need_kill = list(set(started_workers) - set(servers_list))
    need_start = list(set(servers_list) - set(started_workers))

    if need_kill:
        for serv in need_kill:
            send_mess_to_rabbit('kill', 'haproxy')
            kill_worker(serv, 'haproxy')

    if need_start:
        for serv in need_start:
            start_worker(serv, 'haproxy')

    try:
        for serv in nginx_servers:
            nginx_servers_list.append(serv.ip)

        nginx_need_kill = list(set(nginx_started_workers) - set(nginx_servers_list))
        nginx_need_start = list(set(nginx_servers_list) - set(nginx_started_workers))

        if nginx_need_kill:
            for serv in nginx_need_kill:
                kill_worker(serv, 'nginx')

        if nginx_need_start:
            for serv in nginx_need_start:
                start_worker(serv, 'nginx')
    except:
        pass

    try:
        for serv in apache_servers:
            apache_servers_list.append(serv.ip)

        apache_need_kill = list(set(apache_started_workers) - set(apache_servers_list))
        apache_need_start = list(set(apache_servers_list) - set(apache_started_workers))

        if apache_need_kill:
            for serv in apache_need_kill:
                kill_worker(serv, 'apache')

        if apache_need_start:
            for serv in apache_need_start:
                start_worker(serv, 'apache')
    except:
        pass

    try:
        for serv in keepalived_servers:
            keepalived_servers_list.append(serv.ip)

        keepalived_need_kill = list(set(keepalived_started_workers) - set(keepalived_servers_list))
        keepalived_need_start = list(set(keepalived_servers_list) - set(keepalived_started_workers))

        if keepalived_need_kill:
            for serv in keepalived_need_kill:
                kill_worker(serv, 'keepalived')

        if keepalived_need_start:
            for serv in keepalived_need_start:
                start_worker(serv, 'keepalived')

    except Exception as e:
        error = str(e)
        print(error)
        logging.error(f'{error}')

    history_range = sql.get_setting('checker_keep_history_range')

    try:
        sql.delete_alert_history(int(history_range), 'Checker')
    except Exception as e:
        print(f'error: cannot delete old metrics: {e}')


def start_worker(serv, service):
    additional_to_command = ''
    if service == 'haproxy':
        port = sql.get_setting(f'{service}_sock_port')
        additional_to_command = f'--port {port}'
    elif service in ('nginx', 'apache'):
        port = sql.get_setting(f'{service}_stats_port')
        additional_to_command = f'--port {port}'
    cmd = f"tools/checker_{service}.py {serv} {additional_to_command} &"
    os.system(cmd)
    logging.info(f'Master has started a new {service} worker for: {serv}')


def kill_worker(serv, service):
    cmd = f"ps ax |grep 'tools/checker_{service}.py {serv}'|grep -v grep |awk '{{print $1}}' |xargs kill"
    output, stderr = server_mod.subprocess_execute(cmd)
    logging.info(f'Master has killed {service} worker for: {serv}')
    if stderr:
        logging.error(f'{stderr}')


def kill_all_workers():
    cmd = "ps ax |grep -E 'checker_haproxy.py|checker_nginx.py|checker_apache.py|checker_keepalived.py' |grep -v grep |awk '{print $1}' |xargs kill"
    output, stderr = server_mod.subprocess_execute(cmd)
    logging.info(f'Master has killed all workers')
    if stderr:
        logging.error(f'{stderr}')


def get_worker(service):
    cmd = f"ps ax |grep 'tools/checker_{service}.py' |grep -v grep |awk '{{print $7}}'"
    output, stderr = server_mod.subprocess_execute(cmd)
    if stderr:
        logging.error(f'{stderr}')
    return output


@retry(delay=1, tries=6)
def check_user_status():
    return True
    if sql.select_user_status():
        return True
    else:
        return False


if __name__ == "__main__":
    logging.info('Checker master has been started')
    killer = GracefulKiller()

    while True:
        if check_user_status():
            main()
        else:
            kill_all_workers()
            logging.info('Your subscription has been finished. Prolong your subscription. Exit')
            sys.exit()

        time.sleep(20)

        if killer.kill_now:
            kill_all_workers()
            logging.info('Checker master has been stopped')
            break
