# Copyright (c) 2008-2010, Michael Gorven, Stefano Rivera, Max Rabkin
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.

from urllib3 import urlopen, HTTPError
from urllib import urlencode, quote
from httplib import BadStatusLine
from urlparse import urljoin
from random import choice, shuffle, randint
from sys import exc_info
from subprocess import Popen, PIPE
import logging
import re

from ibid.compat import ElementTree
from ibid.config import Option, BoolOption
from ibid.plugins import Processor, match, RPC
from ibid.utils.html import get_html_parse_tree
from ibid.utils import file_in_path, unicode_output

log = logging.getLogger('plugins.quotes')

features = {}

features['fortune'] = {
    'description': u'Returns a random fortune.',
    'categories': ('fun', 'lookup',),
}
class Fortune(Processor, RPC):
    usage = u'fortune'
    feature = ('fortune',)

    fortune = Option('fortune', 'Path of the fortune executable', 'fortune')

    def __init__(self, name):
        super(Fortune, self).__init__(name)
        RPC.__init__(self)

    def setup(self):
        if not file_in_path(self.fortune):
            raise Exception("Cannot locate fortune executable")

    @match(r'^fortune$')
    def handler(self, event):
        fortune = self.remote_fortune()
        if fortune:
            event.addresponse(fortune)
        else:
            event.addresponse(u"Couldn't execute fortune")

    def remote_fortune(self):
        fortune = Popen(self.fortune, stdout=PIPE, stderr=PIPE)
        output, error = fortune.communicate()
        code = fortune.wait()

        output = unicode_output(output.strip(), 'replace')

        if code == 0:
            return output
        else:
            return None

features['bash'] = {
    'description': u'Retrieve quotes from bash.org.',
    'categories': ('fun', 'lookup', 'web',),
}
class Bash(Processor):
    usage = u'bash[.org] [(random|<number>)]'

    feature = ('bash',)

    public_browse = BoolOption('public_browse', 'Allow random quotes in public', True)

    @match(r'^bash(?:\.org)?(?:\s+(random|\d+))?$')
    def bash(self, event, id):
        id = id is None and u'random' or id.lower()

        if id == u'random' and event.public and not self.public_browse:
            event.addresponse(u'Sorry, not in public. PM me')
            return

        soup = get_html_parse_tree('http://bash.org/?%s' % id)

        number = u"".join(soup.find('p', 'quote').find('b').contents)
        output = [u'%s:' % number]

        body = soup.find('p', 'qt')
        if not body:
            event.addresponse(u"There's no such quote, but if you keep talking like that maybe there will be")
        else:
            for line in body.contents:
                line = unicode(line).strip()
                if line != u'<br />':
                    output.append(line)
            event.addresponse(u'\n'.join(output), conflate=False)

features['fml'] = {
    'description': u'Retrieves quotes from fmylife.com.',
    'categories': ('fun', 'lookup', 'web',),
}
class FMLException(Exception):
    pass

class FMyLife(Processor):
    usage = u'fml (<number> | [random] | flop | top | last | love | money | kids | work | health | sex | miscellaneous )'

    feature = ('fml',)

    api_url = Option('fml_api_url', 'FML API URL base', 'http://api.betacie.com/')
    # The Ibid API Key, registered by Stefano Rivera:
    api_key = Option('fml_api_key', 'FML API Key', '4b39a7fcaf01c')
    fml_lang = Option('fml_lang', 'FML Lanugage', 'en')

    public_browse = BoolOption('public_browse', 'Allow random quotes in public', True)

    failure_messages = (
            u'Today, I tried to get a quote for %(nick)s but failed. FML',
            u'Today, FML is down. FML',
            u"Sorry, it's broken, the FML admins must having a really bad day",
    )

    def remote_get(self, id):
        url = urljoin(self.api_url, 'view/%s?%s' % (
            id.isalnum() and id + '/nocomment' or quote(id),
            urlencode({'language': self.fml_lang, 'key': self.api_key}))
        )
        f = urlopen(url)
        try:
            tree = ElementTree.parse(f)
        except SyntaxError:
            class_, e, tb = exc_info()
            new_exc = FMLException(u'XML Parsing Error: %s' % unicode(e))
            raise new_exc.__class__, new_exc, tb

        if tree.find('.//error'):
            raise FMLException(tree.findtext('.//error'))

        item = tree.find('.//item')
        if item:
            url = u"http://www.fmylife.com/%s/%s" % (
                item.findtext('category'),
                item.get('id'),
            )
            text = item.find('text').text
            return u'%s\n- %s' % (text, url)

    @match(r'^(?:fml\s+|http://www\.fmylife\.com/\S+/)(\d+|random|flop|top|last|love|money|kids|work|health|sex|miscellaneous)$')
    def fml(self, event, id):
        try:
            body = self.remote_get(id)
        except (FMLException, HTTPError, BadStatusLine):
            event.addresponse(choice(self.failure_messages) % event.sender)
            return

        if body:
            event.addresponse(body)
        elif id.isdigit():
            event.addresponse(u'No such quote')
        else:
            event.addresponse(choice(self.failure_messages) % event.sender)

    @match(r'^fml$')
    def fml_default(self, event):
        if not event.public or self.public_browse:
            self.fml(event, 'random')
        else:
            event.addresponse(u'Sorry, not in public. PM me')

