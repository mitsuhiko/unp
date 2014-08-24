$ unp_

  unp is a command line tool that can unpack archives easily.  It
  mainly acts as a wrapper around other shell tools that you can
  find on various POSIX systems.

  It figures out how to invoke an unpacker to achieve the desired
  result.  In addition to that it will safely unpack files when an
  archive contains more than one top level item.  In those cases it
  will wrap the resulting file in a folder so that your working
  directory does not get messed up.

  All you have to do:

    $ unp myarchive.tar.gz

  To install you can use pipsi:

    $ pipsi install unp

  Supports the following archives:

  - 7zip Archives (*.7z)
  - AR Archives (*.a)
  - Apple Disk Image (*.dmg; *.sparseimage)
  - Bz2 Compressed Files (*.bz2)
  - Bz2 Compressed Tarballs (*.tar.bz2)
  - Gzip Compressed Files (*.gz)
  - Gzip Compressed Tarballs (*.tar.gz; *.tgz)
  - Uncompressed Tarballs (*.tar)
  - WinRAR Archives (*.rar)
  - Windows Cabinet Archive (*.cab)
  - XZ Compressed Files (*.xz)
  - XZ Compressed Tarballs (*.tar.xz)
  - Zip Archives (*.zip; *.egg; *.whl; *.jar)

  DMG is only supported on OS X where it invokes the hdiutil and
  copies out the contents.
