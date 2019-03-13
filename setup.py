#!/usr/bin/env python3

from distutils.core import setup

setup (
    name            = 'procServUtils',
    description     = 'Support scripts for procServ',
    packages        = ['procServUtils', 'procServUtils.conf'],
    package_dir     = {'procServUtils': 'procServUtils',
                        'procServUtils.conf': 'conf'},
    package_data    = {'procServUtils': ['*.py'],
                        'procServUtils.conf': ['*.conf']},
    scripts         = ['manage-procs',
                        'systemd-procserv-generator-system',
                        'systemd-procserv-generator-user'],
)