features['tfln'] = {
    'description': u'Looks up quotes from textsfromlastnight.com',
    'categories': ('fun', 'lookup', 'web',),
}
class TextsFromLastNight(Processor):
    usage = u"""tfln [(random|<number>)]
    tfln (worst|best) [(today|this week|this month)]"""

    feature = ('tfln',)

    public_browse = BoolOption('public_browse', 'Allow random quotes in public', True)

    random_pool = []

    def get_tfln(self, section):
        tree = get_html_parse_tree('http://textsfromlastnight.com/%s' % section,
                                   treetype='etree')
        ul = [x for x in tree.findall('.//ul')
              if x.get('id') == 'texts-list'][0]
        id_re = re.compile('^/Text-Replies-(\d+)\.html$')
        for li in ul.findall('li'):
            id = 0
            message=''
            div = [x for x in li.findall('div') if x.get('class') == 'text'][0]
            for a in div.findall('.//a'):
                href = a.get('href')
                if href.startswith('/Texts-From-Areacode-'):
                    message += u'\n' + a.text
                elif href.startswith('/Text-Replies-'):
                    id = int(id_re.match(href).group(1))
                    message += a.text
            yield id, message.strip()

    @match(r'^tfln'
            r'(?:\s+(random|worst|best|\d+))?'
            r'(?:this\s+)?(?:\s+(today|week|month))?$')
    def tfln(self, event, number, timeframe=None):
        number = number is None and u'random' or number.lower()

        if number == u'random' and not timeframe \
                and event.public and not self.public_browse:
            event.addresponse(u'Sorry, not in public. PM me')
            return

        if number in (u'worst', u'best'):
            number = u'Texts-From-%s-Nights' % number.title()
            if timeframe:
                number += u'-' + timeframe.title()
            number += u'.html'
        elif number.isdigit():
            number = 'Text-Replies-%s.html' % number

        if number == u'random':
            if not self.random_pool:
                self.random_pool = [message for message
                        in self.get_tfln(u'Random-Texts-From-Last-Night.html')]
                shuffle(self.random_pool)

            message = self.random_pool.pop()
        else:
            try:
                message = self.get_tfln(number).next()
            except StopIteration:
                event.addresponse(u'No such quote')
                return

        id, body = message
        event.addresponse(
            u'%(body)s\n'
            u'- http://textsfromlastnight.com/Text-Replies-%(id)i.html', {
                'id': id,
                'body': body,
            }, conflate=False)

    @match(r'^(?:http://)?(?:www\.)?textsfromlastnight\.com/'
           r'Text-Replies-(\d+).html$')
    def tfln_url(self, event, id):
        self.tfln(event, id)

features['mlia'] = {
    'description': u'Looks up quotes from MyLifeIsAverage.com and MyLifeIsG.com',
    'categories': ('fun', 'lookup', 'web',),
}
class MyLifeIsAverage(Processor):
    usage = (u"mlia [(<number> | random | recent | today | yesterday | "
             u"this week | this month | this year )]")

    feature = ('mlia',)

    public_browse = BoolOption('public_browse',
                               'Allow random quotes in public', True)

    random_pool = []
    pages = 1

    def find_stories(self, url):
        if isinstance(url, basestring):
            tree = get_html_parse_tree(url, treetype='etree')
        else:
            tree = url

        stories = [div for div in tree.findall('.//div')
                       if div.get(u'class') == u'story s']

        for story in stories:
            body = story.findtext('div').strip()
            id = story.findtext('.//a')
            if isinstance(id, basestring) and id[1:].isdigit():
                id = int(id[1:])
                yield id, body

    @match(r'^mlia(?:\s+this)?'
           r'(?:\s+(\d+|random|recent|today|yesterday|week|month|year))?$')
    def mlia(self, event, query):
        query = query is None and u'random' or query.lower()

        if query == u'random' and event.public and not self.public_browse:
            event.addresponse(u'Sorry, not in public. PM me')
            return

        url = 'http://mylifeisaverage.com/'

        if query == u'random' or query is None:
            if not self.random_pool:
                purl = url + str(randint(1, self.pages))
                tree = get_html_parse_tree(purl, treetype='etree')
                self.random_pool = list(self.find_stories(tree))
                shuffle(self.random_pool)

                pagination = [ul for ul in tree.findall('.//ul')
                                       if ul.get(u'class') == u'pages'][0]
                self.pages = int(
                    [li for li in pagination.findall('li')
                        if li.get(u'class') == u'last'][0]
                    .find(u'a').get(u'href'))

            story = self.random_pool.pop()

        else:
            try:
                if query.isdigit():
                    surl = url + '/s/' + query
                else:
                    surl = url + '/best/' + query

                story = self.find_stories(surl).next()

            except StopIteration:
                event.addresponse(u'No such quote')
                return

        id, body = story
        url += 's/%i' % id
        event.addresponse(u'%(body)s\n- %(url)s', {
            'url': url,
            'body': body,
        })

    @match(r'^(?:http://)?(?:www\.)?mylifeisaverage\.com'
           r'/s/(\d+)$')
    def mlia_url(self, event, id):
        self.mlia(event, id)

