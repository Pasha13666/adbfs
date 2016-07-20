# coding=utf-8
from fuse import Fuse, Stat, Direntry, StatVfs
from os import mkdir
from os.path import exists
from pyadb import ADB
from errno import ENOENT
import stat


def run():
    if exists('/tmp/adbfs-cache/saved.files.dat') and exists('/tmp/adbfs-cache/saved.info.dat'):
        with open('/tmp/adbfs-cache/saved.files.dat', 'r') as f:
            for i in f:
                if len(i) > 0 and ';' in i:
                    i = i.split(';', 1)
                    FILES_CACHE[i[0]] = i[1].strip()

        with open('/tmp/adbfs-cache/saved.info.dat', 'r') as f:
            for i in f:
                if len(i) > 0 and ';' in i:
                    i = i.split(';', 2)
                    INFO_CACHE[i[0]] = (int(i[1]), int(i[2]))

    elif not exists('/tmp/adbfs-cache'):
        mkdir('/tmp/adbfs-cache')

    fs = ADBFS(version="%prog 1.0")
    fs.connect()
    fs.parse(errex=1)
    fs.main()

    with open('/tmp/adbfs-cache/saved.files.dat', 'w') as f:
        for i in FILES_CACHE.items():
            f.write('%s;%s\n' % i)

    with open('/tmp/adbfs-cache/saved.info.dat', 'w') as f:
        for k, v in INFO_CACHE.items():
            f.write('%s;%s;%s\n' % (k, v[0], v[1]))

FILES_CACHE = {}
INFO_CACHE = {}


def non_cached(name):
    if name in FILES_CACHE:
        del FILES_CACHE[name]
    if name in INFO_CACHE:
        del INFO_CACHE[name]


def cached(name, mk):
    if name not in FILES_CACHE:
        i = len(FILES_CACHE)
        FILES_CACHE[name] = i
        mk("/tmp/adbfs-cache/%s" % i)
    return "/tmp/adbfs-cache/%s" % FILES_CACHE[name]


def lru_cache(fn):
    def wrapper(self, path):
        if path in INFO_CACHE:
            st = INFO_CACHE[path]
            f = Stat()
            f.st_nlink = 1
            f.st_mode = st[0]
            f.st_size = st[1]
            return f
        else:
            f = fn(self, path)
            if isinstance(f, Stat):
                INFO_CACHE[path] = (f.st_mode, f.st_size)
            return f
    return wrapper


class ADBFS(Fuse):
    opened = {}

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        self.adb = ADB('adb')

    def connect(self):
        print 'Connect device to computer...'
        self.adb.wait_for_device()
        err = self.adb.get_error()
        if err:
            print 'ADB error:', err.strip()
            exit(5)

        print 'Driver enabled!'

    def _sh(self, cmd):
        try:
            return self.adb.shell_command("'%s'" % cmd) or ""
        except Exception as e:
            print 'Command ', cmd, 'failed:', self.adb.get_error()
            raise e

    # ---- DIRECTORIES ----
    def readdir(self, path, offset):
        if self._sh('test -d "%s"&&echo true' % path).strip() == 'true':
            if path[:-1] != '/':
                path += '/'
            dd = self._sh('ls -a "%s"' % path).splitlines()
            for i in dd:
                yield Direntry(i)

    def rmdir(self, path):
        self.adb.shell_command('rmdir "%s"' % path)
        non_cached(path)

    def mkdir(self, path, mode):
        self.adb.shell_command('mkdir "%s"' % path)
        self.adb.shell_command('chmod %s "%s"' % (oct(mode), path))
        non_cached(path)

    # ---- FILES ----
    def create(self, path, mode):
        self.adb.shell_command('echo "" >"%s"' % path)
        self.adb.shell_command('chmod %s "%s"' % (oct(mode), path))
        non_cached(path)

    def mknod(self, path, mode, dev):
        self.adb.shell_command('touch "%s"' % path)
        self.adb.shell_command('chmod %s "%s"' % (oct(mode), path))
        non_cached(path)

    def open(self, path, flags):
        if self._sh('test -e "%s"&&echo true' % path).strip() != 'true':
            return -ENOENT

        if path in self.opened:
            self.opened[path][1] += 1
        else:
            rfn = cached(path, lambda x: self.adb.get_remote_file(path, x))
            self.opened[path] = [open(rfn, 'rb+'), 1]

    def release(self, path, flags):
        f = self.opened[path]
        f[1] -= 1
        if f[1] == 0:
            f[0].close()
            del self.opened[path]

    def read(self, path, size, offset):
        f = self.opened[path][0]
        f.seek(0, 2)
        slen = f.tell()
        if offset < slen:
            if offset + size > slen:
                size = slen - offset

            f.seek(offset)
            return f.read(size)
        return ''

    def write(self, path, data, offset):
        f = self.opened[path][0]
        f.seek(0, 2)
        slen = f.tell()
        if offset < slen:

            f.seek(offset)
            l = f.write(data)

            rfn = cached(path, lambda x: self.adb.get_remote_file(path, x))
            self.adb.push_local_file(rfn, path)
            return l
        return 0

    def fsync(self, path):
        if path in FILES_CACHE:
            rfn = FILES_CACHE[path]
            self.adb.push_local_file(rfn, path)
            non_cached(path)

    def unlink(self, path):
        self.adb.shell_command('rm "%s"' % path)
        non_cached(path)

    # ---- OTHER ----
    @lru_cache
    def getattr(self, path):
        st = Stat()
        st.st_nlink = 1
        if self._sh('test -e "%s"&&echo true' % path).strip() != 'true':
            return -ENOENT

        elif self._sh('test -h "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFLNK

        elif self._sh('test -d "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFDIR

        elif self._sh('test -f "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFREG

        elif self._sh('test -c "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFCHR

        elif self._sh('test -b "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFBLK

        elif self._sh('test -p "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFIFO

        elif self._sh('test -s "%s"&&echo true' % path).strip() == 'true':
            st.st_mode = stat.S_IFSOCK

        else:
            st.st_mode = 0

        st.st_mode |= int(self._sh('stat -c%%a "%s"' % path) or '0', 8)
        st.st_size = int(self._sh('stat -c%%s "%s"' % path) or '0')
        print "file:", path, "size: ", st.st_size, "mode:", oct(st.st_mode)

        return st

    def chmod(self, path, mode):
        self._sh('chmod %s "%s"' % (oct(mode), path))
        non_cached(path)

    def chown(self, oid, gid, path):
        pass # TODO: chown

    def rename(self, path, new):
        self._shd('mv "%s" "%s"' % (path, new))
        non_cached(path)
        non_cached(new)

    def statfs(self):
        st = StatVfs()
        st.f_bsize = 1024
        st.f_frsize = 1024
        st.f_bfree = 0
        st.f_bavail = 0
        st.f_files = 2
        st.f_blocks = 4
        st.f_ffree = 0
        st.f_favail = 0
        st.f_namelen = 255
        return st

if __name__ == '__main__':
    run()
