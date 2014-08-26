import os
import re
import sys
import tempfile
import mimetypes
import subprocess

import click


FILENAME = object()
OUTPUT_FOLDER = object()
unpackers = []


def register_unpacker(cls):
    unpackers.append(cls)
    return cls


def fnmatch(pattern, filename):
    filename = os.path.basename(os.path.normcase(filename))
    pattern = os.path.normcase(pattern)
    bits = '(%s)' % re.escape(pattern).replace('\\*', ')(.*?)(')
    return re.match('^%s$' % bits, filename)


def which(name):
    path = os.environ.get('PATH')
    if path:
        for p in path.split(os.pathsep):
            p = os.path.join(p, name)
            if os.access(p, os.X_OK):
                return p


def increment_string(string):
    m = re.match(r'(.*?)(\d+)$', string)
    if m is None:
        return string + '-2'
    return m.group(1) + str(int(m.group(2)) + 1)


def get_mimetype(filename):
    file_executable = which('file')
    if file_executable is not None:
        rv = subprocess.Popen(['file', '-b', '--mime-type', filename],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).communicate()[0].strip()
        if rv:
            return rv
    return mimetypes.guess_type(filename)[0]


def line_parser(format):
    pass


class StreamProcessor(object):

    def __init__(self, format, stream):
        self.regex = re.compile(format)
        self.stream = stream

    def process(self, p):
        stream = getattr(p, self.stream)
        while 1:
            line = stream.readline()
            if not line:
                break
            match = self.regex.search(line)
            if match is not None:
                yield match.group(1)


class UnpackerBase(object):
    id = None
    name = None
    executable = None
    filename_patterns = ()
    mimetypes = ()
    brew_package = None
    args = ()
    cwd = OUTPUT_FOLDER

    def __init__(self, filename, silent=False):
        self.filename = filename
        self.silent = silent
        self.assert_available()

    @classmethod
    def filename_matches(cls, filename):
        for pattern in cls.filename_patterns:
            if fnmatch(pattern, filename) is not None:
                return True

    @classmethod
    def mimetype_matches(cls, filename):
        mt = get_mimetype(filename)
        return mt in cls.mimetypes

    @classmethod
    def find_executable(cls):
        return which(cls.executable)

    @property
    def basename(self):
        for pattern in self.filename_patterns:
            match = fnmatch(pattern, self.filename)
            if match is None:
                continue
            pieces = match.groups()
            if pieces and pieces[-1].startswith('.'):
                return ''.join(pieces[:-1])
        return os.path.basename(self.filename).rsplit('.', 1)[0]

    def assert_available(self):
        if self.find_executable() is not None:
            return

        msgs = ['Cannot unpack "%s" because %s is not available.' % (
            click.format_filename(self.filename),
            self.executable,
        )]
        if sys.platform == 'darwin' and self.brew_package is not None:
            msgs.extend((
                'You can install the unpacker using brew:',
                '',
                '    $ brew install %s' % self.brew_package,
            ))

        raise click.UsageError('\n'.join(msgs))

    def get_args_and_cwd(self, dst):
        def convert_arg(arg):
            if arg is FILENAME:
                return self.filename
            if arg is OUTPUT_FOLDER:
                return dst
            return arg

        args = [self.find_executable()]
        for arg in self.args:
            args.append(convert_arg(arg))
        cwd = convert_arg(self.cwd)
        if cwd is None:
            cwd = '.'
        return args, cwd

    def report_file(self, filename):
        if not self.silent:
            click.echo(click.format_filename(filename), err=True)

    def real_unpack(self, dst, silent):
        raise NotImplementedError()

    def finish_unpacking(self, tmp_dir, dst):
        # Calculate the fallback destination
        basename = self.basename
        fallback_dst = os.path.join(os.path.abspath(dst), basename)
        while os.path.isdir(fallback_dst):
            fallback_dst = increment_string(fallback_dst)

        # Find how many unpacked files there are.  If there is more than
        # one, then we have to go to the fallback destination.  Same goes
        # if the intended destination already exists.
        contents = os.listdir(tmp_dir)
        if len(contents) == 1:
            the_one_file = contents[0]
            intended_dst = os.path.join(dst, the_one_file)
        else:
            intended_dst = None
        if intended_dst is None or os.path.exists(intended_dst):
            os.rename(tmp_dir, fallback_dst)
            return fallback_dst

        # Otherwise rename the first thing to the intended destination
        # and remove the temporary directory.
        os.rename(os.path.join(tmp_dir, the_one_file), intended_dst)
        os.rmdir(tmp_dir)
        return intended_dst

    def cleanup(self, dst):
        try:
            os.remove(dst)
        except Exception:
            pass

        try:
            import shutil
            shutil.rmtree(dst)
        except Exception:
            pass

    def unpack(self, dst):
        if not self.silent:
            click.secho('Unpacking "%s" with %s' % (
                self.filename,
                self.executable,
            ), fg='yellow')

        dst = os.path.abspath(dst)
        try:
            os.makedirs(dst)
        except OSError:
            pass

        tmp_dir = tempfile.mkdtemp(prefix='.' + self.basename, dir=dst)
        try:
            if self.real_unpack(tmp_dir) != 0:
                click.secho('Error: unpacking through %s failed.'
                            % self.executable, fg='red')
                sys.exit(2)

            final = self.finish_unpacking(tmp_dir, dst)
            if not self.silent:
                click.secho('Extracted to %s' % final, fg='green')
        finally:
            self.cleanup(tmp_dir)

    def dump_command(self, dst):
        args, cwd = self.get_args_and_cwd(dst)
        for idx, arg in enumerate(args):
            if arg.split() != [arg]:
                args[idx] = '"%s"' % \
                    arg.replace('\\', '\\\\').replace('"', '\\"')
        click.echo(' '.join(args))

    def __repr__(self):
        return '<Unpacker %r>' % (
            self.name,
        )