features['bible'] = {
    'description': u'Retrieves Bible verses',
    'categories': ('lookup', 'web',),
}
class Bible(Processor):
    usage = u"""bible <passages> [in <version>]
    <book> <verses> [in <version>]"""

    feature = ('bible',)
    # http://labs.bible.org/api/ is an alternative
    # Their feature set is a little different, but they should be fairly
    # compatible
    api_url = Option('bible_api_url', 'Bible API URL base',
                    'http://api.preachingcentral.com/bible.php')

    psalm_pat = re.compile(r'\bpsalm\b', re.IGNORECASE)

    # The API doesn't seem to work with the apocrypha, even when looking in
    # versions that include it
    books = '|'.join(['Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy',
    'Joshua', 'Judges', 'Ruth', '(?:1|2|I|II) Samuel', '(?:1|2|I|II) Kings',
    '(?:1|2|I|II) Chronicles', 'Ezra', 'Nehemiah', 'Esther', 'Job', 'Psalms?',
    'Proverbs', 'Ecclesiastes', 'Song(?: of (?:Songs|Solomon)?)?',
    'Canticles', 'Isaiah', 'Jeremiah', 'Lamentations',
    'Ezekiel', 'Daniel', 'Hosea', 'Joel', 'Amos', 'Obadiah', 'Jonah', 'Micah',
    'Nahum', 'Habakkuk', 'Zephaniah', 'Haggai', 'Zechariah', 'Malachi',
    'Matthew', 'Mark', 'Luke', 'John', 'Acts', 'Romans',
    '(?:1|2|I|II) Corinthians', 'Galatians', 'Ephesians', 'Philippians',
    'Colossians', '(?:1|2|I|II) Thessalonians', '(?:1|2|I|II) Timothy',
    'Titus', 'Philemon', 'Hebrews', 'James', '(?:1|2|I|II) Peter',
    '(?:1|2|3|I|II|III) John', 'Jude',
    'Revelations?(?: of (?:St.|Saint) John)?']).replace(' ', '\s*')

    @match(r'^bible\s+(.*?)(?:\s+(?:in|from)\s+(.*))?$')
    def bible(self, event, passage, version=None):
        passage = self.psalm_pat.sub('psalms', passage)

        params = {'passage': passage.encode('utf-8'),
                  'type': 'xml',
                  'formatting': 'plain'}
        if version:
            params['version'] = version.lower().encode('utf-8')

        f = urlopen(self.api_url + '?' + urlencode(params))
        tree = ElementTree.parse(f)

        message = self.formatPassage(tree)
        if message:
            event.addresponse(message)
        errors = list(tree.findall('.//error'))
        if errors:
            event.addresponse(u'There were errors: %s.', '. '.join(err.text for err in errors))
        elif not message:
            event.addresponse(u"I couldn't find that passage.")

    # Allow queries which are quite definitely bible references to omit "bible".
    # Specifically, they must start with the name of a book and be followed only
    # by book names, chapters and verses.
    @match(r'^((?:(?:' + books + ')(?:\d|[-:,]|\s)*)+?)(?:\s+(?:in|from)\s+(.*))?$')
    def bookbible(self, *args):
        self.bible(*args)

    def formatPassage(self, xml):
        message = []
        oldref = (None, None, None)
        for item in xml.findall('.//item'):
            ref, text = self.verseInfo(item)
            if oldref[0] != ref[0]:
                message.append(u'(%s %s:%s)' % ref)
            elif oldref[1] != ref[1]:
                message.append(u'(%s:%s)' % ref[1:])
            else:
                message.append(u'%s' % ref[2])
            oldref = ref

            message.append(text)

        return u' '.join(message)

    def verseInfo(self, xml):
        book, chapter, verse, text = map(xml.findtext,
                                        ('bookname', 'chapter', 'verse', 'text'))
        return ((book, chapter, verse), text)

# vi: set et sta sw=4 ts=4:
