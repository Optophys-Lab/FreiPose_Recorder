from setuptools import setup


setup(
    name="FreiPose_Recorder",
    version='0.10',
    description='Tool to record videos using (multiple) Basler Cameras synchornoiusly',
    url='https://github.com/Optophys-Lab/FreiPose_Recorder',
    author='Artur',
    python_requires=">=3.8,<3.10",
    install_requires=["numpy",
                      "pyqt6",
                      "pyqtgraph",
                      "pypylon == 1.9.0",
                      "vidgear[core]",
                      "pyserial",
                      "opencv-python"]
)
