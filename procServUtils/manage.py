
import logging
_log = logging.getLogger(__name__)

import sys, os, errno
import pwd, grp
import subprocess as SP

from .conf import getconf, getrundir, getgendir
from .generator import run as genrun

try:
    import shlex
except ImportError:
    from . import shlex

_levels = [
    logging.WARN,
    logging.INFO,
    logging.DEBUG,
]

# -----------------------------------------------------------------------------
# Default parameters
# -----------------------------------------------------------------------------
systemctl       = '/bin/systemctl'
conserver_conf  = '/etc/conserver/procs.cf'
systemd_dir     = '/etc/systemd/system'

def status(conf, args, fp=None):
    rundir=getrundir(user=args.user)
    fp = fp or sys.stdout

    for name in conf.sections():
        if not conf.getboolean(name, 'instance'):
            continue
        fp.write('%s '%name)

        pid = None
        ports = []
        infoname = os.path.join(rundir, 'ioc@%s'%name, 'info')
        try:
            with open(infoname) as F:
                _log.debug('Read %s', F.name)
                for line in map(str.strip, F):
                    if line.startswith('pid:'):
                        pid = int(line[4:])
                    elif line.startswith('tcp:'):
                        ports.append(line[4:])
                    elif line.startswith('unix:'):
                        ports.append(line[5:])
        except Exception as e:
            _log.debug('No info file %s', infoname)
            if getattr(e, 'errno',0)!=errno.ENOENT:
                _log.exception('oops')

        if pid is not None:
            _log.debug('Test PID %s', pid)
            # Can we say if the process is actually running?
            running = True
            try:
                os.kill(pid, 0)
                _log.debug('PID exists')
            except OSError as e:
                if e.errno==errno.ESRCH:
                    running = False
                    _log.debug('PID does not exist')
                elif e.errno==errno.EPERM:
                    _log.debug("Can't say if PID exists or not")
                else:
                    _log.exception("Testing PID %s", pid)
            fp.write('Running' if running else 'Dead')

            if running:
                fp.write('\t'+' '.join(ports))
        else:
            fp.write('Stopped')

        fp.write('\n')

def syslist(conf, args):
    SP.check_call([systemctl,
                    '--user' if args.user else '--system',
                    'list-units', 'ioc@*'])

