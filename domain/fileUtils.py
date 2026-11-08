import uos


def isFileExist(dir, fileName):
    """检查文件是否存在。用 uos.stat 替代 uos.listdir，避免遍历整个目录。"""
    try:
        uos.stat(dir.rstrip('/') + '/' + fileName)
        return True
    except OSError:
        return False

