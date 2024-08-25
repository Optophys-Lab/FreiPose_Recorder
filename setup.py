from setuptools import setup, find_packages


setup(
    name="FreiPose_Recorder",
    version='1.0.0',
    description='Tool to record videos using (multiple) Basler Cameras synchornoiusly',
    url='https://github.com/Optophys-Lab/FreiPose_Recorder',
    author='Artur',
    python_requires=">=3.8,<3.11",
    packages=find_packages(exclude=["circuitpython.*", "circuitpython"]),
    install_requires=["numpy",
                      "pyqt6 == 6.4.2",
                      "pyqtgraph",
                      "pypylon == 3.0.1",
                      "vidgear[core]",
                      "pyserial",
                      "opencv-python"],
    extras_require={
            "DLC_live": ["deeplabcut-live"]}
)
