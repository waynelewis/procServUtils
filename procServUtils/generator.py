
import sys, os, errno, glob
from .conf import getconf

def write_service(F, conf, sect, user=False):
    opts = {
        'name':sect,
        'user':conf.get(sect, 'user'),
        'group':conf.get(sect, 'group'),
        'chdir':conf.get(sect, 'chdir'),
        'command':conf.get(sect, 'command'),
        'port':conf.get(sect, 'port'),
        'userarg':'--user' if user else '--system',
    }

    if 'tcp:' in opts['port']:
        print(opts['port'])
        opts['port'] = opts['port'].split(':')[1]
        print(opts['port'])

    # Set default value for iocsh command
    opts['iocsh_cmd'] = ""

    # See if we should use a site-specific iocsh command
    if conf.has_option(sect, 'site'):
        if conf.get(sect, 'site') == "ess-e3":
            try:
                e3_require_bin = os.environ['E3_REQUIRE_BIN']
                opts['iocsh_cmd'] = "{}/{}".format(e3_require_bin, "iocsh.bash")
            except KeyError:
                print("Please source the desired setE3Env.bash, then rerun this command")
                sys.exit()

    F.write("""
[Unit]
Description=procServ for {name}
After=network.target remote-fs.target
ConditionPathIsDirectory={chdir}
""".format(**opts))

    if conf.has_option(sect, 'host'):
        F.write('ConditionHost=%s\n'%conf.get(sect, 'host'))

    F.write("""
[Service]
Type=simple
ExecStart=/usr/bin/procServ \\
                    --foreground \\
                    --logfile=/var/log/procServ/out-{name} \\
                    --info-file=/run/procserv-{name}/info \\
                    --ignore=^C^D \\
                    --chdir={chdir} \\
                    --name={name} \\
                    --port={port} \\
""".format(**opts))

    if opts['iocsh_cmd'] != '':
        F.write("""                    {iocsh_cmd} \\
""".format(**opts))

    F.write("""                    {command}
                    
SyslogIdentifier=ioc@{name}
""".format(**opts))

    if not user:
        F.write("""
User={user}
Group={group}
""".format(**opts))

    F.write("""
[Install]
WantedBy=multi-user.target
""")

def run(outdir, user=False):
    conf = getconf(user=user)
    service_name_template = 'ioc@%s.service'

    wantsdir = os.path.join(outdir, 'multi-user.target.wants')
    try:
        os.makedirs(wantsdir)
    except OSError as e:
        if e.errno!=errno.EEXIST:
            _log.exception('Creating directory "%s"', wantsdir)
            raise

    # Cleanup of the *.service files at first
    serviceFilesList = glob.glob(os.path.join(outdir, service_name_template % '*'), recursive=True)
    for serviceFile in serviceFilesList:
        try:
            os.remove(serviceFile)
        except:
            _log.debug("Error while trying to delete a service file: %s" % serviceFile)

    # Create new service files according to configured procedures
    for sect in conf.sections():
        if not conf.getboolean(sect, 'instance'):
            continue
        service = service_name_template % sect
        ofile = os.path.join(outdir, service)
        with open(ofile+'.tmp', 'w') as F:
            write_service(F, conf, sect, user=user)

        os.rename(ofile+'.tmp', ofile)
        
        try:
            os.symlink(ofile,
                    os.path.join(wantsdir, service))
        except FileExistsError:
            continue