class Unpacker(UnpackerBase):
    stream_processor = None

    def real_unpack(self, dst):
        args, cwd = self.get_args_and_cwd(dst)
        extra = {}
        extra[self.stream_processor.stream] = subprocess.PIPE
        c = subprocess.Popen(args, cwd=cwd, **extra)
        for filename in self.stream_processor.process(c):
            self.report_file(filename)
        return c.wait()


class SingleInplaceUnpacker(UnpackerBase):

    def real_unpack(self, dst):
        args, cwd = self.get_args_and_cwd(dst)
        filename = os.path.join(dst, self.basename)
        with open(filename, 'wb') as f:
            rv = subprocess.Popen(args, cwd=cwd, stdout=f).wait()
        self.report_file(filename)
        return rv


tar_stream_processor = StreamProcessor(
    format=r'^x (.*?)$',
    stream='stderr',
)


@register_unpacker
class TarUnpacker(Unpacker):
    id = 'tar'
    name = 'Uncompressed Tarballs'
    filename_patterns = ['*.tar']
    executable = 'tar'
    args = ['xvf', FILENAME]
    stream_processor = tar_stream_processor
    mimetypes = ['application/x-tar']


@register_unpacker
class TarGzUnpacker(Unpacker):
    id = 'tgz'
    name = 'Gzip Compressed Tarballs'
    filename_patterns = ['*.tar.gz', '*.tgz']
    executable = 'tar'
    args = ['xvzf', FILENAME]
    stream_processor = tar_stream_processor


@register_unpacker
class TarBz2Unpacker(Unpacker):
    id = 'tbz2'
    name = 'Bz2 Compressed Tarballs'
    filename_patterns = ['*.tar.bz2']
    executable = 'tar'
    args = ['xvjf', FILENAME]
    stream_processor = tar_stream_processor


