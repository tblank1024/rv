import json

fp =  open('datalog3.json',"r")

line = 0
for line in range(0,10):
    data = fp.readline()
    print(data)
