# ADBFS is fuse driver for Android filesystem working with ADB.

## Usage

Run `FUSE_PYTHON_API=0.2 ./adbfs.py <mountpoint>` and connect your device to computer.


## Requirements

#### On PC

 - Python 2
 - fuse
 - python-fuse
 - ADB in `$PATH`

#### On Android device

BusyBox: `sh`, `test`, `rmdir`, `mkdir`, `chmod`, `touch`, `rm`, `stat`, `mv`, `ls`.
If `ls -a` doesn\`t print one name per line change `USE_LS` to `True`.