@register_unpacker
class TarXZUnpacker(UnpackerBase):
    id = 'txz'
    name = 'XZ Compressed Tarballs'
    filename_patterns = ['*.tar.xz']
    executable = 'unxz'
    args = ['-c', FILENAME]
    brew_package = 'xz'

    def real_unpack(self, dst):
        args, cwd = self.get_args_and_cwd(dst)
        tar = subprocess.Popen(['tar', 'x'], cwd=cwd,
                               stderr=subprocess.PIPE,
                               stdin=subprocess.PIPE)
        xz = subprocess.Popen(args, stdout=subprocess.PIPE, cwd=cwd)
        while 1:
            chunk = xz.stdout.read(131072)
            if not chunk:
                break
            tar.stdin.write(chunk)
        tar.stdin.close()
        xz.stdout.close()
        for proc in tar, xz:
            rv = proc.wait()
            if rv != 0:
                return rv
            return 0


@register_unpacker
class GzipUnpacker(SingleInplaceUnpacker):
    id = 'gz'
    name = 'Gzip Compressed Files'
    filename_patterns = ['*.gz']
    executable = 'gunzip'
    args = ['-c', FILENAME]
    mimetypes = ['application/x-gzip']


@register_unpacker
class Bz2Unpacker(SingleInplaceUnpacker):
    id = 'bz2'
    name = 'Bz2 Compressed Files'
    filename_patterns = ['*.bz2']
    executable = 'bunzip2'
    args = ['-c', FILENAME]
    mimetypes = ['application/x-bzip2']


@register_unpacker
class XZUnpacker(SingleInplaceUnpacker):
    id = 'xz'
    name = 'XZ Compressed Files'
    filename_patterns = ['*.xz']
    executable = 'unxz'
    args = ['-c', FILENAME]
    brew_package = 'xz'
    mimetypes = ['application/x-xz']


@register_unpacker
class ZipUnpacker(Unpacker):
    id = 'zip'
    name = 'Zip Archives'
    filename_patterns = ['*.zip', '*.egg', '*.whl', '*.jar']
    executable = 'unzip'
    args = [FILENAME]
    mimetypes = ['application/zip']
    stream_processor = StreamProcessor(
        format=r'^  inflating: (.*?)$',
        stream='stdout',
    )


@register_unpacker
class RarUnpacker(Unpacker):
    id = 'rar'
    name = 'WinRAR Archives'
    filename_patterns = ['*.rar']
    executable = 'unrar'
    args = ['-idp', '-y', 'x', FILENAME]
    mimetypes = ['application/zip']
    brew_package = 'unrar'
    stream_processor = StreamProcessor(
        format=r'^Extracting  (.*?)\s+OK\s*$',
        stream='stdout',
    )


@register_unpacker
class P7ZipUnpacker(Unpacker):
    id = '7z'
    name = '7zip Archives'
    filename_patterns = ['*.7z']
    executable = '7z'
    args = ['-bd', 'x', FILENAME]
    mimetypes = ['application/zip']
    brew_package = 'p7zip'
    stream_processor = StreamProcessor(
        format=r'^Extracting  (.*?)$',
        stream='stdout',
    )


@register_unpacker
class CabUnpacker(Unpacker):
    id = 'cab'
    name = 'Windows Cabinet Archive'
    filename_patterns = ['*.cab']
    executable = 'cabextract'
    args = ['-f', FILENAME]
    mimetypes = ['application/vnd.ms-cab-compressed']
    brew_package = 'cabextract'
    stream_processor = StreamProcessor(
        format=r'^  extracting (.*?)$',
        stream='stdout',
    )


@register_unpacker
class ArUnpacker(Unpacker):
    id = 'ar'
    name = 'AR Archives'
    filename_patterns = ['*.a']
    executable = 'ar'
    args = ['-vx', FILENAME]
    mimetypes = ['application/x-archive']
    stream_processor = StreamProcessor(
        format=r'^x - (.*?)$',
        stream='stdout',
    )


