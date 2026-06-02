import socket
import ssl
import threading
import select
import logging
from enum import Enum
import time
import json


class MessageType(Enum):
    """Enum class to represent the message types"""
    start_daq = 'start_rec'
    stop_daq = 'stop'
    start_daq_pulses = 'start_pulses'
    stop_daq_pulses = 'stop_pulses'
    start_daq_viewing = 'start_viewing'
    poll_status = 'status_poll'
    start_video_rec = 'start_rec'
    start_video_view = 'start_viewing'
    stop_video = 'stop'
    start_video_calibrec = 'start_calibrec'
    status = 'status'
    response = 'response'
    disconnected = 'disconnected'
    copy_files = 'copy_files'
    purge_files = 'purge_files'


class MessageStatus(Enum):
    """Enum class to represent status"""
    ready = 'ready'
    error = 'error'
    viewing = 'viewing'
    recording = 'recording'
    viewing_ok = 'viewing_ok'
    recording_ok = 'recording_ok'
    recording_fail = 'recording_fail'
    stop_ok = 'stop_ok'
    pulsing_ok = 'pulsing_ok'
    calib_ok = 'calib_ok'
    copy_ok = 'copy_ok'
    copy_fail = 'copy_fail'


class SocketMessage:
    """
    Class to represent the individual socket messages. Contains attributes such as session id etc.
    """
    status_error = {'type': MessageType.status.value, 'status': MessageStatus.error.value}
    status_ready = {'type': MessageType.status.value, 'status': MessageStatus.ready.value}
    status_recording = {'type': MessageType.status.value, 'status': MessageStatus.recording.value}
    status_viewing = {'type': MessageType.status.value, 'status': MessageStatus.viewing.value}

    respond_recording = {'type': MessageType.response.value, 'status': MessageStatus.recording_ok.value}
    respond_recording_fail = {'type': MessageType.response.value, 'status': MessageStatus.recording_fail.value}
    respond_viewing = {'type': MessageType.response.value, 'status': MessageStatus.viewing_ok.value}
    respond_stop = {'type': MessageType.response.value, 'status': MessageStatus.stop_ok.value}
    respond_pulsing = {'type': MessageType.response.value, 'status': MessageStatus.pulsing_ok.value}
    respond_calib = {'type': MessageType.response.value, 'status': MessageStatus.calib_ok.value}
    respond_copy = {'type': MessageType.response.value, 'status': MessageStatus.copy_ok.value}
    respond_copy_fail = {'type': MessageType.response.value, 'status': MessageStatus.copy_fail.value}
    client_disconnected = {'type': MessageType.disconnected.value}

    def __init__(self):
        self._session_path = None
        self._fps = 30
        self._session_id = "test"
        self._daq_setting_file = ''
        self._basler_setting_file = ''
        self._pulse_lag = 0
        self.start_daq = {'type': MessageType.start_daq.value, 'session_id': self._session_id,
                          'setting_file': self._daq_setting_file}
        self.stop_daq = {'type': MessageType.stop_daq.value}
        self.start_daq_pulses = {'type': MessageType.start_daq_pulses.value, 'fps': self._fps,
                                 'pulse_lag': self._pulse_lag}
        self.stop_daq_pulses = {'type': MessageType.stop_daq_pulses.value}
        self.start_daq_viewing = {'type': MessageType.start_daq_viewing.value, 'session_id': self._session_id,
                                  'setting_file': self._daq_setting_file}
        self.poll_status = {'type': MessageType.poll_status.value}

        self.start_video_rec = {'type': MessageType.start_video_rec.value, 'session_id': self._session_id,
                                'setting_file': self._basler_setting_file, 'frame_rate': self._fps}
        self.start_video_view = {'type': MessageType.start_video_view.value, 'session_id': self._session_id,
                                 'setting_file': self._basler_setting_file, 'frame_rate': self._fps}
        self.stop_video = {'type': MessageType.stop_video.value}

        self.start_video_calibrec = {'type': MessageType.start_video_calibrec.value, 'session_id': 'calibration',
                                     'setting_file': self._basler_setting_file, 'frame_rate': 5}

        self.copy_files = {'type': MessageType.copy_files.value, 'session_id': self._session_id,
                                     'session_path': self._session_path}
        self.purge_files = {'type': MessageType.purge_files.value, 'session_id': self._session_id}

    @property
    def pulse_lag(self):
        """The lag  for the mcc pulsing in milliseconds"""
        return self._pulse_lag

    @pulse_lag.setter
    def pulse_lag(self, value: int):
        self._pulse_lag = value
        self.update_messages()

    @property
    def session_id(self):
        """The session id for the current session"""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        self._session_id = value
        self.update_messages()

    @property
    def session_path(self):
        """The session path for the current session"""
        return self._session_path

    @session_path.setter
    def session_path(self, value: str):
        self._session_path = value
        self.update_messages()

    @property
    def fps(self):
        """The frame rate for the video recording in frames per second"""
        return self._fps

    @fps.setter
    def fps(self, value: float):
        self._fps = value
        self.update_messages()

    @property
    def daq_setting_file(self):
        """The setting file for the daq device"""
        return self._daq_setting_file

    @daq_setting_file.setter
    def daq_setting_file(self, value: str):
        self._daq_setting_file = value
        self.update_messages()

    @property
    def basler_setting_file(self):
        """The setting file for the FreiPoseRecorder tool"""
        return self._basler_setting_file

    @basler_setting_file.setter
    def basler_setting_file(self, value: str):
        self._basler_setting_file = value
        self.update_messages()

    def update_messages(self):
        """Updates the messages with the current values"""
        self.start_daq.update(**{'session_id': self.session_id, 'setting_file': self.daq_setting_file})
        self.start_daq_viewing.update(**{'session_id': self._session_id,
                                         'setting_file': self.daq_setting_file})
        self.start_daq_pulses.update(**{'fps': self.fps, 'pulse_lag': self.pulse_lag})
        self.start_video_rec.update(**{'session_id': self.session_id, 'setting_file': self.basler_setting_file,
                                       'frame_rate': self.fps})
        self.start_video_view.update(**{'session_id': self._session_id, 'setting_file': self.basler_setting_file,
                                        'frame_rate': self.fps})
        self.start_video_calibrec.update(**{'session_id': 'calibration', 'setting_file': self.basler_setting_file})
        self.copy_files.update(**{'session_id': self.session_id, 'session_path': self._session_path})
        self.purge_files.update(**{'session_id': self._session_id})


