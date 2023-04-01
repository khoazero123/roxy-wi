#!/usr/bin/env python3
import json
import time
import os
import sys
import asyncio
import threading
import logging

import websockets
from websockets import WebSocketServerProtocol
from aio_pika import connect, IncomingMessage

sys.path.append(os.path.join(sys.path[0], os.path.dirname(os.getcwd())))
sys.path.append(os.path.join(sys.path[0], os.getcwd()))

import modules.db.sql as sql
import modules.roxywi.common as roxywi_common

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
logging.getLogger("pika").setLevel(logging.WARNING)


class Server:
    clients = set()
    connected = {'client': dict()}
    logging.info(f'Roxy-WI sockets service has been started')
    rabbit_user = sql.get_setting('rabbitmq_user')
    rabbit_password = sql.get_setting('rabbitmq_password')
    rabbit_host = sql.get_setting('rabbitmq_host')
    rabbit_port = sql.get_setting('rabbitmq_port')
    rabbit_vhost = sql.get_setting('rabbitmq_vhost')
    rabbit_queue = sql.get_setting('rabbitmq_queue')


    def __init__(self):
        logging.info(f'Roxy-WI sockets service has been inited')


    async def register(self, ws: WebSocketServerProtocol) -> None:
        self.clients.add(ws)
        logging.info(f'{ws.remote_address} connects')


    async def unregister(self, ws: WebSocketServerProtocol) -> None:
        self.clients.remove(ws)
        logging.info(f'{ws.remote_address} disconnects')
        for key, val in self.connected.items():
            for k, v in val.items():
                if v['connect'] == ws:
                    del self.connected['client'][k]
                    logging.info(f'connect {ws} has been deleted')
                    break


    async def send_to_clients(self, message: str, user_connection) -> None:
        if self.clients:
            for conn in self.clients:
                if conn == user_connection:
                    conn_log = str(conn)
                    logging.info(f'trying to send to {conn_log} connects')
                    await conn.send(message)


    async def ws_handler(self, ws: WebSocketServerProtocol, url: str) -> None:
        await self.register(ws)
        try:
            await self.distribute(ws)
        finally:
            await self.unregister(ws)


    async def distribute(self, ws: WebSocketServerProtocol) -> None:
        try:
            async for message in ws:
                try:
                    consume_task = message.split(' ')[0]
                    user_group_id = message.split(' ')[1]
                    user_uuid = message.split(' ')[2]
                    self.connected['client'][user_uuid] = {'user_group_id': ''}
                    self.connected['client'][user_uuid]['connect'] = ws
                    self.connected['client'][user_uuid]['user_group_id'] = user_group_id
                    # logging.info(f'{self.connected}')
                except Exception as e:
                    error = str(e)
                    logging.error(f'error in distribute parsing: {error}')
        except Exception as e:
            error = str(e)
            logging.error(f'error in distribute for loop: {error}')


    async def main(self):
        # Perform connection
        connection = await connect(host=self.rabbit_host,
                                   port=self.rabbit_port,
                                   login=self.rabbit_user,
                                   password=self.rabbit_password,
                                   virtualhost=self.rabbit_vhost)
        # Creating a channel
        try:
            channel = await connection.channel()
        except Exception as e:
            print(str(e))

        # Declaring queue
        try:
            queue = await channel.declare_queue(self.rabbit_queue)
        except Exception as e:
            print(str(e))
            logging.error(str(e))
        # await queue.consume(self.on_message, no_ack=True)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    print(message.body)
                    logging.info(message.body)
                    get_message = json.loads(message.body)
                    try:
                        for key, val in server.connected.items():
                            try:
                                for k, v in val.items():
                                    try:
                                        if int(v['user_group_id']) == int(get_message['user_group']):
                                            try:
                                                if roxywi_common.check_user_group(user_group_id=int(v['user_group_id']), user_uuid=k):
                                                    await self.send_to_clients(get_message['message'], v['connect'])
                                                    logging.info(get_message['message'])
                                            except Exception as e:
                                                error = str(e)
                                                logging.error('second if ' + error)
                                    except Exception as e:
                                        error = str(e)
                                        logging.error('first if ' + error)
                            except Exception as e:
                                error = str(e)
                                logging.error('second ' + error)
                    except Exception as e:
                        error = str(e)
                        logging.error('first ' + error)
                if queue.name in message.body.decode():
                    continue
        await connection.close()


async def timerThread(server):
    while True:
        time.sleep(5)
        await server.main()


# helper routine to allow thread to call async function
def between_callback(server):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(timerThread(server))
    loop.close()


# start server
server = Server()
start_server = websockets.serve(server.ws_handler, '127.0.0.1', 8765)

# start timer thread
threading.Thread(target=between_callback,args=(server,)).start()

# start main event loop
loop = asyncio.get_event_loop()
loop.run_until_complete(start_server)
loop.run_forever()
