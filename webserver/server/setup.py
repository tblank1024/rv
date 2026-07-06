#!/usr/bin/env python

from setuptools import find_packages, setup

packages = [
    "uvicorn[standard]>=0.18.0,<1.0.0",  # Updated to newer version that works better with ARM64
    "gunicorn==20.1.0",
    "fastapi==0.89.1",
    "requests==2.27.1",
    "paho-mqtt==1.6.1",
    "tzlocal==5.0.1",
    "pyserial==3.5",  # Required for USB hub serial communication
    "python-kasa==0.10.2",  # Pinned exactly: kasa_patches.py targets this version's internals
    "pythonping==1.1.4",  # Required for internet connectivity testing
    "rvglue @ git+https://github.com/tblank1024/rv@e44d078819cc0e8d8746769a5cde18580204a454#subdirectory=rvglue",
    "docker>=6.0.0",  # Docker SDK for container management via unix socket
    #"aiofiles",
    #"aiohttp==3.8.3",
]

test_packages = [
    "mock==4.0.3",
    "pytest==6.2.1",
    "responses",
    "starlette",
    "mock",
]

linting_packages = [
    "pre-commit==2.9.3",
    "black==20.8b1",
    "flake8==3.8.4",
    "flake8-bugbear==20.1.4",
    "flake8-builtins==1.5.3",
    "flake8-comprehensions==3.2.3",
    "flake8-tidy-imports==4.2.1",
    "flake8-import-order==0.18.1",
]

setup(
    name="RVSecurity",
    version="1.0",
    description="A simple server for controlling an RV security system",
    author="Tom Blank",
    author_email="tblank@hotmail.com",
    install_requires=packages,
    packages=find_packages(),
    extras_require={
        "dev": test_packages + linting_packages,
    },
)