class SocketComm:
    """
    Socket communication class. Enables server-client communitation via network.
    """
    def __init__(self, type: str = "server", host: str = "localhost", port: int = 8800, use_ssl: bool = False):
        self.acception_thread = None
        self.ssl_sock = None
        self.sock = None
        self._sock = None
        self._ssl_sock = None
        self.type = type
        self.host = host
        self.port = port
        if self.type == "server":
            self.context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        else:
            self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        # self.context.set_ciphers('DEFAULT')
        self.use_ssl = use_ssl # this doesnt work yet get some weird error from ssl module
        self.connected = False
        self.stop_event = threading.Event()
        self.log = logging.getLogger(f"SocketComm_{self.type}")
        self.log.setLevel(logging.DEBUG)
        self.message_time = time.monotonic()

    def create_socket(self):
        """"""
        if self._sock is not None:  # don't recreate socket if already exists
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.type == 'client':
            pass
        elif self.type == 'server':
            try:
                self._sock.bind((self.host, self.port))
            except OSError:
                self.log.warning('Adress already in use.. need to delete somehow ?')
            self._sock.listen()
            if self.use_ssl:
                self._ssl_sock = self.context.wrap_socket(self._sock, server_side=True, do_handshake_on_connect=False)

    def accept_connection(self):
        self.create_socket()
        while not self.stop_event.is_set():
            if time.monotonic() - self.message_time > 5:
                self.message_time = time.monotonic()
                self.log.debug('waiting for connection...')
            if self.use_ssl:
                ready, _, _ = select.select([self._ssl_sock], [], [], 0.1)
                if ready:
                    self.ssl_sock, self.addr = self._ssl_sock.accept()
                    self.ssl_sock.settimeout(0.1)
                    self.connected = True
                    self.log.info(f"Connected to {self.addr}")
                    break
            else:
                ready, _, _ = select.select([self._sock], [], [], 0.1)
                if ready:
                    self.sock, self.addr = self._sock.accept()
                    self.sock.settimeout(0.1)
                    self.connected = True
                    self.log.info(f"Connected to {self.addr}")
                    break
        else:
            self.log.debug("Stop event set. Stopping thread...")
            return

    def threaded_accept_connection(self):
        """
        Accepts connection in a separate thread, to not block the main thread
        """
        self.stop_event.set() #exit old acceptance thread
        self.stop_event.clear() #reset for new thread
        self.acception_thread = threading.Thread(target=self.accept_connection)
        self.acception_thread.start()

    def stop_waiting_for_connection(self):
        """
        sets the stop event, so the thread will stop waiting for a connection
        """
        self.stop_event.set()

    def connect(self) -> bool:
        """
        Connects to the server
        returns: True if connection was successful, False otherwise
        """
        if self.type == 'client':
            if self.use_ssl:
                self.ssl_sock = self.context.wrap_socket(self._sock, server_hostname=self.host,
                                                         do_handshake_on_connect=False)
            else:
                self.sock = self._sock
                self.sock.settimeout(0.1)  # otherwise we get issues if nothing is comming
            self._connect(self.host, self.port)
            self.connected = True
            return True
        else:
            return False
            # raise RuntimeError("Error: Cannot connect on server socket")

    def close_socket(self):
        if self.use_ssl:
            if self.ssl_sock:
                self.ssl_sock.close()
            self._ssl_sock.close()
        if self.sock: #client connection
            self.sock.close()
        if self._sock:  #socket
            self._sock.close()
            self._sock = None
        self.connected = False

    def close_client_socket(self):
        """close only the client connection,but keep socket open"""
        if self.sock: #client connection
            self.sock.close()
            self.sock = None
        self.connected = False

    def read_json_message(self) -> dict:
        """
        reads message from socket and decodes it into dict
        returns: dict
        """
        try:
            message = self._recv_until(b'\n')
            if message is not None:
                message = json.loads(message.decode())
            else:
                return message
        except json.decoder.JSONDecodeError:
            message = None
        return message

    def read_json_message_fast(self) -> dict:
        try:
            message = self._recv(1024)
            if message == -1:
                return SocketMessage.client_disconnected
            if message is not None:
                message = json.loads(message.decode())
            else:
                return message
        except json.decoder.JSONDecodeError:
            message = None
            print('message decoding failed')
        return message

    def read_json_message_fast_linebreak(self) -> dict:
        """
        reads message from socket. Message is read until a linebreak charakter is fond
        The messge ist then decoded into dictionary
        returns: dict
        """
        if self.sock is None:
            return None
        try:
            message = self._recv_until(b'\n')
            if message == -1:
                return SocketMessage.client_disconnected
            if message is not None:
                message = json.loads(message.decode())
        except json.decoder.JSONDecodeError:
            message = None
            print('message decoding failed')
        return message

    def send_json_message(self, message: dict):
        message = json.dumps(message).encode()
        message += b'\n'
        self._send(message)

    def _connect(self, host, port):
        if self.use_ssl:
            self.ssl_sock.connect((host, port))
        else:
            self.sock.connect((host, port))

    def _send(self, data):
        try:
            if self.use_ssl:
                self.ssl_sock.sendall(data)
            else:
                self.sock.sendall(data)
        except ConnectionResetError:
            self.log.error("Connection reset by peer")

    def _recv(self, size) -> (bytes, int):
        try:
            if self.use_ssl:
                return self.ssl_sock.recv(size)
            else:
                return self.sock.recv(size)
        except socket.timeout:
            return None
        except ConnectionResetError:
            self.log.warning("Client disconnected")
            return -1

    def _recv_until(self, delimiter) -> bytes:
        data = b''
        try:
            if self.use_ssl:
                while not data.endswith(delimiter):
                    data += self.ssl_sock.recv(1)
            else:
                while not data.endswith(delimiter):
                    data += self.sock.recv(1)
        except socket.timeout:
            data = None
        except ConnectionResetError:
            self.log.warning("Client disconnected")
            data = -1
        return data

    def _recv_all(self):
        data = b''
        if self.use_ssl:
            while True:
                try:
                    data += self.ssl_sock.recv(1024)
                except socket.timeout:
                    break
        else:
            while True:
                try:
                    data += self.sock.recv(1024)
                except socket.timeout:
                    break
        return data


