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
import modules.alerting.alerting as alerting
import signal
import logging


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
	if service_status == 'DOWN' or service_status == 'MAINT':
		level = 'warning'
	else:
		level = 'info'

	logging.info(f'{mes}')
	serv_group = sql.select_servers(server=service_ip)

	for s in serv_group:
		group = s[3]

	sql.insert_alerts(group, level, service_ip, 'N/A', mes, 'Checker')

	try:
		alerting.alert_routing(service_ip, 1, group, level, mes, alert_type)
	except Exception as e:
		error = str(e)
		logging.error(f'Cannot send alert: {error}')



def main(serv, port):
	port = str(port)
	first_run = True
	current_stat = []
	old_stat = []
	readstats = ""
	killer = GracefulKiller()
	old_stat_service = ""
	conn_notify = []
	service_id = 1
	server_id = ''


	while True:
		if first_run:
			service_id = sql.select_service_id_by_slug('haproxy')
			server_id = sql.select_server_id_by_ip(serv)
			try:
				service_status = sql.select_checker_service_status(server_id, service_id, 'service')
			except Exception:
				service_status = ''
			if not service_status:
				old_stat_service = 'error'
			else:
				old_stat_service = 'Ok'

		try:
			readstats = subprocess.check_output([f"echo show stat | nc {serv} {port}"], shell=True)
		except CalledProcessError:
			cur_stat_service = "error"
			if old_stat_service != cur_stat_service:
				status = 'DOWN'
				alert = f"HAProxy service is {status} at {serv}"
				send_and_logging(alert, status, serv, 'service')
				sql.inset_or_update_service_status(server_id, service_id, 'service', 0)

			first_run = False
			old_stat_service = cur_stat_service
			time.sleep(60)
			continue
		except OSError:
			pass
		else:
			cur_stat_service = "Ok"
			if old_stat_service != cur_stat_service:
				status = 'UP'
				alert = f"HAProxy service is {status} at {serv}"
				send_and_logging(alert, status, serv, 'service')
				first_run = True
				sql.inset_or_update_service_status(server_id, service_id, 'service', 1)
				time.sleep(5)
			old_stat_service = cur_stat_service

		vips = readstats.splitlines()

		for i in range(0, len(vips)):
			if "UP" in str(vips[i]):
				current_stat.append("UP")
			elif "DOWN" in str(vips[i]):
				current_stat.append("DOWN")
			elif "MAINT" in str(vips[i]):
				current_stat.append("MAINT")
			else:
				current_stat.append("none")

			if not first_run:
				if (current_stat[i] != old_stat[i] and current_stat[i] != "none") and ("FRONTEND" not in str(vips[i]) and "service" not in str(vips[i])):
					servername = str(vips[i])
					servername = servername.split(",")
					realserver = servername[0]
					server = servername[1]
					alert = f"Backend: {realserver[2:]}, server: {server} has changed status to {current_stat[i]} on {serv} HAProxy"
					send_and_logging(alert, current_stat[i], serv, 'backend')
		first_run = False
		old_stat = current_stat
		current_stat = []
		interval = sql.get_setting('checker_check_interval')
		interval = int(interval) * 60
		time.sleep(interval)

		if killer.kill_now:
			break
		try:
			read_connections = subprocess.check_output([
				"echo show stat | nc " + serv + " " + port + "|awk -F\",\" '{print $1,$2,$5,$7}'|grep -e 'FRONTEND\|BACKEND'|grep -ve 'stats\|per_ip_and_url_rates\|per_ip_rates'"],
				shell=True)
		except Exception as e:
			print(str(e))
			print('Cannot connect to HAProxy')

		try:
			connections = read_connections.splitlines()

			try:
				checker_maxconn_threshold = sql.get_setting('checker_maxconn_threshold')
			except Exception:
				checker_maxconn_threshold = 90

			for i in range(0, len(connections)):
				connections[i] = connections[i].decode(encoding='UTF-8')
				splitted_connections = connections[i].split(' ')
				section = splitted_connections[0]
				section_type = splitted_connections[1]
				section_full_name = section_type + ':' + section
				curr_conn = int(splitted_connections[2])
				max_conn = int(splitted_connections[3])
				connections_percent = curr_conn / max_conn * 100

				if connections_percent > checker_maxconn_threshold:
					if section_full_name not in conn_notify:
						alert = 'The maxconn is about to be exceeded: {} {} {}, connections are {}, max_conn is: {}'.format(
							serv, section_type.lower(), section, curr_conn, max_conn
						)
						send_and_logging(alert, 'DOWN', serv, 'maxconn')
						conn_notify.append(section_full_name)
				else:
					if section_full_name in conn_notify:
						alert = 'The number of connections decreased on: {} {} {}, connections are {}, max_conn is: {}'.format(
							serv, section_type.lower(), section, curr_conn, max_conn
						)
						send_and_logging(alert, 'UP', serv, 'maxconn')
						conn_notify.remove(section_full_name)
		except Exception:
			pass

	logging.info(f'HAProxy worker has been shutdown for: {serv}')


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Check HAProxy servers state.', prog='checker_worker.py', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

	parser.add_argument('IP', help='Start check HAProxy server state at this ip', nargs='?', type=str)
	parser.add_argument('--port', help='Start check HAProxy server state at this port', nargs='?', default=1999, type=int)

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
