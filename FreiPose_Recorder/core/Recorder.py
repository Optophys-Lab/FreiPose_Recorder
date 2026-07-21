import logging, random
# import cv2
import time
import datetime
from pathlib import Path

from threading import Event, Thread
from queue import Queue, Full

from pypylon import genicam
from pypylon import pylon

from FreiPose_Recorder.utils.VideoWriterFast_gear import VideoWriterFast
from FreiPose_Recorder.utils.VideoWriterFast_gear import QueueOverflow

from FreiPose_Recorder.configs.camera_enums import CameraRegistry

from FreiPose_Recorder.configs.params import TIME_STAMP_STRING, TRIGGER_LINE_IN, MAX_FPS, CONVERT2


import os

NUM_CAMERAS = 2  # simulated cameras
# setup demo environment with emulated cameras
# os.environ["PYLON_CAMEMU"] = f"{NUM_CAMERAS}"
# remove when not needed anymore

CONVERSION_TARGET= {"RGB8":pylon.PixelType_RGB8packed,"Mono8":pylon.PixelType_Mono8}[CONVERT2]

def rel_close(v, max_v, thresh=5.0):
    v_scaled = v / max_v * 100.0
    if 100.0 - v_scaled < thresh:
        return True
    return False


class Recorder(object):
    """Class to handle recording of multiple cameras"""

    def __init__(self, verbosity=0, write_timestamps=False):
        self.write_timestamps = write_timestamps
        self.codec = 'divx'
        self.video_writer_list = []  # list of video writers
        self.is_recording = False
        self.is_viewing = False
        self.cams_context = None
        self.multi_record_thread = None
        self.multi_view_queue = None
        self.stop_event = None
        self.error_event = Event()  # event we set if an error occurs to signal the main thread
        self.current_cam = None
        self.current_cam_name = ''
        self.single_view_thread = None
        self.single_view_queue = None
        self.multi_view_thread = None
        self.cams_connected = False
        self.cam_array = []
        self._verbosity = verbosity
        self.save_path = ""
        # self._camera_info = get_camera_infos()
        self._camera_list = list()
        self._camera_names_list = list()

        # self._take_name = 'take'
        self._rid = 0
        self.fps = 10
        self.crf = 0 #to prevent crashes

        self._trigger = None
        self.grab_timeout = 10000  # in
        self.internal_queue_size = 100  # Size of the QUEUE for transfering images between threads

        self.log = logging.getLogger('BaslerRecorder')
        self.log.setLevel(logging.DEBUG)
        self.cameraregistry = CameraRegistry()

    @property
    def fps(self):
        return self._fps

    @fps.setter
    def fps(self, fps_new):
        if fps_new < 1:
            self._fps = 1
        elif fps_new > MAX_FPS:
            self._fps = MAX_FPS
        else:
            self._fps = fps_new

    def get_cam_info(self) -> list:
        self.scan_cams()
        sns = list()
        for idx, cam in enumerate(self.cam_array):
            sns.append(cam.DeviceInfo.GetSerialNumber())
        return sns

    def scan_cams(self):
        """ Searches for attached Basler cams and puts them into our list of cameras. """
        # reset cams
        self._camera_list, self._camera_names_list = list(), list()

        # Get the transport layer factory.
        tlFactory = pylon.TlFactory.GetInstance()

        devices = tlFactory.EnumerateDevices()
        if len(devices) == 0:
            self.log.info('No cameras present')
            self.cam_array = []
            return

        self.log.debug(f'Found {len(devices)} cameras')

        self.cam_array = pylon.InstantCameraArray(len(devices))

        for idx, cam in enumerate(self.cam_array):
            cam.Attach(tlFactory.CreateDevice(devices[idx]))
            sn = cam.DeviceInfo.GetSerialNumber()
            try:
                self.cameraregistry.get_camera(sn)
            except ValueError:
                self.log.warning(f'Connected camera {sn} not found in Enum')

    def connect_cams(self):
        self.cam_array.Open()
        for idx, cam in enumerate(self.cam_array):
            camera_serial = cam.DeviceInfo.GetSerialNumber()
            try:
                c = self.cameraregistry.get_camera(camera_serial)
                self.log.debug(
                    f"set context {c.get('context')} for camera {camera_serial}")
                cam.SetCameraContext(c.get('context'))
                cam.DeviceInfo.SetUserDefinedName(c.get('name'))
            except ValueError:
                r_int = random.randint(10, 256)
                cam.SetCameraContext(r_int)  # for unknown cameras set random context
                cam.DeviceInfo.SetUserDefinedName(f"cam{r_int}")
        self.cams_connected = True
        self.log.debug(f'Connected to {self.cam_array.GetSize()} cameras')

    def disconnect_cams(self):
        """ Disconnects all cameras"""
        if self.cam_array:
            self.cam_array.Close()
        self.cams_connected = False

    def _config_cams_continuous(self, cam):
        if not cam.IsOpen():
            cam.Open()

        # some things are to be set as attributes ...
        try:
            cam.AcquisitionFrameRate.Value = self.fps  # set fps to desired value
        except genicam.LogicalErrorException:
            cam.AcquisitionFrameRateAbs.Value = self.fps

        cam.AcquisitionFrameRateEnable.Value = True

        cam.MaxNumBuffer.SetValue(1024)  # how many buffers there are in total (empty and full)
        cam.OutputQueueSize.SetValue(
            512)  # maximal number of filled buffers (if another image is retrieved it replaces an old one and is called skipped)

        cam.AcquisitionMode.Value = 'Continuous'
        cam.TriggerMode.Value = 'Off'

    def _config_cams_hw_trigger(self, cam):
        if not cam.IsOpen():
            cam.Open()
        try:
            cam.AcquisitionFrameRate.Value = MAX_FPS  # here we go to max fps in order to not be limited
        except genicam.LogicalErrorException:
            cam.AcquisitionFrameRateAbs.Value = MAX_FPS  # maybe basler 2 cameras ?
        cam.AcquisitionFrameRateEnable.Value = True  # TODO should this be False ?
        # behavior wrt to these values is a bit strange to me. Important seems to be to use LastImages Strategy and make MaxNumBuffers larger than OutputQueueSize. Otherwise its not guaranteed to work
        cam.MaxNumBuffer.SetValue(1024)  # how many buffers there are in total (empty and full)
        cam.OutputQueueSize.SetValue(
            512)  # maximal number of filled buffers (if another image is retrieved it replaces an old one and is called skipped)

        cam.AcquisitionMode.Value = 'Continuous'

        #todo move this to camera config? only leave triggermode on ?
        cam.LineSelector.Value = TRIGGER_LINE_IN
        cam.LineMode.Value = "Input"
        #cam.LineSelector = TRIGGER_LINE_OUT
        #cam.LineMode = "Output"
        # cam.LineSource = pylon. # set to exposureactive
        cam.TriggerSelector.Value = "FrameStart"
        cam.TriggerSource.Value = TRIGGER_LINE_IN

        cam.TriggerMode.Value = "On"
        cam.TriggerActivation.Value = 'RisingEdge'

    @staticmethod
    def is_color_cam(cam):
        # get available formats
        available_formats = cam.PixelFormat.Symbolics

        # figure out if a color format is available
        if 'BGR8Packed' in available_formats or 'BGR8' in available_formats:
            return True
        return False

    def set_color_mode(self, cam_id: int, color_mode: str):
        """ Set values for the color mode of the camera from GUI"""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        try:
            cam.PixelFormat.SetValue(color_mode)
        except genicam.LogicalErrorException:
            self.log.info('color mode setting is not available for this camera')
        except genicam.AccessException:
            self.log.info('Cant set color mode while running ! ')
        if was_closed:
            cam.Close()

    def set_gain_exposure(self, cam_id: int, gain: float, exposure: float):
        """ Set values from GUI"""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        try:
            cam.Gain.SetValue(gain)
        except genicam.OutOfRangeException:
            self.log.warning(f'Value{gain:0.0f} is out of range of gain for this camera')
        except genicam.LogicalErrorException:
            self.log.info('gain setting is not available for this camera')

        try:
            cam.ExposureTime.SetValue(exposure)
        except genicam.OutOfRangeException:
            self.log.warning(f'Value{exposure:0.0f} is out of range of the exposure time')
        except genicam.LogicalErrorException:
            try:
                cam.ExposureTimeAbs.SetValue(exposure)
            except genicam.LogicalErrorException:
                self.log.info('Exposure time  setting is not available for this camera')
        if was_closed:
            cam.Close()

    @staticmethod
    def _coerce_to_inc(node, value):
        """Clamp value to [min, max] of a pylon integer node and round to its increment."""
        lo, hi = node.GetMin(), node.GetMax()
        value = int(max(lo, min(hi, value)))
        try:
            inc = node.GetInc()
        except genicam.GenericException:
            inc = 1
        if inc and inc > 1:
            # round down to nearest valid increment relative to the minimum
            value = lo + ((value - lo) // inc) * inc
        return int(value)

    def set_roi(self, cam_id: int, width: int, height: int, offset_x: int, offset_y: int):
        """Set the sensor readout ROI (field of view) for a single camera.

        Values are clamped to the camera limits and rounded to the node increment.
        Returns the actually-applied (width, height, offset_x, offset_y) so the GUI can
        read back what the camera accepted (it may snap to increments). Returns None if
        the ROI could not be set (e.g. camera is currently grabbing)."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        try:
            # Order matters: zero the offsets first so Width/Height can grow to the full
            # sensor, then set size, then set the offsets (OffsetX max depends on Width).
            try:
                cam.OffsetX.SetValue(0)
                cam.OffsetY.SetValue(0)
            except genicam.LogicalErrorException:
                pass  # camera without configurable offset

            cam.Width.SetValue(self._coerce_to_inc(cam.Width, width))
            cam.Height.SetValue(self._coerce_to_inc(cam.Height, height))

            try:
                cam.OffsetX.SetValue(self._coerce_to_inc(cam.OffsetX, offset_x))
                cam.OffsetY.SetValue(self._coerce_to_inc(cam.OffsetY, offset_y))
            except genicam.LogicalErrorException:
                pass

            applied = (cam.Width.GetValue(), cam.Height.GetValue(),
                       cam.OffsetX.GetValue(), cam.OffsetY.GetValue())
        except genicam.AccessException:
            self.log.warning('Cannot set ROI while camera is running. '
                             'Stop live view / recording first.')
            applied = None
        except genicam.OutOfRangeException as e:
            self.log.warning(f'ROI value out of range: {e}')
            applied = None
        except genicam.LogicalErrorException:
            self.log.info('ROI (Width/Height/Offset) is not available for this camera')
            applied = None
        finally:
            if was_closed:
                cam.Close()
        return applied

    def get_roi(self, cam_id: int) -> dict:
        """Return the current ROI of a camera as {width, height, offset_x, offset_y}."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        roi = {}
        try:
            roi = {'width': cam.Width.GetValue(), 'height': cam.Height.GetValue(),
                   'offset_x': cam.OffsetX.GetValue(), 'offset_y': cam.OffsetY.GetValue()}
        except genicam.LogicalErrorException:
            pass  # Not available for this camera
        if was_closed:
            cam.Close()
        return roi

    def get_roi_limits(self, cam_id: int) -> dict:
        """Return min/max/inc for each ROI node, to seed GUI spin boxes.

        Shape: {'width': (min, max, inc), 'height': ..., 'offset_x': ..., 'offset_y': ...}.
        Empty dict if the camera does not expose these nodes."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        limits = {}
        try:
            for key, node in (('width', cam.Width), ('height', cam.Height),
                              ('offset_x', cam.OffsetX), ('offset_y', cam.OffsetY)):
                try:
                    inc = node.GetInc()
                except genicam.GenericException:
                    inc = 1
                limits[key] = (node.GetMin(), node.GetMax(), inc)
        except genicam.LogicalErrorException:
            pass  # Not available for this camera
        if was_closed:
            cam.Close()
        return limits

    def load_pfs(self, cam_id: int, filepath) -> bool:
        """Load a pylon feature stream (.pfs) file onto a camera (ROI + all features)."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        ok = False
        try:
            pylon.FeaturePersistence.Load(str(filepath), cam.GetNodeMap(), True)
            ok = True
        except genicam.GenericException as e:
            self.log.warning(f'Could not load .pfs file for '
                             f'{cam.DeviceInfo.GetUserDefinedName()}: {e}')
        if was_closed:
            cam.Close()
        return ok

    def save_pfs(self, cam_id: int, filepath) -> bool:
        """Save the current camera state to a pylon feature stream (.pfs) file."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        ok = False
        try:
            pylon.FeaturePersistence.Save(str(filepath), cam.GetNodeMap())
            ok = True
        except genicam.GenericException as e:
            self.log.warning(f'Could not save .pfs file for '
                             f'{cam.DeviceInfo.GetUserDefinedName()}: {e}')
        if was_closed:
            cam.Close()
        return ok

    @staticmethod
    def _output_capable_lines(cam) -> list:
        """Names of digital lines that can be configured as Output (for the GUI combo)."""
        lines = []
        try:
            for ln in cam.LineSelector.Symbolics:
                cam.LineSelector.Value = ln
                try:
                    if 'Output' in cam.LineMode.Symbolics:
                        lines.append(ln)
                except genicam.GenericException:
                    continue
        except genicam.LogicalErrorException:
            pass  # camera without configurable lines
        return lines

    @staticmethod
    def _read_output_line(cam) -> str:
        """Name of the line currently in Output mode, or '' if none/not available."""
        try:
            for ln in cam.LineSelector.Symbolics:
                cam.LineSelector.Value = ln
                try:
                    if cam.LineMode.GetValue() == 'Output':
                        return ln
                except genicam.GenericException:
                    continue
        except genicam.LogicalErrorException:
            pass
        return ''

    def get_output_line_options(self, cam_id: int) -> list:
        """Available output-capable line names for a camera (for seeding the GUI combo)."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        lines = self._output_capable_lines(cam)
        if was_closed:
            cam.Close()
        return lines

    def get_output_line(self, cam_id: int) -> str:
        """The line currently configured as TTL output, or '' if none."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        line = self._read_output_line(cam)
        if was_closed:
            cam.Close()
        return line

    def set_output_line(self, cam_id: int, line: str):
        """Configure a TTL output line (LineMode=Output, LineSource=ExposureActive).

        Pass a falsy value or 'Off' to disable output (revert the current output line to
        Input, best-effort — some physical lines are output-only and cannot be changed)."""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        try:
            if line and line != 'Off':
                cam.LineSelector.Value = line
                cam.LineMode.Value = 'Output'
                cam.LineSource.Value = 'ExposureActive'
            else:
                current = self._read_output_line(cam)
                if current:
                    cam.LineSelector.Value = current
                    try:
                        cam.LineMode.Value = 'Input'
                    except genicam.GenericException:
                        self.log.info('Output line cannot be disabled (fixed output line)')
        except genicam.AccessException:
            self.log.warning('Cannot set output line while camera is running. '
                             'Stop live view / recording first.')
        except genicam.LogicalErrorException:
            self.log.info('Output line configuration is not available for this camera')
        except genicam.InvalidArgumentException:
            self.log.warning(f'Output line {line} / source ExposureActive not available')
        if was_closed:
            cam.Close()

    def run_white_balance(self, cam_id: int):
        """Set auto white balance for color cameras"""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        c = self.cameraregistry.get_camera(cam.DeviceInfo.GetSerialNumber())
        self.log.info(f"Setting white balance for {c.get('name')} "
                      f"{cam.GetDeviceInfo().GetSerialNumber()}")

        if not self.is_color_cam(cam):
            self.log.info(f"{c.get('name')} is not a color cam\n"
                          f"Skipping white balancing")
            return
        try:
            cam.AutoFunctionROISelector.SetValue('ROI1')
            cam.AutoFunctionROIUseWhiteBalance.SetValue(False)
            cam.AutoFunctionROISelector.SetValue('ROI2')
            cam.AutoFunctionROIUseWhiteBalance.SetValue(True)

            # define ROI to use
            cam.AutoFunctionROISelector.SetValue('ROI2')
            cam.AutoFunctionROIWidth.SetValue(cam.Width.GetValue())
            cam.AutoFunctionROIHeight.SetValue(cam.Height.GetValue())
            cam.AutoFunctionROIOffsetX.SetValue(0)
            cam.AutoFunctionROIOffsetY.SetValue(0)
        except genicam.LogicalErrorException:
            self.log.info('White balance setting is not available for this camera')
            return

        # get initial values
        if self._verbosity > 1:
            print('Initial balance ratio:', end='\t')
            cam.BalanceRatioSelector.SetValue('Red')
            print('Red= ', cam.BalanceRatio.GetValue(), end='\t')
            cam.BalanceRatioSelector.SetValue('Green')
            print('Green= ', cam.BalanceRatio.GetValue(), end='\t')
            cam.BalanceRatioSelector.SetValue('Blue')
            print('Blue= ', cam.BalanceRatio.GetValue())

        cam.BalanceWhiteAuto.SetValue('Once')

        i = 0
        while not cam.BalanceWhiteAuto.GetValue() == 'Off':
            if not cam.IsGrabbing():
                cam.GrabOne(5000)
                i += 1

                if i > 100:
                    self.log.error('Auto White balance was not successful')
                    break
            else:
                time.sleep(0.01)
                i = 0

        # get final values
        if self._verbosity > 1:
            print('Final balance ratio:', end='\t')
            cam.BalanceRatioSelector.SetValue('Red')
            print('Red= ', cam.BalanceRatio.GetValue(), end='\t')
            cam.BalanceRatioSelector.SetValue('Green')
            print('Green= ', cam.BalanceRatio.GetValue(), end='\t')
            cam.BalanceRatioSelector.SetValue('Blue')
            print('Blue= ', cam.BalanceRatio.GetValue())
        self.log.debug('Finished White balancing')
        if was_closed:
            cam.Close()

    def run_auto_exposure(self, cam_id: int) -> float:
        """ Adjust exposure time while keeping gain fixed. """
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()

        self.log.info(f"Setting auto exposure for {self.cameraregistry.get_camera(cam.GetDeviceInfo().GetSerialNumber()).get('name')}"
                      f"{cam.GetDeviceInfo().GetSerialNumber()}")
        try:
            cam.AutoFunctionROISelector.SetValue('ROI1')
            cam.AutoFunctionROIUseBrightness.SetValue(True)
            cam.AutoFunctionROISelector.SetValue('ROI2')
            cam.AutoFunctionROIUseBrightness.SetValue(False)
        except genicam.LogicalErrorException:
            self.log.info('Auto exposure setting is not available for this camera')
            return 0

        # define ROI to use
        cam.AutoFunctionROISelector.SetValue('ROI1')
        wOff = int(cam.Width.GetValue() / 4)
        hOff = int(cam.Height.GetValue() / 4)
        wSize = int(cam.Width.GetValue() / 2)
        hSize = int(cam.Height.GetValue() / 2)

        # Enforce size is a multiple of two (important because of bayer pattern)
        wSize = int(wSize / 2) * 2
        hSize = int(hSize / 2) * 2

        # set ROI
        cam.AutoFunctionROIWidth.SetValue(wSize)
        cam.AutoFunctionROIHeight.SetValue(hSize)
        cam.AutoFunctionROIOffsetX.SetValue(wOff)
        cam.AutoFunctionROIOffsetY.SetValue(hOff)

        # 0.3 means that the target brightness is 30 % of the maximum brightness
        # of the raw pixel value read out from the sensor.
        cam.AutoTargetBrightness.SetValue(0.2)

        # give auto some bounds
        cam.AutoExposureTimeLowerLimit.SetValue(cam.AutoExposureTimeLowerLimit.GetMin())
        cam.AutoExposureTimeUpperLimit.SetValue(cam.AutoExposureTimeUpperLimit.GetMax())

        # set gain to its reference value
        cam.ExposureAuto.SetValue('Once')

        i = 0
        while not cam.ExposureAuto.GetValue() == 'Off':
            if not cam.IsGrabbing():
                cam.GrabOne(5000)
                # instead of grabing just waiting if cama is already grabbing ?
                i += 1

                if i > 100:
                    self.log.error('Auto Exposure was not successful')
                    break
            else:
                time.sleep(0.01)
                i = 0
        exposure_time = self.get_cam_exposureTime(cam)
        self.log.debug(f'Final exposure after {i} images {exposure_time:0.1f} us in range '
                       f'{cam.AutoExposureTimeLowerLimit.GetMin()}-{cam.AutoExposureTimeUpperLimit.GetMax()}')

        # check if we should give warnings
        if rel_close(exposure_time, cam.AutoExposureTimeUpperLimit.GetMax()):
            self.log.warning('Final exposure value is very close to its maximum value:'
                             'Consider increasing gain, opening camera shutter wider or put more light.')

        if was_closed:
            cam.Close()
        return exposure_time

    def run_auto_gain(self, cam_id) -> float:
        # check if this can be run while visualization is running ?
        # do a check if grabbing is already grabbing ?
        # if so just wait until th flag gets reset ?
        """ Adjust gain while keeping exposure time fixed.
        returns resulting gain
        """
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        self.log.info(f"Setting auto gain for {self.cameraregistry.get_camera(cam.GetDeviceInfo().GetSerialNumber()).get('name','Unknown')} "
                      f"{cam.GetDeviceInfo().GetSerialNumber()}")

        # no clue whether those are needed / or work
        try:
            cam.AutoFunctionROISelector.SetValue('ROI1')
            cam.AutoFunctionROIUseBrightness.SetValue(True)
            cam.AutoFunctionROISelector.SetValue('ROI2')
            cam.AutoFunctionROIUseBrightness.SetValue(False)
        except genicam.LogicalErrorException:
            self.log.info('Auto gain setting is not available for this camera')
            return 0

        # define ROI to use
        cam.AutoFunctionROISelector.SetValue('ROI1')
        wOff = int(cam.Width.GetValue() / 4)
        hOff = int(cam.Height.GetValue() / 4)
        wSize = int(cam.Width.GetValue() / 2)
        hSize = int(cam.Height.GetValue() / 2)

        # Enforce size is a multiple of two (important because of bayer pattern)
        wSize = int(wSize / 2) * 2
        hSize = int(hSize / 2) * 2

        # set ROI
        cam.AutoFunctionROIWidth.SetValue(wSize)
        cam.AutoFunctionROIHeight.SetValue(hSize)
        cam.AutoFunctionROIOffsetX.SetValue(wOff)
        cam.AutoFunctionROIOffsetY.SetValue(hOff)

        # 0.3 means that the target brightness is 30 % of the maximum brightness
        # of the raw pixel value read out from the sensor.
        cam.AutoTargetBrightness.SetValue(0.2)

        # give auto some bounds
        cam.AutoGainLowerLimit.SetValue(cam.Gain.GetMin())
        cam.AutoGainUpperLimit.SetValue(cam.Gain.GetMax())

        # set exposure to its reference value
        # cam.ExposureTime.SetValue(0)
        # print('Initial gain', cam.Gain.GetValue())
        cam.GainAuto.SetValue('Once')
        i = 0
        while not cam.GainAuto.GetValue() == 'Off':
            if not cam.IsGrabbing():
                cam.GrabOne(5000)
                # instead of grabing just waiting if cama is already grabbing ?
                i += 1

                if i > 100:
                    self.log.error('Auto Gain was not successful')
                    break
            else:
                time.sleep(0.01)
                i = 0
        gain = self.get_cam_gain(cam)
        self.log.debug(f'Final gain after {i} images {cam.Gain.GetValue():0.1f} in range {cam.Gain.GetMin()}'
                       f'-{cam.Gain.GetMax()}')

        # check if we should give warnings
        if rel_close(gain, cam.Gain.GetMax()):
            self.log.warning('Final gain value is very close to its maximum value:'
                             ' Consider increasing exposure time, opening camera shutter wider or put more light.')

        if was_closed:
            cam.Close()
        return gain

    @staticmethod
    def get_cam_exposureTime(cam: pylon.InstantCamera) -> float:
        """Wrapper to ge exposure time.. in some cameras has different node"""
        try:
            return cam.ExposureTime.GetValue()
        except genicam.LogicalErrorException:
            return cam.ExposureTimeAbs.GetValue()

    @staticmethod
    def set_cam_exposureTime(cam: pylon.InstantCamera, exp_time: [float, None]):
        """Wrapper to set exposure time, in some cameras has different node"""
        if exp_time is None:
            return
        try:
            cam.ExposureTime.SetValue(exp_time)
        except genicam.OutOfRangeException:
            print(f'Value{exp_time:0.0f} is out of range of the exposure time')
            try:
                cam.ExposureTimeAbs.SetValue(exp_time)
            except genicam.LogicalErrorException:
                pass  # Not implemented for this camera

    @staticmethod
    def get_cam_gain(cam: pylon.InstantCamera) -> float:
        """Wrapper to get gain.. some cameras might not have the option"""
        try:
            return cam.Gain.GetValue()
        except genicam.LogicalErrorException:
            return 0

    @staticmethod
    def get_cam_limits(cam: pylon.InstantCamera) -> [tuple, tuple, list]:
        try:
            gain_limits = (cam.Gain.GetMin(), cam.Gain.GetMax())
            exp_limits = (cam.ExposureTime.GetMin(), cam.ExposureTime.GetMax())
            color_modes = cam.PixelFormat.Symbolics
            return gain_limits, exp_limits, color_modes
        except genicam.LogicalErrorException:
            return [], [], []

    @classmethod
    def set_cam_settings(cls, cam: pylon.InstantCamera, settings: dict):
        was_closed = False
        if not cam.IsOpen():
            was_closed = True
            cam.Open()

        roi = settings.get('roi')
        if roi:
            try:
                # zero offsets first so size can grow, then set size, then offsets
                cam.OffsetX.SetValue(0)
                cam.OffsetY.SetValue(0)
                cam.Width.SetValue(cls._coerce_to_inc(cam.Width, roi['width']))
                cam.Height.SetValue(cls._coerce_to_inc(cam.Height, roi['height']))
                cam.OffsetX.SetValue(cls._coerce_to_inc(cam.OffsetX, roi['offset_x']))
                cam.OffsetY.SetValue(cls._coerce_to_inc(cam.OffsetY, roi['offset_y']))
            except genicam.AccessException:
                print('Cannot set ROI while camera is running')
            except genicam.LogicalErrorException:
                pass  # ROI not available for this camera
            except (KeyError, genicam.OutOfRangeException):
                pass  # incomplete/out-of-range roi in settings

        try:
            gain = settings['gain']
            cam.Gain.SetValue(gain)
        except genicam.OutOfRangeException:
            print(f'Value{gain:0.0f} is out of range of gain for this camera')
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera
        except KeyError:
            pass

        cls.set_cam_exposureTime(cam, settings.get('exp_time', None))

        try:
            flipX = settings['flipX']
            cam.ReverseX.SetValue(flipX)
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera
        except KeyError:
            pass  # not in settings

        try:
            flipY = settings['flipY']
            cam.ReverseX.SetValue(flipY)
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera
        except KeyError:
            pass  # not in settings

        try:
            red_balance, green_balance, blue_balance = settings['color_balance']
            cam.BalanceRatioSelector.SetValue('Red')
            cam.BalanceRatio.SetValue(red_balance)
            cam.BalanceRatioSelector.SetValue('Green')
            cam.BalanceRatio.SetValue(green_balance)
            cam.BalanceRatioSelector.SetValue('Blue')
            cam.BalanceRatio.SetValue(blue_balance)
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera
        except KeyError:
            pass  # not in settings

        try:
            cam.PixelFormat.SetValue(settings['color_mode'])
        except genicam.LogicalErrorException: # Not implemented for this camera
            print('Could not set color mode')
        except genicam.InvalidArgumentException:
            print(f"Color mode {settings['color_mode']} not available for {cam.DeviceInfo.GetUserDefinedName()} camera")

        line_in = settings.get('lineIN', None)
        if line_in is None:
            line_in = TRIGGER_LINE_IN
        try:
            cam.LineSelector.Value = line_in
            cam.LineMode.Value = "Input"
            cam.TriggerSelector.Value = "FrameStart"
            cam.TriggerSource.Value = line_in
        except genicam.LogicalErrorException:
            print('Could not set trigger line')

        # 'output_line' (new) supersedes the legacy 'lineOUT' string; both are a line name.
        line_out = settings.get('output_line') or settings.get('lineOUT')
        if line_out and line_out != 'Off':
            try:
                cam.LineSelector.Value = line_out
                cam.LineMode.Value = "Output"
                # set to exposureactive
                cam.LineSource.Value = "ExposureActive"
            except genicam.LogicalErrorException:
                print('Could not set output line')
            except genicam.InvalidArgumentException:
                print(f'Output line {line_out} not available for '
                      f'{cam.DeviceInfo.GetUserDefinedName()} camera')

        if was_closed:
            cam.Close()

    @classmethod
    def get_cam_settings(cls, cam: pylon.InstantCamera) -> dict:
        """
        Get settings from a camera
        :param cam: camera object
        :return: dict with settings
        """
        was_closed = False
        if not cam.IsOpen():
            was_closed = True
            cam.Open()

        cam_settings = {}
        cam_name = cam.DeviceInfo.GetUserDefinedName()
        cam_settings[cam_name] = {}

        cam_settings[cam_name]['gain'] = cls.get_cam_gain(cam)
        cam_settings[cam_name]['exp_time'] = cls.get_cam_exposureTime(cam)

        try:
            cam_settings[cam_name]['flipX'] = cam.ReverseX.GetValue()
            cam_settings[cam_name]['flipY'] = cam.ReverseY.GetValue()
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera

        try:
            if cls.is_color_cam(cam):
                cam.BalanceRatioSelector.SetValue('Red')
                red_balance = cam.BalanceRatio.GetValue()
                cam.BalanceRatioSelector.SetValue('Green')
                green_balance = cam.BalanceRatio.GetValue()
                cam.BalanceRatioSelector.SetValue('Blue')
                blue_balance = cam.BalanceRatio.GetValue()
                cam_settings[cam_name]['color_balance'] = (red_balance, green_balance, blue_balance)
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera

        try:
            color_mode = cam.PixelFormat.GetValue()
            cam_settings[cam_name]['color_mode'] = color_mode
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera

        try:
            cam_settings[cam_name]['roi'] = {
                'width': cam.Width.GetValue(), 'height': cam.Height.GetValue(),
                'offset_x': cam.OffsetX.GetValue(), 'offset_y': cam.OffsetY.GetValue()}
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera

        # TTL output line: which line (if any) is currently configured as Output
        try:
            cam_settings[cam_name]['output_line'] = cls._read_output_line(cam)
        except genicam.LogicalErrorException:
            pass  # Not implemented for this camera

        if was_closed:
            cam.Close()
        return cam_settings

    def flip_image_x(self, cam_id: int):
        """ Flips the image  of a single camera in the X plane """
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        cam.ReverseX.Value = cam.ReverseX.GetValue()  # switch value
        if was_closed:
            cam.Close()

    def flip_image_y(self, cam_id: int):
        """ Flips the image of a single camera in the Y plane"""
        was_closed = False
        cam = self.cam_array[cam_id]
        if not cam.IsOpen():
            was_closed = True
            cam.Open()
        cam.ReverseY.Value = not cam.ReverseY.GetValue()  # switch value
        if was_closed:
            cam.Close()

    def run_single_cam_show(self, cam_id: int, stop_event: Event):
        """
        Show a single camera in a separate thread
        :param cam_id: camera id
        :param stop_event: Event to stop the thread
        """
        cam = self.cam_array[cam_id]
        self.single_view_queue = Queue(self.internal_queue_size) # QUEUE for transferring images between threads
        if not cam.IsOpen():
            cam.Open()
        try:
            cam_name = self.cameraregistry.get_camera(cam.GetDeviceInfo().GetSerialNumber()).get('name', 'unknown')
            self.log.info(f'Showing device {cam_name} '
                          f'with {self.fps} FPS')
            self.current_cam_name = cam_name
        except ValueError:
            self.log.info(f'Showing device {cam.GetDeviceInfo().GetSerialNumber()} with {self.fps} FPS')
            self.current_cam_name = cam.GetDeviceInfo().GetSerialNumber()

        self._config_cams_continuous(cam)
        self.current_cam = cam

        self.stop_event = stop_event
        self.error_event.clear()
        self.single_view_thread = Thread(target=self.single_cam_show)
        self.single_view_thread.start()

    def stop_single_cam_show(self):
        self.log.debug('Stopping single view, waiting for join')
        self.single_view_thread.join()  # wait for thread to finish
        self.log.debug('single view thread has joined')
        self.current_cam = None
        self.error_event.clear()
        self.stop_event = None
        self.single_view_thread = None

    def single_cam_show(self):
        """
        Get images from a single camera in a separate thread. Puts images to Q for visualization in GUI
        """
        cam = self.current_cam
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned  # most significant bit first #
        # LsbAligned other option

        cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

        while not self.stop_event.is_set():
            try:
                grabResult = cam.RetrieveResult(self.grab_timeout, pylon.TimeoutHandling_ThrowException)
                if grabResult.GrabSucceeded():
                    #is this line needed ?
                    targetImage = pylon.PylonImage.Create(pylon.PixelType_Mono8, grabResult.GetWidth(),
                                                          grabResult.GetHeight())

                    if converter.ImageHasDestinationFormat(grabResult):
                        # no conversion required
                        img = grabResult.GetArray()
                    else:
                        # convert to RGB
                        targetImage = converter.Convert(grabResult)
                        img = targetImage.GetArray()

                    self.single_view_queue.put_nowait(img)
                    grabResult.Release()
                else:
                    self.log.error(f"Occured: {grabResult.ErrorCode} {grabResult.ErrorDescription}")
            except genicam.TimeoutException as e:
                self.log.error(e)
                self.error_event.set()
                break
            except Full:
                self.log.error("Queue buffer overrun !")
                self.error_event.set()
                break
            except Exception as e:  # some other error occured
                self.log.error(e)
                self.error_event.set()
                break
        cam.StopGrabbing()

    def run_multi_cam_show(self, stop_event: Event, use_hw_trigger: bool = False):
        self.multi_view_queue = [Queue(self.internal_queue_size) for _ in range(self.cam_array.GetSize())]
        #self.multi_view_queue = [Queue(self.internal_queue_size)] * self.cam_array.GetSize()
        #second option does copies of ques and not references!

        if not self.cam_array.IsOpen():
            self.cam_array.Open()

        self.log.info(f'Showing {self.cam_array.GetSize()} cameras '
                      f'with {self.fps} FPS')

        self.cams_context = {} # to identify from which camera the images arrive

        for c_id, cam in enumerate(self.cam_array):
            if use_hw_trigger:
                self._config_cams_hw_trigger(cam)
            else:
                self._config_cams_continuous(cam)
            self.cams_context[cam.GetCameraContext()] = c_id
        #self.log.debug(self.cams_context)
        self.stop_event = stop_event
        self.error_event.clear()
        self.multi_view_thread = Thread(target=self.multi_cam_show)
        self.multi_view_thread.start()
        self.is_viewing = True

    def stop_multi_cam_show(self):
        if self.multi_view_thread:
            self.log.debug('Stopping multi-view, waiting for join')
            self.multi_view_thread.join()  # wait for thread to finish
            self.log.debug('multi-view thread joined')
        self.stop_event = None
        self.error_event.clear()
        self.multi_view_thread = None
        self.cams_context = None
        self.is_viewing = False

    def multi_cam_show(self):
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned  # most significant bit first #
        # will i need an array of converters ?

        self.cam_array.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        while not self.stop_event.is_set():
            try:
                grabResult = self.cam_array.RetrieveResult(self.grab_timeout, pylon.TimeoutHandling_ThrowException)
                context_id = self.cams_context[grabResult.GetCameraContext()]
                #self.log.debug(f"Cam {grabResult.GetCameraContext()} grabbed with context {context_id}")

                if grabResult.GrabSucceeded():
                    if converter.ImageHasDestinationFormat(grabResult):
                        # no conversion required
                        img = grabResult.GetArray()
                    else:
                        # convert to RGB
                        targetImage = converter.Convert(grabResult)
                        img = targetImage.GetArray()
                    #img = grabResult.GetArray()
                    # context_id = self.cams_context[grabResult.GetCameraContext()]
                    self.multi_view_queue[context_id].put_nowait(img)
                    grabResult.Release()
                else:
                    print("Error: ", grabResult.ErrorCode, grabResult.ErrorDescription)
            except genicam.TimeoutException as e:
                self.log.error(e)
                self.error_event.set()
                break
            except Full:
                self.log.error(f"Queue buffer for camera {context_id} overrun !")
                self.error_event.set()
                break
        self.cam_array.StopGrabbing()
        self.is_viewing = False

    def run_multi_cam_record(self, stop_event: Event, filename: str = 'testrec', use_hw_trigger: bool = False):
        was_closed = False
        self.multi_view_queue = [Queue(self.internal_queue_size) for _ in range(self.cam_array.GetSize())]

        # create path if not exists
        (Path(self.save_path)).mkdir(parents=True, exist_ok=True)

        if not self.cam_array.IsOpen():
            was_closed = True
            self.cam_array.Open()

        self.log.info(f'Recording {self.cam_array.GetSize()} cameras '
                      f'with {self.fps} FPS')

        self.cams_context = {}
        self.video_writer_list = list()
        try:
            timestamp = datetime.datetime.now().strftime(TIME_STAMP_STRING)
        except (TypeError, ValueError):
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        # to make sure all have the same timestamp
        for c_id, cam in enumerate(self.cam_array):
            if use_hw_trigger:
                self._config_cams_hw_trigger(cam)
            else:
                self._config_cams_continuous(cam)

            self.cams_context[cam.GetCameraContext()] = c_id
            video_name = f"{filename}_{timestamp}_" \
                         f"{cam.DeviceInfo.GetUserDefinedName()}.mp4"
            video_name = (Path(self.save_path) / video_name).as_posix()
            self.video_writer_list.append(VideoWriterFast(video_name,
                                                          fps=self.fps,
                                                          crf=self.crf,
                                                          codec=self.codec))  # was DIVX
        # self.log.debug(print(self.cams_context))
        self.stop_event = stop_event
        self.error_event.clear()
        self.multi_record_thread = Thread(target=self.multi_cam_record)
        self.multi_record_thread.start()
        self.is_recording = True

    def stop_multi_cam_record(self):
        self.log.debug('Stopping recording, waiting for join')
        self.multi_record_thread.join()
        self.log.debug('thread joined,waiting for writers to finish')
        for writer in self.video_writer_list:
            writer.wait_to_finish()
            writer.stop()
        self.log.debug('writers finished')
        self.is_recording = False
        self.error_event.clear()
        self.stop_event = None
        self.multi_record_thread = None
        self.cams_context = None

    def multi_cam_record(self):
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned  # most significant bit first #

        self.cam_array.StartGrabbing(pylon.GrabStrategy_LatestImages)
        # cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)  # here you dont have any buffer
        # cam.StartGrabbing(pylon.GrabStrategy_OneByOne)  # here you dont get warnings if something gets skipped

        while not self.stop_event.is_set():
            try:
                grabResult = self.cam_array.RetrieveResult(self.grab_timeout, pylon.TimeoutHandling_ThrowException)
                context_id = self.cams_context[grabResult.GetCameraContext()]
                #self.log.debug(f"Cam {grabResult.GetCameraContext()} grabbed with context {context_id}")

                if grabResult.GetNumberOfSkippedImages() > 0:
                    self.log.warning(f'Cam{context_id}: Missed {grabResult.GetNumberOfSkippedImages()} frames')
                if grabResult.GrabSucceeded():
                    if converter.ImageHasDestinationFormat(grabResult):
                        # no conversion required
                        img = grabResult.GetArray()
                    else:
                        # convert to RGB
                        targetImage = converter.Convert(grabResult)
                        img = targetImage.GetArray()
                    img_nr_camera = grabResult.ID
                    img_nr = grabResult.ImageNumber
                    img_ts = grabResult.TimeStamp
                    #if len(img.shape) == 2:
                    #    img = np.stack([img] * 3, -1)

                    # context_id = self.cams_context[grabResult.GetCameraContext()]
                    if self.write_timestamps:
                        self.video_writer_list[context_id].feed((img, img_nr_camera, img_nr, img_ts))
                    else:
                        self.video_writer_list[context_id].feed(img)
                    self.multi_view_queue[context_id].put_nowait(img)
                    # weirdly enough the recording does not mix up frames.. so maybe mixing up happens later ? in the queue
                    # or at the visualization ?
                    grabResult.Release()
                else:
                    self.log.error(grabResult.ErrorCode, grabResult.ErrorDescription)

            except genicam.TimeoutException as e:
                self.log.error(e)
                self.error_event.set()
                break
            except Full:
                self.log.error(f"Queue buffer{context_id}overrun !")
                self.error_event.set()
                break
            except QueueOverflow:
                self.error_event.set()
                self.log.error(f"Queue buffer{context_id}overrun !")
                break
        self.cam_array.StopGrabbing()
        self.is_recording = False


if __name__ == "__main__":
    baslerRec = Recorder()
    print(baslerRec.get_cam_info())