def addproc(conf, args):
    import socket
    from configparser import ConfigParser
    site_conf = ConfigParser()

    outdir = getgendir(user=args.user)
    cfile = os.path.join(outdir, '%s.conf'%args.name)

    if os.path.exists(cfile) and not args.force:
        _log.error("Instance already exists @ %s", cfile)
        _log.error("Use -f (--force) to overwrite")
        sys.exit(1)

    #if conf.has_section(args.name):
    #    _log.error("Instance already exists")
    #    sys.exit(1)

    try:
        os.makedirs(outdir)
    except OSError as e:
        if e.errno!=errno.EEXIST:
            _log.exception('Creating directory "%s"', outdir)
            raise

    _log.info("Writing: %s", cfile)

    # Try reading in the site default file
    if args.site is not None:
        try:
            conf_path = os.path.join(os.getcwd(), 'conf')
            conf_path = os.path.join(conf_path, args.site+'.conf')

            site_conf = ConfigParser()
            site_conf.read(conf_path)

            # Populate expected variables
            args.username = site_conf[args.site]['user']
            args.group = site_conf[args.site]['group']
            if 'host' not in site_conf[args.site].keys():
                args.host = socket.gethostname()
            else:
                args.host = site_conf[args.site]['host']
        except FileNotFoundError:
            _log.exception('No available site config file for {}'.format(args.site))
        except KeyError as e:
            _log.exception('Expected key not found')

    # Set command
    if args.command is not None:
        args.command[0] = os.path.abspath(os.path.join(args.chdir, args.command[0]))

    # Set chdir
    if site_conf[args.site]['base_dir'] is not None:
        # Site specific options
        if args.site == 'ess-e3':
            args.chdir = os.path.join(site_conf[args.site]['base_dir'], args.name)
            args.command = 'st.{}.cmd'.format(args.name)
            port_dir = 'ioc@{}'.format(args.name)
            args.port = 'unix:{}'.format(os.path.join(
                getrundir(), port_dir, 'control'))
            try:
                os.mkdir(os.path.join(getrundir(), port_dir))
            except OSError:
                pass
            try:

                uid = pwd.getpwnam(args.username).pw_uid
                gid = grp.getgrnam(args.group).gr_gid
                os.chown(os.path.join(getrundir(), port_dir), uid, gid)
            except OSError:
                pass

    else:
        args.chdir = os.path.abspath(os.path.join(os.getcwd(), args.chdir))
        args.command = ' '.join(map(shlex.quote, args.command))

    opts = {
        'name':args.name,
        'command':args.command,
        'chdir':args.chdir,
    }

    with open(cfile+'.tmp', 'w') as F:
        F.write("""
[%(name)s]
command = %(command)s
chdir = %(chdir)s
"""%opts)

        if args.username: F.write("user = %s\n"%args.username)
        if args.group: F.write("group = %s\n"%args.group)
        if args.host: F.write("host = %s\n"%args.host)
        if args.site: F.write("site = %s\n"%args.site)
        if args.port: F.write("port = %s\n"%args.port)

    os.rename(cfile+'.tmp', cfile)

    # Check if should to re-write Conserver coniguration file
    if args.writeconf:
        _log.info('Trying to update conserver configuration...')
        # Updating conserver config file due the previous procedures
        conf = getconf(user=args.user)
        # Adding writeconf default parameters
        #   - where to save configuration file of conserver;
        #   - if should automatically reload the service;
        args.out    = conserver_conf
        writeprocs(conf, args)

    # Check if should to re-write System-D service files
    if args.writesysd:
        _log.info('Trying to update System-D service files...')
        genrun(outdir=args.outsysd, user=args.user)

    # Daemon reloading
    _log.info('Trigger systemd reload')
    SP.check_call([systemctl,
                   '--user' if args.user else '--system',
                   'daemon-reload'], shell=False)

    # procServ restarting
    if args.autostart:
        _log.info("Starting the service: ioc@%s.service" % args.name)
        SP.check_call([systemctl,
                       '--user' if args.user else '--system',
                       'start', 'ioc@%s.service' % args.name])
    else:
        sys.stdout.write("# systemctl start ioc@%s.service\n"%args.name)

def delproc(conf, args):
    from .conf import getconffiles, ConfigParser
    for cfile in getconffiles(user=args.user):
        _log.debug('Process %s', cfile)

        with open(cfile) as F:
            C = ConfigParser({'instance':'1'})
            C.readfp(F)

        if not C.has_section(args.name):
            continue
        if not C.getboolean(args.name, 'instance'):
            continue

        if not args.force and sys.stdin.isatty():
            while True:
                sys.stdout.write("Remove section '%s' from %s ? [yN]"%(args.name, cfile))
                sys.stdout.flush()
                L = sys.stdin.readline().strip().upper()
                if L=='Y':
                    break
                elif L in ('N',''):
                    sys.exit(1)
                else:
                    sys.stdout.write('\n')

        if len(C.defaults())==1 and len(C.sections())==1:
            _log.info('Removing empty file %s', cfile)
            os.remove(cfile)
        else:
            C.remove_section(args.name)
            C.remove_option('DEFAULT', 'instance')
            _log.info("Removing section '%s' from file %s", args.name, cfile)
            with open(cfile+'.tmp', 'w') as F:
                C.write(F)
            os.rename(cfile+'.tmp', cfile)

    # Check if should to re-write Conserver coniguration file
    if args.writeconf:
        _log.info('Trying to update Conserver configuration file...')
        # Updating conserver config file due the previous procedures
        conf = getconf(user=args.user)
        # Adding writeconf default parameters
        #   - where to save configuration file of conserver;
        #   - if should automatically reload the service;
        args.out    = conserver_conf
        writeprocs(conf, args)

    # Check if should to re-write System-D service files
    if args.writesysd:
        _log.info('Trying to update System-D service files...')
        genrun(outdir=args.outsysd, user=args.user)

    # Daemon reloading
    _log.info('Trigger systemd reload')
    SP.check_call([systemctl,
                   '--user' if args.user else '--system',
                   'daemon-reload'], shell=False)

    sys.stdout.write("# systemctl stop ioc@%s.service\n"%args.name)

