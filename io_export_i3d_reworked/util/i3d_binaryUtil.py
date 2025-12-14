import subprocess
import os

def create_binary_from_exe(file, gamePath):
    app = 'i3dConverter.exe'
    #path handling
    abspath = os.path.dirname(__file__)
    app_path = os.path.join(abspath,app)
    print(app_path)
    if(not os.path.isfile(app_path)):
        return app_path + " not found"
    input_params = ['-in', file, "-out", file]
    if(gamePath):
        input_params += ["-gamePath", gamePath]

    # out, err = subprocess.Popen([app_path]+input_params, stdout=subprocess.PIPE).communicate(b"input data that is passed to subprocess' stdin")
    out, err = subprocess.Popen([app_path]+input_params, stdout=subprocess.PIPE).communicate()
    out = out.decode("utf-8")
    out = out.splitlines()
    # print (out)   
    return out[-1:]

if(__name__=='__main__'):
    create_binary_from_exe()