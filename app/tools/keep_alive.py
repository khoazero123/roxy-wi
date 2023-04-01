#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import logging

import asyncio
from retry import retry

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.alerting.alerting as alerting
import modules.server.server as server_mod
import modules.roxywi.common as roxywi_common
import modules.service.common as service_common

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


class AutoStart(object):
	""" Checking and restart services """

	def __init__(self, service_ip, service_port, service_type, server_group, server_id):
		self.service_ip = service_ip
		self.service_port = service_port
		self.service_type = service_type
		self.server_group = server_group
		self.server_id = server_id


	def restart_service(self):
		alert = f"Tried to start {self.service_type} service on {self.service_ip}"
		logging.info(alert)

		if self.service_type == 'apache':
			service_name = service_common.get_correct_apache_service_name(self.service_ip)
		else:
			service_name = self.service_type

		start_command = [f'sudo systemctl restart {service_name}']
		try:
			server_mod.ssh_command(self.service_ip, start_command)
			time.sleep(1)
			try:
				roxywi_common.logging(self.service_ip, f' Auto start service has tried to restart {self.service_type}',
							  haproxywi=1, login=1, keep_history=1, service=self.service_type)
			except Exception as e:
				error = str(e)
				logging.error(f'Cannot save history {error}')
			try:
				json_for_sending = {"user_group": self.server_group, "message": f'warning: {alert}'}
				alerting.send_message_to_rabbit(json.dumps(json_for_sending))
			except Exception as e:
				error = str(e)
				logging.error(f'Cannot send a message {error}')
		except Exception as e:
			error = str(e)
			print(error)
			logging.error(f'Cannot restart service {error}')


	async def check_service(self):
		try:
			await asyncio.open_connection(self.service_ip, self.service_port)
		except Exception:
			try:
				restarted = sql.select_update_keep_alive_restart(self.server_id, self.service_type)
			except Exception:
				restarted = 0

			if not restarted:
				self.restart_service()
				sql.update_keep_alive_restart(self.server_id, self.service_type, 1)
			else:
				roxywi_common.logging(self.service_ip, f' Auto start service has already tried to restart. Ignoring {self.service_type}',
									  haproxywi=1, login=1, keep_history=1, service=self.service_type)
		else:
			sql.update_keep_alive_restart(self.server_id, self.service_type, 0)


	async def check_keepalived(self):
		answer = ''
		start_command = ['sudo systemctl is-active keepalived']
		try:
			answer = server_mod.ssh_command(self.service_ip, start_command)
			time.sleep(1)
		except Exception as e:
			print(str(e))

		if answer.strip() != 'active':
			restarted = sql.select_update_keep_alive_restart(self.server_id, self.service_type)
			if not restarted:
				self.restart_service()
				sql.update_keep_alive_restart(self.server_id, self.service_type, 1)
			else:
				roxywi_common.logging(self.service_ip,
									  f' Auto start service has already tried to restart. Ignoring {self.service_type}',
									  haproxywi=1, login=1, keep_history=1, service=self.service_type)
		else:
			sql.update_keep_alive_restart(self.server_id, self.service_type, 0)


def main():
	async def haproxy_checkin():
		servers = sql.select_keep_alive()
		port = sql.get_setting('haproxy_sock_port')

		for serv in servers:
			haproxy_services = AutoStart(serv.ip, port, 'haproxy', serv.groups, serv.server_id)
			await haproxy_services.check_service()


	async def nginx_checkin():
		servers = sql.select_nginx_keep_alive()
		port = sql.get_setting('nginx_stats_port')
		port = int(port)

		for serv in servers:
			nginx_services = AutoStart(serv.ip, port, 'nginx', serv.groups, serv.server_id)
			await nginx_services.check_service()


	async def apache_checkin():
		servers = sql.select_apache_keep_alive()
		port = sql.get_setting('apache_stats_port')
		port = int(port)

		for serv in servers:
			apache_services = AutoStart(serv.ip, port, 'apache', serv.groups, serv.server_id)
			await apache_services.check_service()


	async def keepalived_checkin():
		servers = sql.select_keepalived_keep_alive()

		for serv in servers:
			keepalived_services = AutoStart(serv.ip, serv.port, 'keepalived', serv.groups, serv.server_id)
			await keepalived_services.check_keepalived()

	ioloop = asyncio.get_event_loop()
	tasks = [ioloop.create_task(haproxy_checkin()),
			 ioloop.create_task(nginx_checkin()),
			 ioloop.create_task(apache_checkin()),
			 ioloop.create_task(keepalived_checkin())]
	wait_tasks = asyncio.wait(tasks)
	ioloop.run_until_complete(wait_tasks)
	print('new loop')
	time.sleep(60)


@retry(delay=1, tries=6)
def check_user_status():
	if sql.select_user_status():
		return True
	else:
		return False


if __name__ == "__main__":
	logging.info(f'Keep alive service has been started')
	killer = GracefulKiller()

	while not killer.kill_now:
		if check_user_status():
			main()
		else:
			logging.info('Your subscription has been finished. Please prolong your subscription. Exited')
			sys.exit()

		if killer.kill_now:
			break

	logging.info(f'Keep alive service has been stopped')