class DMGUnpacker(UnpackerBase):
    id = 'dmg'
    name = 'Apple Disk Image'
    filename_patterns = ['*.dmg', '*.sparseimage']
    executable = 'hdiutil'
    args = ['attach', '-nobrowse', FILENAME]

    def real_unpack(self, dst):
        mp = dst + '---mp'
        args, cwd = self.get_args_and_cwd(dst)
        args.append('-mountpoint')
        args.append(mp)

        with open('/dev/null', 'wb') as devnull:
            rv = subprocess.Popen(args, cwd=cwd,
                                  stdout=devnull,
                                  stderr=devnull).wait()
            if rv != 0:
                return rv

        p = subprocess.Popen(['cp', '-vpR', mp + '/', dst],
                             stdout=subprocess.PIPE)
        while 1:
            line = p.stdout.readline()
            if not line:
                break
            line = line.rstrip('\r\n').split(' -> ', 1)[1]
            if line.startswith(dst + '/'):
                line = line[len(dst) + 1:].strip()
                if line:
                    self.report_file(line)

        return p.wait()

    def cleanup(self, dst):
        with open('/dev/null', 'wb') as devnull:
            subprocess.Popen(['umount', dst + '---mp'],
                             stderr=devnull, stdout=devnull).wait()
        UnpackerBase.cleanup(self, dst)


if sys.platform == 'darwin':
    register_unpacker(DMGUnpacker)


def get_unpacker_class(filename):
    uifn = click.format_filename(filename)

    for unpacker_cls in unpackers:
        if unpacker_cls.filename_matches(filename):
            return unpacker_cls

    for unpacker_cls in unpackers:
        if unpacker_cls.mimetype_matches(filename):
            return unpacker_cls

    raise click.UsageError('Could not determine unpacker for "%s".' % uifn)


def list_unpackers(ctx, param, value):
    if not value:
        return

    for unpacker in sorted(unpackers, key=lambda x: x.name.lower()):
        if unpacker.find_executable() is None:
            continue
        click.echo('- %- 5s %s (%s)' % (
            unpacker.id,
            unpacker.name,
            '; '.join(unpacker.filename_patterns),
        ))

    ctx.exit()


def select_unpacker(ctx, param, value):
    if value is None:
        return value
    for unpacker in unpackers:
        if unpacker.id == value.lower():
            return unpacker
    raise click.BadParameter('Unknown unpacker.')


@click.command()
@click.argument('files', nargs=-1, type=click.Path(), required=True)
@click.option('-q', '--silent', is_flag=True,
              help='If this is enabled, nothing will be printed.')
@click.option('-o', '--output', type=click.Path(),
              help='Defines the output folder.  '
              'Defaults to the working directory.')
@click.option('--unpacker', 'forced_unpacker', callback=select_unpacker,
              metavar='UNPACKER',
              help='Overrides the automatically detected unpacker.  For '
              'a list of available unpackers see "--list-unpackers".')
@click.option('--list-unpackers', is_flag=True, expose_value=False,
              callback=list_unpackers,
              help='Lists all supported and available unpackers.')
@click.option('--dump-command', is_flag=True,
              help='Instead of executing the unpacker it prints out the '
              'command that would be executed.  This is useful for '
              'debugging broken archives usually.  Note that this command '
              'when executed directly might spam your current working '
              'directory!')
@click.version_option()
def cli(files, silent, output, dump_command, forced_unpacker):
    """unp is a super simple command line application that can unpack a lot
    of different archives.  No matter if you unpack a zip or tarball, the
    syntax for doing it is the same.  Unp will also automatically ensure
    that the unpacking goes into a single folder in case the archive does not
    contain a wrapper directory.  This guarantees that you never accidentally
    spam files into your current working directory.

    Behind the scenes unp will shell out to the most appropriate application
    based on filename or guessed mimetype.
    """
    if output is None:
        output = '.'

    unpackers = []

    for filename in files:
        filename = os.path.realpath(filename)
        if not os.path.isfile(filename):
            raise click.UsageError('Could not find file "%s".' %
                                   click.format_filename(filename))
        if forced_unpacker is not None:
            unpacker_cls = forced_unpacker
        else:
            unpacker_cls = get_unpacker_class(filename)
        unpackers.append(unpacker_cls(filename, silent=silent))

    for unpacker in unpackers:
        if dump_command:
            unpacker.dump_command(output)
        else:
            unpacker.unpack(output)
