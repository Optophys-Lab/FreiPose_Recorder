import time
from utils.socket_utils import SocketComm, SocketMessage

HOST = "127.0.0.1"
PORT = 8881
FPS = 30
RECORDING_DURATION = 10  # seconds, for testing

sock = SocketComm('client', host=HOST, port=PORT)
sock.create_socket()
sock.connect()
sock.sock.settimeout(2.0)
print("Connected to FreiPose")

response = sock.read_json_message()
print("Initial message:", response)

sock.send_json_message({'type': 'status_poll'})
time.sleep(1.0)
response = sock.read_json_message()
print("Status:", response)

sock.send_json_message({
    'type': 'start_rec',
    'session_id': 'test_session_001',
    'setting_file': '',
    'frame_rate': FPS
})
time.sleep(1.0)
response = sock.read_json_message()
print("Recording response:", response)

# Wait for recording duration
time.sleep(RECORDING_DURATION)

sock.send_json_message({'type': 'stop'})
time.sleep(1.0)
response = sock.read_json_message()
print("Stop response:", response)

sock.send_json_message({'type': 'disconnected'})
time.sleep(0.5)
sock.close_socket()
print("Done")