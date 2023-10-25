# Copyright (c) 2008-2009, Michael Gorven
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.

from urlparse import urlparse
from urllib import urlopen
from sys import stderr
import socket

from bzrlib import branch

repositories =  {   '/srv/src/ibid/': 'ibid',
                }
boturl = 'http://kennels.dyndns.org:8080'

def post_change_branch_tip(params):
    repository = urlparse(params.branch.base)[2]
    if repository.startswith('///'):
        repository = repository.replace('//', '', 1)
    if repository in repositories:
        socket.setdefaulttimeout(30)
        try:
            try:
                urlopen('%s/bzr/committed/%s/%s/%s' % (
                        boturl,
                        repositories[repository],
                        params.old_revno+1,
                        params.new_revno
                    )).close()
            except IOError, e:
                if 'reason' in e:
                    print >> stderr, u"Couldn't notify Ibid of commit: %s" \
                                     % (e.reason,)
                elif 'code' in e:
                    print >> stderr, u"Couldn't notify Ibid of commit: HTTP " \
                                     u"code %s" % (e.code,)
                else:
                    print >> stderr, u"Couldn't notify Ibid of commit: %s" \
                                     % (e,)
        finally:
            socket.setdefaulttimeout(None)

branch.Branch.hooks.install_named_hook('post_change_branch_tip',
                                       post_change_branch_tip,
                                       'Trigger Ibid to announce the commit')

# vi: set et sta sw=4 ts=4:
