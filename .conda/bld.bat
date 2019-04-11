@echo off

rem # Install anything that didn't get conda installed via pip.
rem # We need to turn pip index back on because Anaconda turns
rem # it off for some reason. Just pip install -r requirements.txt
rem # doesn't seem to work, tensorflow-gpu, jsonpickle, networkx,
rem # all get installed twice if we do this. pip doesn't see the
rem # conda install of the packages.

set PIP_NO_INDEX=False
pip install opencv-python PySide2==5.12.0 imgaug cattrs==1.0.0rc qimage2ndarray==1.8