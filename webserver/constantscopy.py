#phython
import sys
import json

def close_exit(fp_source, fp_dst, mode, msg):
    fp_source.close()
    fp_dst.close()
    if mode == 0:
        print(msg)
        sys.exit(0)
    else:
        print("Error opening files or xx.js file in incorrect format")
        print("Usage: python constantcopy.py <source> <destination>")
        print("Example: python constantcopy.py xx1.js xx2.json")
        print("Legal file format:")
        print('  export const IPADDR= "192.168.2.177"');
        print('  export const PORT= "8000";')
        print("  ...")
        print('>>>', msg)
        sys.exit(1)
    


def openfiles():
#open files and return file pointers
    try:
        fp_source = open(sys.argv[1], "rt")
        fp_dst = open(sys.argv[2], "wt")
    except:
        close_exit(fp_source, fp_dst, 1, "Exiting - file problem")
    return (fp_source, fp_dst)

def ParseInput(fp_source):
#parse input file and return dictionary
    constants = {}
    try:
        for line in fp_source:
            if line.startswith("export const "):
                line = line.replace("export const ", "")
                line = line.replace('"', '')
                part = line.rpartition("=") 
                if part[1] == "":
                    close_exit(fp_source, fp_dst, 1, "Exiting - no '=' found")
                constants[part[0].strip()] = part[2].strip().replace(';', "")
    except:
        close_exit(fp_source, fp_dst, 1, "Exiting - malformed input file")
    return constants

if __name__ == "__main__":
    (fp_source, fp_dst) = openfiles()
    constants = ParseInput(fp_source)
    outjson = json.dumps(constants, indent = 4)
    fp_dst.write(outjson)
    print(outjson)
    close_exit(fp_source, fp_dst, 0, 'OK - Done')
