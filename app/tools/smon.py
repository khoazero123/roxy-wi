#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import socket
import sys
import time
import json
import logging

from urllib.request import Request, urlopen, ssl
from urllib.request import socket as url_socket
from urllib.error import URLError, HTTPError
from retry import retry
# import subprocess
import requests
import urllib3
from contextlib import closing
from datetime import datetime
from pytz import timezone

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.alerting.alerting as alerting

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logging.getLogger("pika").setLevel(logging.WARNING)
urllib3.disable_warnings()


class Smon(object):
    def __init__(self, service_ip, service_port, first_run, http, service_id, user_group, telegram_channel=0, slack_channel_id=0):
        self.user_group = user_group
        self.service_ip = service_ip
        self.service_port = service_port
        self.telegram_channel = telegram_channel
        self.slack_channel = slack_channel_id
        self.service_id = service_id
        self.first_run = first_run
        self.http = http

    def send_and_logging(self, mes, level='warning'):
        if level == 'warning':
            logging.warning(mes)
        elif level == 'critical':
            logging.critical(mes)
        else:
            logging.info(mes)

        mes_for_logs = f'{level}: {mes}'
        mes_for_db = mes

        sql.insert_alerts(self.user_group, level, self.service_ip, self.service_port, mes_for_db, 'SMON')

        if self.telegram_channel != 0:
            try:
                alerting.telegram_send_mess(mes_for_logs, telegram_channel_id=self.telegram_channel)
            except Exception as e:
                print(str(e))
                pass

        if self.slack_channel != 0:
            try:
                alerting.slack_send_mess(mes_for_logs, slack_channel_id=self.slack_channel)
            except Exception as e:
                print(str(e))
                pass

        try:
            json_for_sending = {"user_group": self.user_group, "message": mes_for_logs}
            alerting.send_message_to_rabbit(json.dumps(json_for_sending))
            logging.info('Send message to Rabbit')
        except Exception as e:
            error = str(e)
            logging.error(f'Cannot send a message {error}')


    def port_is_down(self, now_utc):
        sql.change_status(0, self.service_id)
        sql.add_sec_to_state_time(now_utc, self.service_id)
        sql.response_time('', self.service_id)
        if not first_run:
            service_status = 'DOWN'
            mes = 'Port: {0} on host {1} is {2} '.format(str(self.service_port),
                                                         self.service_ip,
                                                         service_status)
            self.send_and_logging(mes)
            # try:
            #     script = sql.select_script(self.id)
            #     subprocess.check_call(script, shell=True)
            # except subprocess.CalledProcessError as e:
            #     logging.warning('Cannot run the script for: '+str(self.service_port)+' on host '+self.service_ip+', error: '+str(e))
            #     pass

    def check_socket(self):
        try:
            now_utc = datetime.now(timezone(sql.get_setting('time_zone')))
        except Exception:
            now_utc = datetime.now(timezone('UTC'))
        now_utc = str(now_utc)
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(5)
            status = sql.select_status(self.service_id)
            status = int(status)
            start = time.time()

            try:
                if sock.connect_ex((self.service_ip, self.service_port)) == 0:
                    end = (time.time()-start)*1000
                    sql.response_time(end, self.service_id)

                    if status == 0 or status == 3:
                        sql.change_status(1, self.service_id)
                        sql.add_sec_to_state_time(now_utc, self.service_id)
                        if not first_run:
                            service_status = 'UP'
                            mes = 'Port: {0} on host {1} is {2} '.format(str(self.service_port),
                                                                         self.service_ip,
                                                                         service_status)
                            self.send_and_logging(mes, 'info')
                    return True
                else:
                    if status == 1 or status == 3:
                        self.port_is_down(now_utc)
                    return False
            except Exception:
                if status == 1 or status == 3:
                    self.port_is_down(now_utc)
                return False

    def check_port_status(self):
        status = sql.select_http_status(self.service_id)
        try:
            http_uri = self.http.split(":")[1]
            http_method = self.http.split(":")[0]
        except Exception:
            http_method = 'http'
            try:
                http_uri = self.http

                if '/' not in http_uri[0]:
                    http_uri = f'/{http_uri}'

            except Exception:
                http_uri = '/'
        try:
            now_utc = datetime.now(timezone(sql.get_setting('time_zone')))
        except Exception:
            now_utc = datetime.now(timezone('UTC'))
        now_utc = str(now_utc)
        try:
            response = requests.get(f'{http_method}://{self.service_ip}:{self.service_port}{http_uri}', verify=False)
            response.raise_for_status()

            if status == 0:
                sql.change_http_status(1, self.service_id)
                sql.add_sec_to_state_time(now_utc, self.service_id)
                service_status = 'UP'
                mes = f'HTTP port {self.service_port} on host {self.service_ip} is {service_status}'
                self.send_and_logging(mes, 'info')

            if http_method == 'https':
                self.check_ssl_expire()

            body_answer = sql.select_body(self.service_id)
            if body_answer is not None and body_answer != 'None':
                status = sql.select_body_status(self.service_id)

                if body_answer not in response.content.decode(encoding='UTF-8'):
                    if status == 1:
                        sql.change_body_status(0, self.service_id)
                        sql.add_sec_to_state_time(now_utc, self.service_id)
                        i = 0
                        body = ''
                        for l in response.content.decode(encoding='UTF-8'):
                            body += l
                            i += 1
                            if i > 145:
                                break

                        if not self.first_run:
                            service_status = 'failure'
                            mes = f'Checking body {self.service_port} on host {self.service_ip} is {service_status}'
                            self.send_and_logging(mes)
                else:
                    if status == 0:
                        sql.change_body_status(1, self.service_id)
                        sql.add_sec_to_state_time(now_utc, self.service_id)
                        if not self.first_run:
                            service_status = 'well'
                            mes = 'Answer from {0} on host {1} is {2} '.format(str(self.service_port),
                                                                               self.service_ip,
                                                                               service_status)
                            self.send_and_logging(mes, 'info')

        except requests.exceptions.HTTPError as err:
            if status == 1:
                sql.change_http_status(0, self.service_id)
                sql.add_sec_to_state_time(now_utc, self.service_id)
                service_status = 'failure'
                mes = 'Response is: {content} from {ip} port {port} is '.format(content=err.response.status_code,
                                                                                ip=self.service_ip,
                                                                                port=str(self.service_port))
                self.send_and_logging(mes)
        except requests.exceptions.ConnectTimeout:
            if status == 1:
                sql.change_http_status(0, self.service_id)
                sql.add_sec_to_state_time(now_utc, self.service_id)
                service_status = 'timeout'
                mes = 'HTTP connection to {0} port {1} is {2} '.format(self.service_ip,
                                                                       str(self.service_port),
                                                                       service_status)
                self.send_and_logging(mes)
        except requests.exceptions.ConnectionError:
            if status == 1:
                sql.change_http_status(0, self.service_id)
                sql.add_sec_to_state_time(now_utc, self.service_id)
                service_status = 'connection error'
                mes = 'HTTP connection to {0} port {1} is {2} '.format(self.service_ip,
                                                                       str(self.service_port),
                                                                       service_status)
                self.send_and_logging(mes)
        except Exception as err:
            print(f"error: Unexpected error: {err}")


    def check_ssl_expire(self):
        try:
            context = ssl.create_default_context()
            with url_socket.create_connection((self.service_ip, self.service_port)) as sock:
                with context.wrap_socket(sock, server_hostname=self.service_ip) as ssock:
                    data = json.dumps(ssock.getpeercert(), sort_keys=True, indent=4)
        except Exception as error:
            logging.error(f'Cannot get SSL information {error}')
            return None

        n = json.loads(data)
        now_date = datetime.strptime(n['notAfter'], '%b %d %H:%M:%S %Y %Z')
        present = datetime.now(timezone('UTC'))
        present = present.strftime('%b %d %H:%M:%S %Y %Z')
        present = datetime.strptime(present, '%b %d %H:%M:%S %Y %Z')
        warning_days = sql.get_setting('smon_ssl_expire_warning_alert')
        critical_days = sql.get_setting('smon_ssl_expire_critical_alert')

        if (now_date - present).days < warning_days:
            alert = 'ssl_expire_warning_alert'
            need_alert = sql.get_smon_alert_status(self.service_ip, alert)
            if need_alert == 0:
                sql.update_smon_alert_status(self.service_ip, 1, alert)
                mes = f'A SSL certificate on {self.service_ip} will expire in less than {warning_days} days'
                self.send_and_logging(mes)
        else:
            sql.update_smon_alert_status(self.service_ip, 0, 'ssl_expire_warning_alert')

        if (now_date - present).days < critical_days:
            alert = 'ssl_expire_critical_alert'
            need_alert = sql.get_smon_alert_status(self.service_ip, alert)
            if need_alert == 0:
                mes = f'A SSL certificate on {self.service_ip} will expire in less than {critical_days} days'
                self.send_and_logging(mes, 'critical')
                sql.update_smon_alert_status(self.service_ip, 1, alert)
        else:
            sql.update_smon_alert_status(self.service_ip, 0, 'ssl_expire_critical_alert')


