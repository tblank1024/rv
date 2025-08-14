Additional raspap configuration so that
1 - bridges both eth0 and wlan0 together
2 - connects this to the internet (pi5connect does the work)


pi5connect.sh - shell scipt that finds active internet interface
99-pi5connect - another shell script that gets run by the network manager when new devices are installed
              - this script must be executable and located in /etc/NetworkManager/dispatcher.d/99-pi5connect
