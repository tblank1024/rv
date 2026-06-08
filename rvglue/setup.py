from setuptools import setup, find_packages

setup(
    name='rvglue',
    version='0.1.8',
    packages=["rvglue"],
    install_requires=[
        'paho-mqtt==1.6.1'
        ],
    url='https://github.com/tblank1024/rvglue',
    author='Tom Blank',
    author_email='tblank@ieee.org',
    description='Leverages Mosquitto MQTTclient and variable list for pub or sub',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)