import serial
import time
from FreiPose_Recorder.configs.params import MAX_FPS

class TriggerArduino:
    def __init__(self, serial_port):
        self.device = None
        self.device = serial.Serial(serial_port, timeout=1)
        self._fps = 30

        # arduino commands
        self._ping_cmd = b'P\r'
        self._start_cmd = b'S%d\n'
        self._stop_cmd = b'Q\r'
        self._send_string_cmd =b'T%s\r'
        
    def __del__(self):
        if self.device is not None:
            self.device.close()

    def ping(self):
        self.device.write(self._ping_cmd)
        time.sleep(0.1)
        s = self.device.read(100)
        print('pong=', self._pretty_str(s))

    @property
    def fps(self):
        return self._fps

    @fps.setter
    def fps(self, fps):
        fps = float(fps)
        if fps < 1 or fps >= MAX_FPS:
            print('Invalid fps value', fps)
            return
        self._fps = fps

    def start(self):
        self.device.write(self._start_cmd % self._fps)
        
    def send_string(self, string2send):
        self.device.write(self._send_string_cmd % string2send.encode('utf-8'))

    def end(self):
        self.device.write(self._stop_cmd)

    def _pretty_str(self, s):
        s = s.decode('utf-8')
        s = s.replace('\n', '')
        s = s.replace('\r', '')
        s = s.replace('>', '')
        return s


if __name__ == '__main__':
    mod = TriggerArduino()
    mod.ping()
    mod.fps = 2.0
    mod.start()
    time.sleep(10.0)
    mod.end()