if __name__ == "__main__":
    import time
    import argparse
    import json

    """
    parser = argparse.ArgumentParser(description='Socket communication test')
    parser.add_argument('--type', type=str, default='server', help='Socket type: client or server')
    parser.add_argument('--host', type=str, default='localhost', help='Host IP address')
    parser.add_argument('--port', type=int, default=8800, help='Port number')
    parser.add_argument('--use_ssl', type=bool, default=False, help='Use SSL')
    args = parser.parse_args()

    sock = SocketComm('server')
    sock.create_socket()
    sock.threaded_accept_connection()
    while not sock.connected:
        print('no connection established,waiting...')
        time.sleep(1)
    try:
        data = sock.read_json_message()
        print(data)
    except Exception as e:
        print(e)
        pass
    sock.close_socket()
    """

    import json
    sock = SocketComm('client',port=8880)
    sock.create_socket()
    sock.connect()
    time.sleep(0.5)
    response = sock.read_json_message_fast()

    # print(response)
    # message = {'type': 'start_rec', 'session_id': 'test2', 'setting_file': ''}
    # time.sleep(5)
    # print("sending message")
    # sock._send(json.dumps(message).encode())
    # time.sleep(25)
    # print("sending stop")
    # message = {'type': 'stop'}
    # sock._send(json.dumps(message).encode())
    # sock.close_socket()