def writeprocs(conf, args):
    opts = {
        'rundir':getrundir(user=args.user),
    }
    _log.debug('Writing %s', args.out)
    with open(args.out+'.tmp', 'w') as F:
        for name in conf.sections():
            opts['name'] = name
            port_string = conf.get(name, 'port')
            if 'tcp:' in port_string:
                opts['tcp_port'] = port_string.split(':')[1]
            if port_string.isdigit():
                opts['tcp_port'] = port_string

            F.write("""
console %(name)s {
    master localhost;
"""%opts)

            if 'tcp_port' in opts.keys():
                F.write("""    type host;
    host localhost;
    port %(tcp_port)s;
}
"""%opts)
            else:
                F.write("""    type uds;
    uds %(rundir)s/ioc@%(name)s/control;
}
"""%opts)

    os.rename(args.out+'.tmp', args.out)

    # Reloading conserver-server
    if args.reload:
        _log.debug('Reloading conserver-server')
        SP.check_call([systemctl,
                    '--user' if args.user else '--system',
                    'restart', 'conserver'], shell=False)
    else:
        sys.stdout.write('# systemctl restart conserver\n')

def getargs():
    from argparse import ArgumentParser

    P = ArgumentParser()
    P.add_argument('--user', action='store_true', default=os.geteuid()!=0,
                   help='Consider user config')
    P.add_argument('--system', dest='user', action='store_false',
                   help='Consider system config')
    P.add_argument('-v', '--verbose', action='count', default=0)

    SP = P.add_subparsers()

    S = SP.add_parser('status', help='List procServ instance state')
    S.set_defaults(func=status)

    S = SP.add_parser('list', help='List procServ instances')
    S.set_defaults(func=syslist)

    S = SP.add_parser('add', help='Create a new procServ instance')
    S.add_argument('-C', '--chdir', default=os.getcwd(), help='Run directory for instance')
    S.add_argument('-P', '--port', help='telnet port')
    S.add_argument('-U', '--user', dest='username')
    S.add_argument('-G', '--group')
    S.add_argument('-H', '--host', help='Target IOC hostname', default='localhost')
    S.add_argument('-S', '--site', help='Allow site-specific configuration')
    S.add_argument('-f', '--force', action='store_true', default=False)
    S.add_argument('-A', '--autostart',action='store_true', default=False,
                    help='Automatically start the service after adding it')
    S.add_argument('-w', '--writeconf', action='store_true', default=True,
                    help='Automatically update Conserver configuration')
    S.add_argument('-D', '--outsysd', default=systemd_dir)
    S.add_argument('-d', '--writesysd', action='store_true', default=True,
                    help='Create System-D service files')
    S.add_argument('-R', '--reload', action='store_true', default=False,
                    help='Restart conserver-server')
    S.add_argument('--command', help='Command script or executable, without path (chdir is added later)')
    S.add_argument('name', help='Instance name')
    #S.add_argument('command', nargs='+', help='Command script or executable, without path (chdir is added later)')
    S.set_defaults(func=addproc)

    S = SP.add_parser('remove', help='Remove a procServ instance')
    S.add_argument('-f', '--force', action='store_true', default=False)
    S.add_argument('-w', '--writeconf', action='store_true', default=True,
                    help='Automatically update Conserver configuration')
    S.add_argument('-D', '--outsysd', default=systemd_dir)
    S.add_argument('-d', '--writesysd', action='store_true', default=True,
                    help='Create System-D service files')
    S.add_argument('-R', '--reload', action='store_true', default=False,
                    help='Restart conserver-server')
    S.add_argument('name', help='Instance name')
    S.set_defaults(func=delproc)

    S = SP.add_parser('write-procs-cf', help='Write conserver config')
    S.add_argument('-f', '--out', default=conserver_conf)
    S.add_argument('-R', '--reload', action='store_true', default=False,
                    help='Restart conserver-server')
    S.set_defaults(func=writeprocs)

    A = P.parse_args()
    if not hasattr(A, 'func'):
        P.print_help()
        sys.exit(1)

    return A

def main(args):
    lvl = _levels[max(0, min(args.verbose, len(_levels)-1))]
    logging.basicConfig(level=lvl)
    conf = getconf(user=args.user)
    args.func(conf, args)
