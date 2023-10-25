# Copyright (c) 2009-2010, Michael Gorven, Stefano Rivera
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.
#
# The youtube Processor is inspired by (and steals the odd RE from) youtube-dl:
#   Copyright (c) 2006-2008 Ricardo Garcia Gonzalez
#   Released under MIT Licence

from cgi import parse_qs
from urllib import urlencode
from urllib import urlopen, build_opener, HTTPError, HTTPRedirectHandler
import logging
import re

from ibid.plugins import Processor, handler, match
from ibid.config import ListOption

default_user_agent = 'Mozilla/5.0'
default_referer = "http://ibid.omnia.za.net/"

features = {}

log = logging.getLogger('plugins.url')

features['tinyurl'] = {
    'description': u'Shorten and lengthen URLs',
    'categories': ('lookup', 'web',),
}
class Shorten(Processor):
    usage = u'shorten <url>'
    feature = ('tinyurl',)

    @match(r'^shorten\s+(\S+\.\S+)$')
    def shorten(self, event, url):
        f = urlopen('http://is.gd/api.php?%s' % urlencode({'longurl': url}))
        shortened = f.read()
        f.close()

        event.addresponse(u'That reduces to: %s', shortened)

class NullRedirect(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None

class Lengthen(Processor):
    usage = u"""<url>
    expand <url>"""
    feature = ('tinyurl',)

    services = ListOption('services', 'List of URL prefixes of URL shortening services', (
        'http://is.gd/', 'http://tinyurl.com/', 'http://ff.im/',
        'http://shorl.com/', 'http://icanhaz.com/', 'http://url.omnia.za.net/',
        'http://snipurl.com/', 'http://tr.im/', 'http://snipr.com/',
        'http://bit.ly/', 'http://cli.gs/', 'http://zi.ma/', 'http://twurl.nl/',
        'http://xrl.us/', 'http://lnk.in/', 'http://url.ie/', 'http://ne1.net/',
        'http://turo.us/', 'http://301url.com/', 'http://u.nu/', 'http://twi.la/',
        'http://ow.ly/', 'http://su.pr/', 'http://tiny.cc/', 'http://ur1.ca/',
    ))

    def setup(self):
        self.lengthen.im_func.pattern = re.compile(r'^(?:((?:%s)\S+)|(?:lengthen\s+|expand\s+)(http://\S+))$' % '|'.join([re.escape(service) for service in self.services]), re.I|re.DOTALL)

    @handler
    def lengthen(self, event, url1, url2):
        url = url1 or url2
        opener = build_opener(NullRedirect())
        try:
            f = opener.open(url)
            f.close()
        except HTTPError, e:
            if e.code in (301, 302, 303, 307):
                event.addresponse(u'That expands to: %s', e.hdrs['location'])
                return
            raise

        event.addresponse(u"No redirect")

features['youtube'] = {
    'description': u'Determine the title and a download URL for a Youtube Video',
    'categories': ('lookup', 'web',),
}
class Youtube(Processor):
    usage = u'<Youtube URL>'

    feature = ('youtube',)

    @match(r'^(?:youtube(?:\.com)?\s+)?'
        r'(?:http://)?(?:\w+\.)?youtube\.com/'
        r'(?:v/|(?:watch(?:\.php)?)?\?(?:.+&)?v=)'
        r'([0-9A-Za-z_-]+)(?(1)[&/].*)?$')
    def youtube(self, event, id):
        for el_type in ('embedded', 'detailpage', 'vevo'):
            url = 'http://www.youtube.com/get_video_info?' + urlencode({
                'video_id': id,
                'el': el_type,
                'ps': 'default',
                'eurl': '',
                'gl': 'US',
                'hl': 'en',
            })
            info = parse_qs(urlopen(url).read())
            if info.get('status', [None])[0] == 'ok':
                break

        if info.get('status', [None])[0] == 'ok':
            event.addresponse(u'%(title)s: %(url)s', {
                'title': info['title'][0].decode('utf-8'),
                'url': 'http://www.youtube.com/get_video?' + urlencode({
                    'video_id': id,
                    't': info['token'][0],
                }),
            })
        else:
            event.addresponse(u"Sorry, I couldn't retreive that, YouTube says: "
                              u"%(status)s: %(reason)s", {
                  'status': info['status'][0],
                  'reason': info['reason'][0],
            })

# vi: set et sta sw=4 ts=4:
