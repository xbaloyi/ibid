# Copyright (c) 2008-2011, Michael Gorven, Stefano Rivera, Jonathan Hitchcock
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.

from urllib3 import HTTPError
from time import time
from datetime import datetime
import re
import logging

import feedparser

from ibid.compat import ElementTree
from ibid.config import DictOption
from ibid.plugins import Processor, match, handler
from ibid.utils import ago, decode_htmlentities, generic_webservice, \
                       json_webservice, parse_timestamp

log = logging.getLogger('plugins.social')
features = {}

features['lastfm'] = {
    'description': u'Lists the tracks last listened to by the specified user.',
    'categories': ('lookup', 'web',),
}
class LastFm(Processor):
    usage = u'last.fm for <username>'

    feature = ('lastfm',)

    @match(r'^last\.?fm\s+for\s+(\S+?)\s*$')
    def listsongs(self, event, username):
        songs = feedparser.parse('http://ws.audioscrobbler.com/1.0/user/%s/recenttracks.rss?%s' % (username, time()))
        if songs['bozo']:
            event.addresponse(u'No such user')
        else:
            event.addresponse(u', '.join(u'%s (%s ago)' % (
                    e.title,
                    ago(event.time - parse_timestamp(e.updated))
                ) for e in songs['entries']))

features['microblog'] = {
    'description': u'Looks up messages on microblogging services like twitter '
                   u'and identica.',
    'categories': ('lookup', 'web',),
}
class Twitter(Processor):
    usage = u"""latest (tweet|identica) from <name>
    (tweet|identica) <number>"""

    feature = ('microblog',)

    default = {
        'twitter':   {'endpoint': 'http://twitter.com/',   'api': 'twitter',  'name': 'tweet', 'user': 'twit'},
        'tweet':     {'endpoint': 'http://twitter.com/',   'api': 'twitter',  'name': 'tweet', 'user': 'twit'},
        'identica':  {'endpoint': 'http://identi.ca/api/', 'api': 'laconica', 'name': 'dent',  'user': 'denter'},
        'identi.ca': {'endpoint': 'http://identi.ca/api/', 'api': 'laconica', 'name': 'dent',  'user': 'denter'},
        'dent':      {'endpoint': 'http://identi.ca/api/', 'api': 'laconica', 'name': 'dent',  'user': 'denter'},
    }
    services = DictOption('services', 'Micro blogging services', default)

    class NoTweetsException(Exception):
        pass

    def setup(self):
        self.update.im_func.pattern = re.compile(r'^(%s)\s+(\d+)$' % '|'.join(self.services.keys()), re.I)
        self.latest.im_func.pattern = re.compile(r'^(?:latest|last)\s+(%s)\s+(?:update\s+)?(?:(?:by|from|for)\s+)?@?(\S+)$'
                % '|'.join(self.services.keys()), re.I)

    def remote_update(self, service, id):
        status = json_webservice('%sstatuses/show/%s.json' % (service['endpoint'], id))

        return {'screen_name': status['user']['screen_name'], 'text': decode_htmlentities(status['text'])}

    def remote_latest(self, service, user):
        if service['api'] == 'twitter':
            # Twitter ommits retweets in the JSON and XML results:
            statuses = generic_webservice('%sstatuses/user_timeline/%s.atom'
                    % (service['endpoint'], user.encode('utf-8')),
                    {'count': 1})
            tree = ElementTree.fromstring(statuses)
            latest = tree.find('{http://www.w3.org/2005/Atom}entry')
            if latest is None:
                raise self.NoTweetsException(user)
            return {
                'text': latest.findtext('{http://www.w3.org/2005/Atom}content')
                        .split(': ', 1)[1],
                'ago': ago(datetime.utcnow() - parse_timestamp(
                    latest.findtext('{http://www.w3.org/2005/Atom}published'))),
                'url': [x for x
                     in latest.getiterator('{http://www.w3.org/2005/Atom}link')
                     if x.get('type') == 'text/html'
                  ][0].get('href'),
            }
        elif service['api'] == 'laconica':
            statuses = json_webservice('%sstatuses/user_timeline/%s.json'
                    % (service['endpoint'], user.encode('utf-8')),
                    {'count': 1})
            if not statuses:
                raise self.NoTweetsException(user)
            latest = statuses[0]
            url = '%s/notice/%i' % (service['endpoint'].split('/api/', 1)[0],
                                    latest['id'])

        return {
            'text': decode_htmlentities(latest['text']),
            'ago': ago(datetime.utcnow()
                       - parse_timestamp(latest['created_at'])),
            'url': url,
        }

    @handler
    def update(self, event, service_name, id):
        service = self.services[service_name.lower()]
        try:
            event.addresponse(u'%(screen_name)s: "%(text)s"', self.remote_update(service, int(id)))
        except HTTPError, e:
            if e.code in (401, 403):
                event.addresponse(u'That %s is private', service['name'])
            elif e.code == 404:
                event.addresponse(u'No such %s', service['name'])
            else:
                log.debug(u'%s raised %s', service['name'], unicode(e))
                event.addresponse(u'I can only see the Fail Whale')

    @handler
    def latest(self, event, service_name, user):
        service = self.services[service_name.lower()]
        try:
            event.addresponse(u'"%(text)s" %(ago)s ago, %(url)s', self.remote_latest(service, user))
        except HTTPError, e:
            if e.code in (401, 403):
                event.addresponse(u"Sorry, %s's feed is private", user)
            elif e.code == 404:
                event.addresponse(u'No such %s', service['user'])
            else:
                log.debug(u'%s raised %s', service['name'], unicode(e))
                event.addresponse(u'I can only see the Fail Whale')
        except self.NoTweetsException, e:
            event.addresponse(
                u'It appears that %(user)s has never %(tweet)sed', {
                    'user': user,
                    'tweet': service['name'],
                })

    @match(r'^https?://(?:www\.)?twitter\.com/(?:#!/)?[^/ ]+/statuse?s?/(\d+)$')
    def twitter(self, event, id):
        self.update(event, u'twitter', id)

    @match(r'^https?://(?:www\.)?identi.ca/notice/(\d+)$')
    def identica(self, event, id):
        self.update(event, u'identica', id)

# vi: set et sta sw=4 ts=4:
