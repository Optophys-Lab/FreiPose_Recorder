import time
from socket_utils import SocketComm, SocketMessage

HOST = "127.0.0.1"
PORT = 8881

sock = SocketComm('client', host=HOST, port=PORT)
sock.create_socket()
sock.connect()
sock.sock.settimeout(2.0)  # override default 0.1s timeout
print("Connected to FreiPose")

time.sleep(1.0)  # wait for FreiPose to send status_ready

response = sock.read_json_message()
print("Initial message:", response)

sock.send_json_message({'type': 'status_poll'})
time.sleep(1.0)
response = sock.read_json_message()
print("Status:", response)

sock.close_socket()