from domain.LogUtils import log
import btree
import _thread

# First, we need to open a stream which holds a database
# This is usually a file, but can be in-memory database
# using uio.BytesIO, a raw flash partition, etc.
# Oftentimes, you want to create a database if it doesn't
# exist and open if it exists. Idiom below takes care of this.
# DO NOT open database with "a+b" access mode.
db=None
dbFile=None
# 多线程锁：Web线程与主线程会并发访问数据库，btree非线程安全，
# 所有读写操作必须通过dbLock串行化，否则可能导致数据库损坏（修复R2）
dbLock = _thread.allocate_lock()

def openDB():
    global db
    global dbFile
    if dbFile == None:
        try:
            dbFile = open("mydb", "r+b")
        except OSError:
            dbFile = open("mydb", "w+b")

    if db == None:
        # Now open a database itself
        db = btree.open(dbFile)

def closeDB():
    global db
    global dbFile
    if db != None:
        db.close()
        db = None

    if dbFile != None:
        dbFile.close()
        dbFile = None


# The keys you add will be sorted internally in the database

def testDB(prefix,count):
    global db
    log("+++start insert. prefix:{},count:{}".format(prefix,count))
    dbLock.acquire()
    try:
        openDB()

        for i in range(count):
            db[str(i)] = prefix+":"+str(i)

        closeDB()
        log("insert finish.")

        log("---start query.")
        openDB()
        for key in db:
            log("key:{},value:{}".format(key,db[key]))
        closeDB()
    finally:
        closeDB()
        dbLock.release()
    log("test db finish.")

def save(kv):
    if None == kv or len(kv) == 0:
        return

    global db
    dbLock.acquire()
    try:
        openDB()
        for k,v in kv.items():
            db[k] = v
        db.flush()
    finally:
        closeDB()
        dbLock.release()

def get(k):
    global db
    res = None
    dbLock.acquire()
    try:
        openDB()
        if k in db:
            res = db[k]
    finally:
        closeDB()
        dbLock.release()
    return res

def multiGet(keys):
    global db
    res = {}
    dbLock.acquire()
    try:
        openDB()
        for k in keys:
            if k in db:
                res[k] = db[k]
            else:
                res[k] = None
    finally:
        closeDB()
        dbLock.release()
    return res

def _to_str(val):
    if isinstance(val, bytes):
        return val.decode("utf-8")
    return val

def getAll(verbose=False):
    global db
    res = {}
    dbLock.acquire()
    try:
        openDB()
        for key in db:
            k = _to_str(key)
            v = _to_str(db[key])
            res[k] = v
            if verbose:
                log("key:{},value:{}".format(k, v))
    finally:
        closeDB()
        dbLock.release()
    return res

def set(k, v):
    global db
    dbLock.acquire()
    try:
        openDB()
        db[k] = v
        db.flush()
    finally:
        closeDB()
        dbLock.release()

def delete(k):
    global db
    dbLock.acquire()
    try:
        openDB()
        if k in db:
            del db[k]
            db.flush()
    finally:
        closeDB()
        dbLock.release()

def count():
    global db
    n = 0
    dbLock.acquire()
    try:
        openDB()
        n = sum(1 for _ in db)
    finally:
        closeDB()
        dbLock.release()
    return n

def contains(k):
    global db
    found = False
    dbLock.acquire()
    try:
        openDB()
        found = k in db
    finally:
        closeDB()
        dbLock.release()
    return found




# # Assume that any changes are cached in memory unless
# # explicitly flushed (or database closed). Flush database
# # at the end of each "transaction".
# db.flush()

# # Prints b'two'
# log(db[b"2"])

# # Iterate over sorted keys in the database, starting from b"2"
# # until the end of the database, returning only values.
# # Mind that arguments passed to values() method are *key* values.
# # Prints:
# #   b'two'
# #   b'three'
# for word in db.values(b"2"):
#     log(word)

# del db[b"2"]

# # No longer true, prints False
# log(b"2" in db)

# # Prints:
# #  b"1"
# #  b"3"
# for key in db:
#     log(key)

# db.close()

# # Don't forget to close the underlying stream!
# dbFile.close()
