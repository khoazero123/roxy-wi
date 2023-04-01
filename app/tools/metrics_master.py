#!/usr/bin/env python3
import time
import os
import sys

import signal
import logging
from retry import retry

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
    try:
        sql.delete_metrics()
        sql.delete_http_metrics()
        sql.delete_waf_metrics()
        sql.delete_nginx_metrics()
        sql.delete_apache_metrics()
    except Exception as e:
        print(f'error: cannot delete old metrics {e}')

    servers = sql.select_haproxy_servers_metrics_for_master()
    started_workers = get_worker('haproxy')
    servers_list = []

    for serv in servers:
        servers_list.append(serv.ip)

    need_kill = list(set(started_workers) - set(servers_list))
    need_start = list(set(servers_list) - set(started_workers))

    if need_kill:
        for serv in need_kill:
            kill_worker(serv, 'haproxy')

    if need_start:
        for serv in need_start:
            start_worker(serv, 'haproxy')

    try:
        waf_servers = sql.select_waf_servers_metrics_for_master()
        waf_started_workers = get_worker('waf')
        waf_servers_list = []

        for serv in waf_servers:
            waf_servers_list.append(serv.ip)

        waf_need_kill = list(set(waf_started_workers) - set(waf_servers_list))
        waf_need_start = list(set(waf_servers_list) - set(waf_started_workers))

        if waf_need_kill:
            for serv in waf_need_kill:
                kill_worker(serv, 'waf')

        if waf_need_start:
            for serv in waf_need_start:
                start_worker(serv, 'waf')
    except Exception as e:
        mes = f'Problems with WAF worker metrics: {e}'
        logging.error(mes)
        pass

    try:
        nginx_servers = sql.select_nginx_servers_metrics_for_master()
        nginx_started_workers = get_worker('nginx')
        nginx_servers_list = []

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
    except Exception as e:
        mes = f'Problems with NGINX worker metrics: {e}'
        logging.error(mes)
        pass

    try:
        apache_servers = sql.select_apache_servers_metrics_for_master()
        apache_started_workers = get_worker('apache')
        apache_servers_list = []

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
    except Exception as e:
        mes = f'Problems with Apache worker metrics: {e}'
        logging.error(mes)
        pass


def start_worker(serv, service):
    if service in ('haproxy', 'waf'):
        port = sql.get_setting(f'haproxy_sock_port')
    elif service in ('nginx', 'apache'):
        port = sql.get_setting(f'{service}_stats_port')

    cmd = f'tools/metrics_{service}_worker.py {serv} --port {port} &'
    os.system(cmd)
    mes = f'Master started new {service.title()} metrics worker for: {serv}'
    logging.info(mes)


def kill_worker(serv, service):
    cmd = f"ps ax |grep 'tools/metrics_{service}_worker.py {serv}'|grep -v grep |awk '{{print $1}}' |xargs kill"
    output, stderr = server_mod.subprocess_execute(cmd)
    mes = f"Master killed {service.title()} metrics worker for: {serv}"
    logging.info(mes)
    if stderr:
        logging.error(stderr)


def kill_all_workers():
    cmd = "ps ax |grep -e 'tools/metrics_haproxy_worker.py\|tools/metrics_waf_worker.py\|tools/metrics_nginx_worker.py\|tools/metrics_apache_worker.py' |grep -v grep |awk '{print $1}' |xargs kill"
    output, stderr = server_mod.subprocess_execute(cmd)
    mes = "Master killed all metrics workers"
    logging.info(mes)
    if stderr:
        logging.error(stderr)


def get_worker(service):
    cmd = f"ps ax |grep 'tools/metrics_{service}_worker.py' |grep -v grep |awk '{{print $7}}'"
    output, stderr = server_mod.subprocess_execute(cmd)
    if stderr:
        logging.error(stderr)
    return output


@retry(delay=1, tries=6)
def check_user_status():
    return True
    if sql.select_user_status():
        return True
    else:
        return False


if __name__ == "__main__":
    logging.info('Metrics master is started')
    killer = GracefulKiller()

    while True:
        if check_user_status():
            main()
        else:
            kill_all_workers()
            logging.info('Your subscription has been finished. Please prolong your subscription. Exited')
            sys.exit()

        time.sleep(20)

        if killer.kill_now:
            break

    kill_all_workers()
    logging.info('Metrics master is stopped')