@retry(delay=1, tries=6)
def check_user_status():
    if sql.select_user_status():
        return True
    else:
        return False


if __name__ == "__main__":
    first_run = True
    logging.info('Roxy-WI SMON service has been started')
    while True:
        if check_user_status:
            services = sql.select_en_service()
            for s in services:
                ip = s.ip
                port = s.port
                telegram_channel_id = s.telegram_channel_id
                slack_channel_id = s.slack_channel_id
                smon_id = s.id
                user_group = s.user_group
                http = ''

                try:
                    smon = Smon(ip, port, first_run, http, smon_id, user_group, telegram_channel_id, slack_channel_id)
                except Exception as e:
                    print(str(e))
                if smon.check_socket():
                    http = sql.select_http(smon_id)

                    if http is not None and http != '':
                        smon = Smon(ip, port, first_run, http, smon_id, user_group, telegram_channel_id, slack_channel_id)
                        smon.check_port_status()

            first_run = False
            history_range = sql.get_setting('smon_keep_history_range')
            sql.delete_alert_history(int(history_range), 'SMON')
            interval = sql.get_setting('smon_check_interval')
            interval = int(interval) * 60
            time.sleep(interval)
        else:
            logging.info('Your subscription has been finished. Please prolong your subscription. Exited')
            sys.exit()
