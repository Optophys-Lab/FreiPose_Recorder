import logging
from pathlib import Path
import pyqtgraph as pg
from pyqtgraph import ImageView, RawImageWidget, GraphicsView, ImageItem, GraphicsWidget, PlotWidget
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QDialog, QSizePolicy, \
    QGridLayout, QToolBox, QDoubleSpinBox, QComboBox, QLabel, QSpinBox, QScrollArea
from PyQt6 import uic, QtCore, QtGui, QtWidgets
import numpy as np

import cv2
import time


class MultiCameraViewer(QWidget):
    """
    A widget that displays the images from multiple cameras.
    """
    def __init__(self, parent=None, num_cameras=4):
        super().__init__(parent)
        self.grid = None
        self._num_cameras = num_cameras
        self.cam_viewers = []
        self.parent = parent
        self.init_ui()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    @property
    def num_cameras(self):
        return self._num_cameras

    @num_cameras.setter
    def num_cameras(self, value):
        if 0 < value <= 9:
            self._num_cameras = value

        else:
            self._num_cameras = 9
        self.change_ui()

    @staticmethod
    def _get_grid_step(num_cameras):
        """Return number of columns for the camera grid layout."""
        if num_cameras == 1:
            return 1
        elif num_cameras <= 3:
            return num_cameras  # 1 row: 1x2 or 1x3
        elif num_cameras <= 4:
            return 2            # 2x2
        else:
            return 3            # 3x3

    def init_ui(self):
        # create a grid layout to hold the camera views
        self.grid = QGridLayout()
        self.grid.setSpacing(2)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.setLayout(self.grid)

        step = self._get_grid_step(self.num_cameras)
        for i in range(self.num_cameras):
            widget = ImageView_camera(self.parent)
            self.cam_viewers.append(widget)
            self.grid.addWidget(widget, i // step, i % step)

        for col in range(step):
            self.grid.setColumnStretch(col, 1)
        for row in range((self.num_cameras + step - 1) // step):
            self.grid.setRowStretch(row, 1)

        self.show()

    def change_ui(self):
        for view in self.cam_viewers:
            self.grid.removeWidget(view)
            view.deleteLater()
        self.cam_viewers = []

        step = self._get_grid_step(self.num_cameras)
        for i in range(self.num_cameras):
            widget = ImageView_camera(self.parent)
            self.cam_viewers.append(widget)
            self.grid.addWidget(widget, i // step, i % step)

        for col in range(step):
            self.grid.setColumnStretch(col, 1)
        for row in range((self.num_cameras + step - 1) // step):
            self.grid.setRowStretch(row, 1)


class ImageView_camera(QWidget):
    def __init__(self, parent=None):
        super(ImageView_camera, self).__init__(parent)

        # Create a layout for the image widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        #layout.setSpacing(0)
        # Create a RawImageWidget
        self.image_view = pg.RawImageWidget(scaled=True)
        self.image_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Add the RawImageWidget to the layout
        layout.addWidget(self.image_view)

        self.image_view.setImage(np.random.randint(0, 255, (128, 128), np.uint8))

    def updateView(self, image):
        """
        Set the image to be displayed in the RawImageWidget.
        image: numpy array containing the image data
        """
        # rotate img such that if it 2 dimentional it s transposed if 3 dimentional only first 2 axis are transposed
        try:
            if len(image.shape) == 3:
                self.image_view.setImage(image.transpose(1, 0, 2))
            else:
                self.image_view.setImage(image.T)
        except ValueError:
            print("Image could not be displayed. this format is not implemented")


class SingleCamViewer(QDialog):
    def __init__(self, parent, cam_name):
        super(SingleCamViewer, self).__init__(parent)
        self.path2file = Path(__file__)
        uic.loadUi(self.path2file.parent / 'GUI' / 'SingleCameraView.ui', self)
        self.setWindowTitle(f"CamViewer {cam_name}")
        self.log = logging.getLogger('CamViewer')
        self.log.setLevel(logging.DEBUG)
        self.parent = parent
        self.ConnectSignals()
        self.is_showing = True

    def ConnectSignals(self):
        self.STOPButton.clicked.connect(self.stop_viewing)

        self.AutoExposeButton.clicked.connect(self.auto_expose)
        self.AutoGainButton.clicked.connect(self.auto_gain)
        self.WhiteBalanceButton.clicked.connect(self.white_balance)
        self.FlipXButton.clicked.connect(self.flip_x)
        self.FlipYButton.clicked.connect(self.flip_y)

    def updateView(self, img):
        self.CamViewer.updateView(img)

    def stop_viewing(self):
        self.log.debug('Indicating to main to stop grabbing')
        self.is_showing = False
        self.parent.stop_cams()

    def auto_expose(self):
        self.parent.auto_expose()

    def auto_gain(self):
        self.parent.auto_gain()

    def white_balance(self):
        self.parent.white_balance()

    def flip_x(self):
        self.parent.flip_x()

    def flip_y(self):
        self.parent.flip_y()

    def app_is_exiting(self):
        """routine to call for stop if window is closed"""
        self.stop_viewing()

    def closeEvent(self, event):
        if self.is_showing:
            self.log.debug("Received window close event.")
            self.app_is_exiting()
            super(SingleCamViewer, self).closeEvent(event)
        else:
            self.log.debug("Closed by parent")

class SingleCameraSettings(QWidget):
    def __init__(self, parent=None, name='Camera'):
        super(SingleCameraSettings, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(4)

        font = QtGui.QFont()
        font.setPointSize(9)

        # Exposure Time
        self.ExposureTime_spin = QDoubleSpinBox(self)
        self.ExposureTime_spin.setSuffix(" us")
        self.ExposureTime_spin.setMinimum(0.5)
        self.ExposureTime_spin.setMaximum(1000000.0)
        self.ExposureTime_spin.setSingleStep(0.5)
        self.ExposureTime_spin.setValue(5.0)
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Exposure Time", self))
        hbox.addWidget(self.ExposureTime_spin)
        self.layout.addLayout(hbox)

        # Gain
        self.Gain_spin = QDoubleSpinBox(self)
        self.Gain_spin.setMinimum(0.0)
        self.Gain_spin.setMaximum(48.0)
        self.Gain_spin.setSingleStep(0.1)
        self.Gain_spin.setValue(0.0)
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Gain", self))
        hbox.addWidget(self.Gain_spin)
        self.layout.addLayout(hbox)

        # Color mode
        self.ColorMode_comboBox = QComboBox(self)
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Color mode", self))
        hbox.addWidget(self.ColorMode_comboBox)
        self.layout.addLayout(hbox)

        # Codec
        self.Codec_comboBox = QComboBox(self)
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Codec", self))
        hbox.addWidget(self.Codec_comboBox)
        self.layout.addLayout(hbox)

        # CRF
        self.CRF_spinBox = QSpinBox(self)
        self.CRF_spinBox.setMinimum(0)
        self.CRF_spinBox.setMaximum(51)
        self.CRF_spinBox.setValue(0)
        self.CRF_spinBox.setToolTip("0 = lossless, 51 = max compression (libx264)")
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("CRF (compression)", self))
        hbox.addWidget(self.CRF_spinBox)
        self.layout.addLayout(hbox)

        self.layout.addStretch()
        self.setLayout(self.layout)
        self.setFont(font)

    def set_colormodes(self, colormodes: list):
        self.ColorMode_comboBox.clear()
        self.ColorMode_comboBox.addItems(colormodes)

# create a class to dynamically create camera tabs according to number of cameras
class CameraSettingsTab(QWidget):
    def __init__(self, parent=None, nr_cams=4):
        super(CameraSettingsTab, self).__init__(parent)
        self.log = logging.getLogger('CameraTab')
        self.log.setLevel(logging.DEBUG)
        self.parent = parent
        self._num_cameras = nr_cams
        self.cam_settings = []
        self.gain_spin_list = []
        self.exposure_spin_list = []
        self.color_mode_list = []
        self.codec_list = []
        self.crf_list = []
        self._cam_setting_widgets = []  # SingleCameraSettings instances
        self._popup = None             # floating popup panel

        self.init_ui()
        self.ConnectSignals()

    @property
    def num_cameras(self):
        return self._num_cameras

    @num_cameras.setter
    def num_cameras(self, value):
        if 0 < value <= 9:
            self._num_cameras = value
        else:
            self._num_cameras = 9
        self.change_ui()

    def init_ui(self):
        from PyQt6.QtWidgets import QPushButton, QFrame
        font = QtGui.QFont()
        font.setPointSize(9)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(2)
        self.setLayout(self.layout)

        # Instruction label
        self._hint_label = QLabel(
            "📷 Select a camera below to set its individual\n"
            "exposure, gain, codec and compression (CRF).")
        hint_font = QtGui.QFont()
        hint_font.setPointSize(8)
        hint_font.setItalic(True)
        self._hint_label.setFont(hint_font)
        self._hint_label.setStyleSheet("color: #aaaaaa; padding: 2px 4px;")
        self._hint_label.setWordWrap(True)
        self.layout.addWidget(self._hint_label)

        self._buttons = []
        self._cam_setting_widgets = []

        for i in range(self.num_cameras):
            btn = QPushButton(f'Camera {i}')
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding-left: 6px; }"
                "QPushButton:checked { background-color: #3a5a8a; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._on_cam_button(idx))
            self.layout.addWidget(btn)
            self._buttons.append(btn)

            cam_sett = SingleCameraSettings(self)
            self._cam_setting_widgets.append(cam_sett)
            self.gain_spin_list.append(cam_sett.Gain_spin)
            self.exposure_spin_list.append(cam_sett.ExposureTime_spin)
            self.color_mode_list.append(cam_sett.ColorMode_comboBox)
            self.codec_list.append(cam_sett.Codec_comboBox)
            self.crf_list.append(cam_sett.CRF_spinBox)

        self.layout.addStretch()
        self.setFont(font)
        self.show()

        # Build the floating popup once
        self._build_popup()

    def _build_popup(self):
        """Create a floating frameless panel that shows settings for the selected camera."""
        from PyQt6.QtWidgets import QFrame, QStackedWidget
        from PyQt6.QtCore import Qt

        # Tool window: always on top, dropdowns can escape its bounds
        top = self.window()
        self._popup = QFrame(top, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self._popup.setFrameShape(QFrame.Shape.StyledPanel)
        self._popup.setFrameShadow(QFrame.Shadow.Raised)
        self._popup.setStyleSheet(
            "QFrame { background-color: #2b2b2b; border: 1px solid #555; border-radius: 4px; }"
        )
        self._popup.setFixedWidth(320)

        pop_layout = QVBoxLayout(self._popup)
        pop_layout.setContentsMargins(6, 6, 6, 6)
        pop_layout.setSpacing(4)

        self._popup_title = QLabel("Camera settings")
        title_font = QtGui.QFont()
        title_font.setBold(True)
        title_font.setPointSize(9)
        self._popup_title.setFont(title_font)
        pop_layout.addWidget(self._popup_title)

        self._stack = QStackedWidget()
        for cam_sett in self._cam_setting_widgets:
            scroll = QScrollArea()
            scroll.setWidget(cam_sett)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self._stack.addWidget(scroll)

        pop_layout.addWidget(self._stack)
        self._popup.setLayout(pop_layout)
        self._popup.hide()

    def _on_cam_button(self, idx):
        """Show popup next to the clicked button, or hide if same button clicked again."""
        btn = self._buttons[idx]

        # uncheck all other buttons
        for i, b in enumerate(self._buttons):
            if i != idx:
                b.setChecked(False)

        if not btn.isChecked():
            self._popup.hide()
            return

        # position popup to the left of this widget using global coords
        self._stack.setCurrentIndex(idx)
        self._popup_title.setText(f"⚙ {btn.text()} — Settings")
        self._popup.setFixedHeight(200)

        global_pos = btn.mapToGlobal(btn.rect().topLeft())
        popup_x = global_pos.x() - self._popup.width() - 5
        popup_y = global_pos.y()

        # Keep within screen bounds
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        if popup_x < screen.x():
            popup_x = global_pos.x() + btn.width() + 5
        if popup_y + self._popup.height() > screen.bottom():
            popup_y = screen.bottom() - self._popup.height()

        self._popup.move(popup_x, popup_y)
        self._popup.raise_()
        self._popup.show()

    def currentIndex(self):
        return self._stack.currentIndex() if self._stack else 0

    def setCurrentIndex(self, idx):
        if self._stack:
            self._stack.setCurrentIndex(idx)

    def itemText(self, idx):
        if 0 <= idx < len(self._buttons):
            return self._buttons[idx].text()
        return f'Camera {idx}'

    def setItemText(self, idx, text):
        if 0 <= idx < len(self._buttons):
            self._buttons[idx].setText(text)
            if self._stack and self._popup_title:
                if self._stack.currentIndex() == idx:
                    self._popup_title.setText(f"⚙ {text} — Settings")

    # Provide toolbox-compatible interface used by GUI_run.py
    @property
    def toolbox(self):
        return self

    def change_ui(self):
        # Clear existing buttons and widgets
        for btn in self._buttons:
            self.layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons = []
        self.gain_spin_list = []
        self.exposure_spin_list = []
        self.color_mode_list = []
        self.codec_list = []
        self.crf_list = []
        self._cam_setting_widgets = []

        if self._popup:
            self._popup.hide()

        from PyQt6.QtWidgets import QPushButton
        # Remove stretch
        item = self.layout.takeAt(self.layout.count() - 1)

        for i in range(self.num_cameras):
            btn = QPushButton(f'Camera {i}')
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                "QPushButton { text-align: left; padding-left: 6px; }"
                "QPushButton:checked { background-color: #3a5a8a; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._on_cam_button(idx))
            self.layout.addWidget(btn)
            self._buttons.append(btn)

            cam_sett = SingleCameraSettings(self)
            self._cam_setting_widgets.append(cam_sett)
            self.gain_spin_list.append(cam_sett.Gain_spin)
            self.exposure_spin_list.append(cam_sett.ExposureTime_spin)
            self.color_mode_list.append(cam_sett.ColorMode_comboBox)
            self.codec_list.append(cam_sett.Codec_comboBox)
            self.crf_list.append(cam_sett.CRF_spinBox)

        self.layout.addStretch()

        # Rebuild popup stack
        if self._popup:
            self._popup.deleteLater()
        self._build_popup()
        self.ConnectSignals()

    def parent_gain_exposure(self):
        self.parent.parent().set_gain_exposure()

    def parent_color_mode(self, color_mode: str):
        self.parent.parent().set_color_mode(color_mode)

    def parent_refresh_enc_table(self):
        try:
            self.parent.parent().refresh_enc_table()
        except AttributeError:
            pass

    def ConnectSignals(self):
        for spinbox in self.exposure_spin_list:
            spinbox.valueChanged.connect(self.parent_gain_exposure)
        for spinbox in self.gain_spin_list:
            spinbox.valueChanged.connect(self.parent_gain_exposure)
        for spinbox in self.color_mode_list:
            spinbox.currentTextChanged.connect(self.parent_color_mode)
        for combo in self.codec_list:
            combo.currentTextChanged.connect(self.parent_refresh_enc_table)
        for spinbox in self.crf_list:
            spinbox.valueChanged.connect(self.parent_refresh_enc_table)



class RemoteConnDialog(QtWidgets.QDialog):
    """
    Dialog to wait for remote connection, with abort button
    """
    def __init__(self, socket_comm, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.socket_comm = socket_comm
        self.setWindowTitle('Remote Connection')
        self.abort_button = QtWidgets.QPushButton("Abort")
        self.abort_button.clicked.connect(self.stopwaiting)
        self.abort_button.setIcon(QtGui.QIcon("GUI/icons/HandRaised.svg"))
        self.label = QtWidgets.QLabel("waiting for remote connection...")
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.abort_button)
        self.setLayout(layout)

        self.connectio_time = QtCore.QTimer()
        self.connectio_time.timeout.connect(self.check_connection)
        self.connectio_time.start(500)
        self.aborted = False

    def check_connection(self):
        """
        Check if connection is established, if so close dialog, called regularly by timer
        """
        if self.socket_comm.connected:
            self.close()

    def stopwaiting(self):
        """
        Stop waiting for connection, called by abort button
        """
        self.socket_comm.stop_waiting_for_connection()
        self.aborted = True
        self.close()

    def closeEvent(self, event):
        # If the user closes the dialog, kill the process
        self.stopwaiting()
        self.aborted = True
        event.accept()