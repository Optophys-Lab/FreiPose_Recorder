"""
Tool to record videos from multiple Basler cameras synchronously. Based on RecTool by Christian.

Author: Artur artur.schneider@biologie.uni-freiburg.de

Planned features:
- save timestamps from taken frames
- visualize calibration detection ?
- record calibration pattern with processing ?
- implement hardware trigger control !

TODO:
- test recording speeds / loosing frames
- test hardware triggering
"""

import json
import logging
import sys
import time


from queue import Empty
from threading import Event

from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PyQt6.QtCore import QTimer
from PyQt6 import uic, QtGui, QtSerialPort


from pathlib import Path
from core.Recorder_my import Recorder
from ImageViewer import SingleCamViewer, RemoteConnDialog, TagDetector_other
from utils.StitchedImage import StitchedImage
from utils.socket_utils import SocketComm
from core.Trigger import TriggerArduino
log = logging.getLogger('main')
log.setLevel(logging.DEBUG)

# logging.basicConfig(filename='GUI_run.log', filemode='w', format='%(asctime)s - %(levelname)s - %(message)s')

VERSION = "0.4.2"
HOST = "localhost"  # if connecting to remote, use the IP of the current machine
PORT = 8880
USE_ARDUINO_TRIGGER = False


class BASLER_GUI(QMainWindow):
    def __init__(self):
        super(BASLER_GUI, self).__init__()
        self.trigger_timer = None
        self.session_id = "test_sess"
        self.single_camviewer = None
        self.multi_view_timer = None
        self.stop_event = None
        self.single_view_timer = None
        self.path2file = Path(__file__)
        uic.loadUi(self.path2file.parent / 'GUI' / 'GUI_design.ui', self)
        self.setWindowTitle(f'FreiPose Recorder v.{VERSION}')
        self.log = logging.getLogger('GUI')
        self.log.setLevel(logging.DEBUG)

        codec_to_try = ["h264_nvenc", "libx264", "mpeg4", "mpeg2video", "libxvid", "libx264rgb"]
        self.Codec_comboBox.addItems(codec_to_try)

        self.RUNButton.setIcon(QtGui.QIcon("GUI/icons/play.svg"))
        self.RECButton.setIcon(QtGui.QIcon("GUI/icons/record.svg"))
        self.STOPButton.setIcon(QtGui.QIcon("GUI/icons/stop.svg"))
        self.RemoteModeButton.setIcon(QtGui.QIcon("GUI/icons/Signal.svg"))
        self.ConnectButton.setIcon(QtGui.QIcon("GUI/icons/connect.svg"))
        self.Save_pathButton.setIcon(QtGui.QIcon("GUI/icons/folder.svg"))
        self.SettingsSaveButton.setIcon(QtGui.QIcon("GUI/icons/DocumentArrowDown.svg"))
        self.SettingsLoadButton.setIcon(QtGui.QIcon("GUI/icons/DocumentArrowUp.svg"))
        self.ShowSingleCamButton.setIcon(QtGui.QIcon("GUI/icons/Camera.svg"))
        self.FlipXButton.setIcon(QtGui.QIcon("GUI/icons/ArrowsRightLeft.svg"))
        self.FlipYButton.setIcon(QtGui.QIcon("GUI/icons/ArrowsUpDown.svg"))
        #self.CameraSettings2.toolbox.setIcon(QtGui.QIcon("GUI/icons/AdjustmentsHorizontal.svg"))

        self.ConnectSignals()
        self.basler_recorder = Recorder()
        self.scan_cams()
        self.socket_comm = SocketComm(type='server', host=HOST, port=PORT)
        self.socket_comm.create_socket()
        self.is_remote_ctr = False
        if USE_ARDUINO_TRIGGER:
            serial_port = f"/dev/{QtSerialPort.QSerialPortInfo.availablePorts()[0].portName()}"
            #TODO for windows use the port name
            self.trigger = TriggerArduino(serial_port)
        else:
            self.trigger = None
        self.TagDetector = TagDetector_other()

    ### Device Connectivity ####
    def scan_cams(self):
        found_cams = self.basler_recorder.get_cam_info()
        nr_cams = len(found_cams)
        if nr_cams > 0:
            found_cams = '\n'.join(found_cams)
            self.Devices_textEdit.clear()
            self.Devices_textEdit.setText(f"Found cameras SN:\n{found_cams}")

            self.ConnectButton.setEnabled(True)
            self.ScanDevButton.setEnabled(False)
        else:
            self.Devices_textEdit.clear()
            self.Devices_textEdit.setText(f"Found no cameras !!")
        self.MultiViewWidget.num_cameras = nr_cams
        self.CameraSettings2.num_cameras = nr_cams

    def connect_to_cams(self):
        self.basler_recorder.connect_cams()

        for c_id, cam in enumerate(self.basler_recorder.cam_array):
            self.CameraSettings2.toolbox.setItemText(c_id, cam.DeviceInfo.GetUserDefinedName())
            self.CameraSettings2.exposure_spin_list[c_id].blockSignals(True)  # block triggering of events
            self.CameraSettings2.gain_spin_list[c_id].blockSignals(True)
            self.CameraSettings2.exposure_spin_list[c_id].setValue(self.basler_recorder.get_cam_exposureTime(cam))
            self.CameraSettings2.gain_spin_list[c_id].setValue(self.basler_recorder.get_cam_gain(cam))
            gain_limits, exp_limits, colormodes = self.basler_recorder.get_cam_limits(cam)
            if exp_limits:
                self.CameraSettings2.exposure_spin_list[c_id].setMinimum(exp_limits[0])
                self.CameraSettings2.exposure_spin_list[c_id].setMaximum(exp_limits[1])
            if gain_limits:
                self.CameraSettings2.gain_spin_list[c_id].setMinimum(gain_limits[0])
                self.CameraSettings2.gain_spin_list[c_id].setMaximum(gain_limits[1])
            # add color modes to list
            self.CameraSettings2.color_mode_list[c_id].clear()
            self.CameraSettings2.color_mode_list[c_id].addItems(colormodes)
            self.CameraSettings2.exposure_spin_list[c_id].blockSignals(False)  # unblock triggering of events
            self.CameraSettings2.gain_spin_list[c_id].blockSignals(False)

        self.CameraSettings2.toolbox.setCurrentIndex(0)
        self.RUNButton.setEnabled(True)
        self.RECButton.setEnabled(True)
        self.RemoteModeButton.setEnabled(True)
        self.ConnectButton.setEnabled(False)

    def run_cams(self):
        self.stop_event = Event()
        self.basler_recorder.fps = self.FrameRateSpin.value()
        self.number_cams = self.basler_recorder.cam_array.GetSize()
        use_hw_trigger = self.HWTrig_checkBox.isChecked()
        self.basler_recorder.run_multi_cam_show(self.stop_event, use_hw_trigger)

        self.multi_view_timer = QTimer()
        self.multi_view_timer.timeout.connect(self.update_multi_view)
        self.multi_view_timer.start(10)  # make depending on frame rate ..? this should be enough for 100 fps ?
        # self.singleview_thread = Thread(target = self.update_single_view)
        # self.singleview_thread.start()
        self.STOPButton.setEnabled(True)
        self.RUNButton.setEnabled(False)
        self.RECButton.setEnabled(False)
        self.ShowSingleCamButton.setEnabled(False)
        self.FrameRateSpin.setEnabled(False)  # or implement on the go change of the framerate...

        for color_mode in self.CameraSettings2.color_mode_list:
            color_mode.setEnabled(False)


        #create a time that executes the trigger after 500 ms delay to make sure cameras are ready
        if self.trigger and use_hw_trigger:
            self.trigger.fps = self.FrameRateSpin.value()
            self.trigger_timer = QTimer()
            self.trigger_timer.setSingleShot(True)
            self.trigger_timer.timeout.connect(self.trigger.start)
            self.trigger_timer.start(500)

    def update_multi_view(self):
        # call this from a thread ? or maybe not
        try:
            t0 = time.monotonic()
            for c_id in range(self.number_cams):
                curr_image = self.basler_recorder.multi_view_queue[c_id].get_nowait()
                if self.DisableViz_checkBox.isChecked():
                    continue  # return fast
                else:
                    self.MultiViewWidget.cam_viewers[c_id].updateView(curr_image)
            # self.log.debug(f"Nr elements in q {self.basler_recorder.single_view_queue.qsize()}")
            # t0 = time.monotonic()
            # stitched_image = StitchedImage(image_list).image
            #print(f'It took {(time.monotonic() - t0):0.3f} s to put all images up')
        except Empty:
            return
        writerstatus = f"\tVideoWriter {self.basler_recorder.video_writer_list[0].get_state()}" if len(self.basler_recorder.video_writer_list)>1 else "not recording"
        self.statusbar.showMessage(f"In Q :{self.basler_recorder.multi_view_queue[0].qsize()}"
                                   f"/In Q2: {self.basler_recorder.multi_view_queue[1].qsize()}"
                                   f"{writerstatus}")
        # self.ViewWidget.updateView(currentImg)
        # self.ViewWidget.updateView(stitched_image)

    def update_multi_view_singlewindow(self):
        # call this from a thread ? maybe not seems to work so far
        try:
            image_list = []  # * self.number_cams
            for c_id in range(self.number_cams):
                image_list.append(self.basler_recorder.multi_view_queue[c_id].get_nowait())
            # self.log.debug(f"Nr elements in q {self.basler_recorder.single_view_queue.qsize()}")
            t0 = time.monotonic()
            stitched_image = StitchedImage(image_list).image
            print(f'It took {(time.monotonic() - t0):0.3f} s to stitch images')
        except Empty:
            return
        self.statusbar.showMessage(f"In Q :{self.basler_recorder.multi_view_queue[0].qsize()}")
        # self.ViewWidget.updateView(currentImg)
        self.ViewWidget.updateView(stitched_image)

    def start_recording(self):
        self.stop_event = Event()
        session_id = self.SessionIDlineEdit.text()
        if session_id:
            self.session_id = session_id
        self.basler_recorder.fps = self.FrameRateSpin.value()
        self.basler_recorder.codec = self.Codec_comboBox.currentText()
        self.basler_recorder.crf = self.crf_spinBox.value()
        self.number_cams = self.basler_recorder.cam_array.GetSize()
        use_hw_trigger = self.HWTrig_checkBox.isChecked()

        self.basler_recorder.run_multi_cam_record(self.stop_event, filename=self.session_id,
                                                  use_hw_trigger=use_hw_trigger)

        self.multi_view_timer = QTimer()
        self.multi_view_timer.timeout.connect(self.update_multi_view)
        self.multi_view_timer.start(10)  # dependign on frame rate ..

        self.STOPButton.setEnabled(True)
        self.RUNButton.setEnabled(False)
        self.RECButton.setEnabled(False)
        self.ShowSingleCamButton.setEnabled(False)

        self.AutoExposeButton.setEnabled(False)
        self.AutoGainButton.setEnabled(False)
        self.WhiteBalanceButton.setEnabled(False)
        self.FlipXButton.setEnabled(False)
        self.FlipYButton.setEnabled(False)
        self.CameraSettings2.toolbox.setEnabled(False)
        self.All_cams_checkBox.setEnabled(False)
        self.SettingsSaveButton.setEnabled(False)
        self.SettingsLoadButton.setEnabled(False)
        self.FrameRateSpin.setEnabled(False)

        #create a time that executes the trigger after 500 ms delay to make sure cameras are ready
        if self.trigger and use_hw_trigger:
            self.trigger.fps = self.FrameRateSpin.value()
            self.trigger_timer = QTimer()
            self.trigger_timer.setSingleShot(True)
            self.trigger_timer.timeout.connect(self.trigger.start)
            self.trigger_timer.start(500)

    def stop_cams(self):
        if self.stop_event:
            self.stop_event.set()
        self.log.debug('Stopping grabbing')
        # self.basler_recorder.single_view_queue.join() # as this its not being emptied in a thread.. queue is not emptied but stucks here
        if self.single_view_timer:
            self.single_view_timer.stop()
            self.single_view_timer = None
            self.basler_recorder.stop_single_cam_show()

        if self.multi_view_timer:
            if self.basler_recorder.is_recording:
                self.basler_recorder.stop_multi_cam_record()
            else:
                self.basler_recorder.stop_multi_cam_show()
            self.multi_view_timer.stop()
            self.multi_view_timer = None

        if self.single_camviewer:
            if self.single_camviewer.isVisible():
                self.single_camviewer.close()
        self.statusbar.showMessage("Stopped Recording")
        # do i want to show remaining images ? not really..
        # maybe instead add an indicator of how many frames are in buffer ?
        self.STOPButton.setEnabled(False)
        if not self.is_remote_ctr:
            self.RUNButton.setEnabled(True)
            self.RECButton.setEnabled(True)
            self.ShowSingleCamButton.setEnabled(True)

            self.AutoExposeButton.setEnabled(True)
            self.AutoGainButton.setEnabled(True)
            self.WhiteBalanceButton.setEnabled(True)
            self.FlipXButton.setEnabled(True)
            self.FlipYButton.setEnabled(True)
            self.CameraSettings2.toolbox.setEnabled(True)
            self.All_cams_checkBox.setEnabled(True)
            self.SettingsSaveButton.setEnabled(True)
            self.SettingsLoadButton.setEnabled(True)
            self.FrameRateSpin.setEnabled(True)

        for color_mode in self.CameraSettings2.color_mode_list:
            color_mode.setEnabled(True)

    def show_single_cam(self):
        """
        Show single camera in a separate window
        """
        self.All_cams_checkBox.setChecked(False)  # uncheck to not mess up with settings

        current_camid = self.get_current_tab()
        self.stop_event = Event()
        self.basler_recorder.fps = self.FrameRateSpin.value()
        self.basler_recorder.run_single_cam_show(current_camid, self.stop_event)

        self.single_camviewer = SingleCamViewer(self, self.basler_recorder.cam_array[
            current_camid].DeviceInfo.GetUserDefinedName())
        self.single_camviewer.show()

        self.single_view_timer = QTimer()
        self.single_view_timer.timeout.connect(self.update_single_view)
        self.single_view_timer.start(10)  # dependign on frame rate ..
        # self.singleview_thread = Thread(target = self.update_single_view)
        # self.singleview_thread.start()
        self.STOPButton.setEnabled(True)
        self.RUNButton.setEnabled(False)
        self.RECButton.setEnabled(False)
        self.ShowSingleCamButton.setEnabled(False)

    def update_single_view(self):
        """
        Updates the single view widget with the current image in the queue
        """
        try:
            currentImg = self.basler_recorder.single_view_queue.get_nowait()
            _,currentImg = self.TagDetector.detect(currentImg)
            # self.log.debug(f"Nr elements in q {self.basler_recorder.single_view_queue.qsize()}")
            self.statusbar.showMessage(f"In Q :{self.basler_recorder.single_view_queue.qsize()}")
        except Empty:  # if queue is empty just return
            return
        # self.ViewWidget.updateView(currentImg)
        self.single_camviewer.updateView(currentImg)

    #### SETTIGNS ###
    def save_settings(self):
        """
        Save current camera settings to a json file
        """
        if not self.basler_recorder.cams_connected:
            self.log.info('Not connected to cameras cant save settings')

            QMessageBox.information(self,
                                    "Info",
                                    "Not connected to cameras, cant save settings",
                                    buttons=QMessageBox.StandardButton.Ok)
            return

        # get active camera settings.. save those to json with cam name
        cam_lib = {}
        for cam in self.basler_recorder.cam_array:
            cam_settings = self.basler_recorder.get_cam_settings(cam)
            cam_lib.update(**cam_settings)

        cam_lib.update(**{'save_path': self.basler_recorder.save_path, 'fps': self.FrameRateSpin.value(),
                          "HW_trigg": self.HWTrig_checkBox.isChecked(), 'codec': self.Codec_comboBox.currentText(),
                          "crf": self.crf_spinBox.value()})

        # open file dialog for where to save
        settings_file = QFileDialog.getSaveFileName(self,'Save settings file', "",
                                                    "Settings files name (*.settings.json)")
        if settings_file[0]:
            filename = settings_file[0]
            if len(filename.split(".")) < 2:
                filename += '.settings.json'
            with open(filename, 'w') as fi:
                json.dump(cam_lib, fi, indent=4)

    def load_settings(self, file: (str, Path, None) = None):
        """
        Load camera settings from a json file
        """
        if not self.basler_recorder.cams_connected:
            self.log.info('Not connected to cameras cant save settings')

            QMessageBox.information(self,
                                    "Info",
                                    "Not connected to cameras, cant save settings",
                                    buttons=QMessageBox.StandardButton.Ok)
            return

        if file is None or not file:
            settings_file = QFileDialog.getOpenFileName(self, 'Open settings file', "",
                                                        "Settings files (*.settings.json)")
            if settings_file[0]:
                file = settings_file[0]
            else:
                return

        with open(file, 'r') as fi:
            cam_lib = json.load(fi)

        for cam in self.basler_recorder.cam_array:
            try:
                settings = cam_lib[cam.DeviceInfo.GetUserDefinedName()]
            except KeyError:
                self.log.info(f'No settings found for cam: {cam.DeviceInfo.GetUserDefinedName()} '
                              f'with SN: {cam.DeviceInfo.GetSerialNumber()}')
                continue
            self.basler_recorder.set_cam_settings(cam, settings)

        try:
            self.HWTrig_checkBox.setChecked(cam_lib['HW_trigg'])
            self.crf_spinBox.setValue(cam_lib['crf'])
            self.Codec_comboBox.setCurrentText(cam_lib['codec'])
            self.FrameRateSpin.setValue(cam_lib['fps'])
            self.basler_recorder.save_path = cam_lib['save_path']
        except KeyError:
            self.log.info('No general settings found in file')

    def set_save_path(self, save_path: (str, Path, None) = None):
        """
        Set the path where to save the recordings
        """
        if save_path is None or not save_path:
            save_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if save_path:
            self.basler_recorder.save_path = save_path
            self.log.debug(f'Save path set to {save_path}')

    ## IMAGE CONTROL ####
    def get_current_tab(self) -> int:
        """Returns the ID of currently open tab"""
        return self.CameraSettings2.toolbox.currentIndex()

    # those functions are now blocking ? maybe make sure they r not ? create threads for actual adjustments ?
    def auto_expose(self):
        """Runs autoexposure routine for given/all camera"""
        if self.All_cams_checkBox.isChecked():
            for current_camid in range(len(self.basler_recorder.cam_array)):
                final_exp = self.basler_recorder.run_auto_exposure(current_camid)
                #todo block triggerign of setting values !
                self.CameraSettings2.exposure_spin_list[current_camid].setValue(final_exp)
        else:
            current_camid = self.get_current_tab()
            final_exp = self.basler_recorder.run_auto_exposure(current_camid)
            self.CameraSettings2.exposure_spin_list[current_camid].setValue(final_exp)

    def auto_gain(self):
        """Runs autogain routine for given/all camera"""
        if self.All_cams_checkBox.isChecked():
            for current_camid in range(len(self.basler_recorder.cam_array)):
                final_gain = self.basler_recorder.run_auto_gain(current_camid)
                self.CameraSettings2.gain_spin_list[current_camid].setValue(final_gain)
        else:
            current_camid = self.get_current_tab()
            final_gain = self.basler_recorder.run_auto_gain(current_camid)
            self.CameraSettings2.gain_spin_list[current_camid].setValue(final_gain)

    def white_balance(self):
        """Runs auto white balance routine for given/all camera"""
        if self.All_cams_checkBox.isChecked():
            for current_camid in range(len(self.basler_recorder.cam_array)):
                self.basler_recorder.run_white_balance(current_camid)
        else:
            current_camid = self.get_current_tab()
            self.basler_recorder.run_white_balance(current_camid)

    def set_gain_exposure(self):
        """set the gain and exposure time for the current camera"""
        current_camid = self.get_current_tab()
        exp_time = self.CameraSettings2.exposure_spin_list[current_camid].value()
        gain = self.CameraSettings2.gain_spin_list[current_camid].value()
        self.basler_recorder.set_gain_exposure(current_camid, gain, exp_time)

    def set_color_mode(self, color_mode:str):
        """set the gain and exposure time for the current camera"""
        current_camid = self.get_current_tab()
        self.basler_recorder.set_color_mode(current_camid, color_mode)
        #exp_time = self.CameraSettings2.exposure_spin_list[current_camid]

    def flip_x(self):
        """
        Flip image on x axis
        """
        current_camid = self.get_current_tab()
        self.basler_recorder.flip_image_x(current_camid)

    def flip_y(self):
        """
        Flip image on y axis
        """
        current_camid = self.get_current_tab()
        self.basler_recorder.flip_image_y(current_camid)

    #### APP MAINTANCE #######
    def ConnectSignals(self):
        self.ScanDevButton.clicked.connect(self.scan_cams)
        self.ConnectButton.clicked.connect(self.connect_to_cams)
        self.RUNButton.clicked.connect(self.run_cams)
        self.RECButton.clicked.connect(self.start_recording)
        self.STOPButton.clicked.connect(self.stop_cams)

        self.SettingsSaveButton.clicked.connect(self.save_settings)
        self.SettingsLoadButton.clicked.connect(self.load_settings)

        self.AutoExposeButton.clicked.connect(self.auto_expose)
        self.AutoGainButton.clicked.connect(self.auto_gain)
        self.WhiteBalanceButton.clicked.connect(self.white_balance)
        self.FlipXButton.clicked.connect(self.flip_x)
        self.FlipYButton.clicked.connect(self.flip_y)

        self.ShowSingleCamButton.clicked.connect(self.show_single_cam)

        self.Save_pathButton.clicked.connect(self.set_save_path)
        self.RemoteModeButton.clicked.connect(self.remote_mode)


    def remote_mode(self):
        if not self.socket_comm.connected:
            self.socket_comm.threaded_accept_connection()
            remote_dialog = RemoteConnDialog(self.socket_comm, self)
            remote_dialog.exec()

            if not self.socket_comm.connected:
                self.log.debug('Aborted remote connection')
            else:
                self.log.debug('Connected')
                self.enter_remote_mode()
        else:
            # self.abort_remoteconnection()
            self.exit_remote_mode()

    def enter_remote_mode(self):
        self.Client_label.setText(f"Connected to Client:\n{self.socket_comm.addr}")
        self.RemoteModeButton.setText("EXIT\nREMOTE-mode")
        self.RemoteModeButton.setIcon(QtGui.QIcon("GUI/icons/SignalSlash.svg"))
        self.RUNButton.setEnabled(False)
        self.RECButton.setEnabled(False)
        self.ShowSingleCamButton.setEnabled(False)
        self.SettingsSaveButton.setEnabled(False)
        self.SettingsLoadButton.setEnabled(False)
        self.Save_pathButton.setEnabled(False)
        self.CameraSettings2.setEnabled(False)
        self.Codec_comboBox.setEnabled(False)
        self.crf_spinBox.setEnabled(False)
        self.HWTrig_checkBox.setEnabled(False)
        self.AutoExposeButton.setEnabled(False)
        self.AutoGainButton.setEnabled(False)
        self.WhiteBalanceButton.setEnabled(False)
        self.FlipXButton.setEnabled(False)
        self.FlipYButton.setEnabled(False)
        self.FrameRateSpin.setEnabled(False)
        self.SessionIDlineEdit.setEnabled(False)

        self.remote_message_timer = QTimer()
        self.remote_message_timer.timeout.connect(self.check_and_parse_messages)
        self.remote_message_timer.start(500)
        self.is_remote_ctr = True
        self.socket_comm._send(json.dumps({"type": "status", "status": "ready"}).encode())

    def exit_remote_mode(self):
        self.socket_comm.close_socket()
        self.Client_label.setText("disconnected")
        self.RemoteModeButton.setText("Enable\nREMOTE-mode")
        self.RemoteModeButton.setIcon(QtGui.QIcon("GUI/icons/Signal.svg"))
        if self.remote_message_timer:
            self.remote_message_timer.stop()
            self.remote_message_timer = None
        self.is_remote_ctr = False

        # enable all buttons
        self.RUNButton.setEnabled(True)
        self.RECButton.setEnabled(True)
        self.ShowSingleCamButton.setEnabled(True)
        self.SettingsSaveButton.setEnabled(True)
        self.SettingsLoadButton.setEnabled(True)
        self.FrameRateSpin.setEnabled(True)
        self.Save_pathButton.setEnabled(True)
        self.CameraSettings2.setEnabled(True)
        self.Codec_comboBox.setEnabled(True)
        self.crf_spinBox.setEnabled(True)
        self.HWTrig_checkBox.setEnabled(True)
        self.AutoExposeButton.setEnabled(True)
        self.AutoGainButton.setEnabled(True)
        self.WhiteBalanceButton.setEnabled(True)
        self.FlipXButton.setEnabled(True)
        self.FlipYButton.setEnabled(True)
        self.SessionIDlineEdit.setEnabled(True)
        self.SessionIDlineEdit.setText("")
    def check_and_parse_messages(self):
        message = self.socket_comm.read_json_message_fast()
        if message:
            # parse message
            if message['type'] == 'start_rec':
                self.log.info("got message to start recording")
                try:
                    if message["setting_file"]:
                        self.load_settings(message["setting_file"])
                        self.log.debug(f"loaded settings from {message['setting_file']}")
                except (FileNotFoundError, KeyError):
                    self.log.error("passed settings file not found")

                self.session_name = message["session_id"]
                self.SessionIDlineEdit.setText(self.session_name)
                self.remote_message_timer.setInterval(10000)  # increase the interval to 10s
                self.start_recording()
                response = {"type": "response", "status": "recording_ok"}
                self.socket_comm._send(json.dumps(response).encode())

            elif message['type'] == 'stop':
                self.log.info("got message to stop")
                self.stop_cams()
                self.remote_message_timer.setInterval(500)
                response = {"type": "response", "status": "stop_ok"}
                self.socket_comm._send(json.dumps(response).encode())

            elif message['type'] == 'status_poll':
                if self.basler_recorder.is_recording:
                    response = {"type": "status", "status": "recording"}
                elif self.basler_recorder.is_viewing:
                    response = {"type": "status", "status": "viewing"}
                elif self.is_remote_ctr:
                    response = {"type": "status", "status": "ready"}
                else:
                    response = {"type": "status", "status": "error"}
                self.socket_comm._send(json.dumps(response).encode())

            elif message['type'] == 'start_run':
                self.log.info("got message to start viewing")
                try:
                    if message["setting_file"]:
                        self.load_settings(message["setting_file"])
                except (FileNotFoundError, KeyError):
                    self.log.error("passed settings file not found")

                self.session_id = message["session_id"]
                self.SessionIDlineEdit.setText(self.session_id)

                try:
                    if message["frame_rate"]:
                        self.FrameRateSpin.setValue(message["frame_rate"])
                except KeyError:
                    pass
                self.remote_message_timer.setInterval(10000)  # increase the interval to 10s
                self.run_cams()
                response = {"type": "response", "status": "run_ok"}
                self.socket_comm._send(json.dumps(response).encode())

    def app_is_exiting(self):
        # check if recording is running stop if does.
        # close and realize cameras
        self.stop_cams()  # stop any grabbing still ongoing
        self.socket_comm.close_socket()
        if self.basler_recorder.cam_array:  # close cameras if those were open
            self.basler_recorder.cam_array.Close()
        pass

    def closeEvent(self, event):
        """
        Overloaded close event to make sure that all cameras are closed and all threads are stopped
        """
        self.log.info("Received window close event.")
        if self.basler_recorder.is_recording or self.is_remote_ctr:
            message_text = "Recording still running. Abort ?" if self.basler_recorder.is_recording \
                else "Remote mode is active. Abort ?"

            message = QMessageBox.information(self,
                                              "Really quit?",
                                              message_text,
                                              buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
            if message == QMessageBox.StandardButton.No:
                self.log.info('pressed no')
                event.ignore()
                return
            elif message == QMessageBox.StandardButton.Abort:
                event.ignore()
                return
            elif message == QMessageBox.StandardButton.Yes:
                self.log.info('Exiting')
        self.app_is_exiting()
        super(BASLER_GUI, self).closeEvent(event)


def start_gui():
    app = QApplication([])
    win = BASLER_GUI()
    win.show()
    app.exec()


if __name__ == '__main__':
    logging.info('Starting via __main__')
    sys.exit(start_gui())
