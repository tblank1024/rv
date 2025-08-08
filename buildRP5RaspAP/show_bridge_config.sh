#!/bin/bash

echo "===== /etc/network/interfaces ====="
cat /etc/network/interfaces
echo

echo "===== /etc/dhcpcd.conf ====="
cat /etc/dhcpcd.conf
echo

if [ -f /etc/dnsmasq.conf ]; then
    echo "===== /etc/dnsmasq.conf ====="
    cat /etc/dnsmasq.conf
    echo
fi

if [ -f /etc/raspap/dnsmasq.conf ]; then
    echo "===== /etc/raspap/dnsmasq.conf ====="
    cat /etc/raspap/dnsmasq.conf
    echo
fi

if [ -f /etc/sysctl.conf ]; then
    echo "===== /etc/sysctl.conf ====="
    cat /etc/sysctl.conf
    echo
fi

if [ -f /etc/raspap/hostapd.ini ]; then
    echo "===== /etc/raspap/hostapd.ini ====="
    cat /etc/raspap/hostapd.ini
    echo
fi

echo "===== iptables NAT rules ====="
sudo iptables -t nat -L -n -v
echo

echo "===== iptables FORWARD rules ====="
sudo iptables -L FORWARD -n -v
echo

echo "===== ip addr show ====="
ip addr show
echo

echo "===== ip route ====="
ip route
echo
