import uos

def isFileExist(dir,fileName):
    
    files = uos.listdir(dir)
    if fileName in files:
        return True
    else:
        return False
