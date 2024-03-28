# Copyright (c) 2009-2011, Michael Gorven, Stefano Rivera
# Released under terms of the MIT/X/Expat Licence. See COPYING for details.

from datetime import datetime
import logging
from random import choice
import re

from dateutil.tz import tzlocal, tzutc

from ibid.plugins import Processor, match, handler, authorise, auth_responses, \
                         RPC
from ibid.config import Option, IntOption, ListOption
from ibid.db import IbidUnicode, IbidUnicodeText, Boolean, Integer, DateTime, \
                    Table, Column, ForeignKey, server_default, \
                    relation, synonym, func, or_, \
                    Base, VersionedSchema, \
                    get_regexp_op
from ibid.plugins.identity import get_identities
from ibid.utils import format_date

features = {'factoid': {
    'description': u'Factoids are arbitrary pieces of information stored by a '
                   u'key. Factoids beginning with a command such as "<action>" '
                   u'or "<reply>" will supress the "name verb value" output. '
                   u"Search and replace functions won't use real regexs unless "
                   u"appended with the 'r' flag.",
    'categories': ('lookup', 'remember',),
}}

log = logging.getLogger('plugins.factoid')

default_verbs = ('is', 'are', 'has', 'have', 'was', 'were', 'do', 'does', 'can', 'should', 'would')
default_interrogatives = ('what', 'wtf', 'where', 'when', 'who', "what's", "who's")

def strip_name(unstripped):
    "Apply to factoid names, as we use unstripped matches"
    return re.match(r'^\s*(.*?)\s*[?!.]*\s*$', unstripped, re.DOTALL).group(1)

def escape_name(name):
    "Turn a $arg factoid name to _%"
    return name.replace('%', '\\%').replace('_', '\\_').replace('$arg', '_%')

def unescape_name(name):
    "Turn a _% factoid name to $arg"
    return name.replace('_%', '$arg').replace('\\%', '%').replace('\\_', '_')

class FactoidName(Base):
    __table__ = Table('factoid_names', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('name', IbidUnicodeText(32, case_insensitive=True),
           key='_name', nullable=False, unique=True, index=True),
    Column('factoid_id', Integer, ForeignKey('factoids.id'), nullable=False,
           index=True),
    Column('identity_id', Integer, ForeignKey('identities.id'), index=True),
    Column('time', DateTime, nullable=False),
    Column('factpack', Integer, ForeignKey('factpacks.id'), index=True),
    Column('wild', Boolean, nullable=False, default=False, index=True),
    useexisting=True)

    class FactoidNameSchema(VersionedSchema):
        def upgrade_1_to_2(self):
            self.add_column(Column('factpack', Integer,
                                   ForeignKey('factpacks.id')))
        def upgrade_2_to_3(self):
            self.add_index(self.table.c.name)
        def upgrade_3_to_4(self):
            self.add_index(self.table.c.name)
            self.add_index(self.table.c.factoid_id)
            self.add_index(self.table.c.identity_id)
            self.add_index(self.table.c.factpack)
        def upgrade_4_to_5(self):
            self.alter_column(Column('name', IbidUnicode(64), key='_name',
                                     nullable=False, unique=True, index=True))
        def upgrade_5_to_6(self):
            self.alter_column(Column('name', IbidUnicodeText(32), key='_name',
                                     nullable=False, unique=True, index=True))
        def upgrade_6_to_7(self):
            self.add_column(Column('wild', Boolean, server_default('0'),
                                   nullable=False, index=True, default=False))
            for row in self.upgrade_session.query(FactoidName) \
                    .filter(FactoidName.name.like('%#_#%%', escape='#')) \
                    .all():
                row.wild = True
                self.upgrade_session.save_or_update(row)
        def upgrade_7_to_8(self):
            self.drop_index(self.table.c._name)
            self.alter_column(Column('name',
                                     IbidUnicodeText(32, case_insensitive=True),
                                     key='_name', nullable=False, unique=True,
                                     index=True), force_rebuild=True)
            self.add_index(self.table.c._name)

    __table__.versioned_schema = FactoidNameSchema(__table__, 8)

    def __init__(self, name, identity_id, factoid_id=None, factpack=None):
        self.name = name
        self.factoid_id = factoid_id
        self.identity_id = identity_id
        self.time = datetime.utcnow()
        self.factpack = factpack

    def __repr__(self):
        return u'<FactoidName %s %s>' % (self.name, self.factoid_id)

    def _get_name(self):
        return unescape_name(self._name)

    def _set_name(self, name):
        self.wild = u'$arg' in name
        self._name = escape_name(name)

    name = synonym('_name', descriptor=property(_get_name, _set_name))

class FactoidValue(Base):
    __table__ = Table('factoid_values', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('value', IbidUnicodeText, nullable=False),
    Column('factoid_id', Integer, ForeignKey('factoids.id'), nullable=False,
           index=True),
    Column('identity_id', Integer, ForeignKey('identities.id'), index=True),
    Column('time', DateTime, nullable=False),
    Column('factpack', Integer, ForeignKey('factpacks.id'), index=True),
    useexisting=True)

    class FactoidValueSchema(VersionedSchema):
        def upgrade_1_to_2(self):
            self.add_column(Column('factpack', Integer, ForeignKey('factpacks.id')))
        def upgrade_2_to_3(self):
            self.add_index(self.table.c.factoid_id)
            self.add_index(self.table.c.identity_id)
            self.add_index(self.table.c.factpack)
        def upgrade_3_to_4(self):
            self.alter_column(Column('value', IbidUnicodeText, nullable=False),
                              force_rebuild=True)

    __table__.versioned_schema = FactoidValueSchema(__table__, 4)

    def __init__(self, value, identity_id, factoid_id=None, factpack=None):
        self.value = value
        self.factoid_id = factoid_id
        self.identity_id = identity_id
        self.time = datetime.utcnow()
        self.factpack = factpack

    def __repr__(self):
        return u'<FactoidValue %s %s>' % (self.factoid_id, self.value)

class Factoid(Base):
    __table__ = Table('factoids', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('time', DateTime, nullable=False),
    Column('factpack', Integer, ForeignKey('factpacks.id'), index=True),
    useexisting=True)

    names = relation(FactoidName, cascade='all,delete', backref='factoid')
    values = relation(FactoidValue, cascade='all,delete', backref='factoid')

    class FactoidSchema(VersionedSchema):
        def upgrade_1_to_2(self):
            self.add_column(Column('factpack', Integer,
                                   ForeignKey('factpacks.id')))
        def upgrade_2_to_3(self):
            self.add_index(self.table.c.factpack)

    __table__.versioned_schema = FactoidSchema(__table__, 3)

    def __init__(self, factpack=None):
        self.time = datetime.utcnow()
        self.factpack = factpack

    def __repr__(self):
        return u"<Factoid %s = %s>" % (', '.join([name.name for name in self.names]), ', '.join([value.value for value in self.values]))

class Factpack(Base):
    __table__ = Table('factpacks', Base.metadata,
    Column('id', Integer, primary_key=True),
    Column('name', IbidUnicode(64, case_insensitive=True),
           nullable=False, unique=True, index=True),
    useexisting=True)

    class FactpackSchema(VersionedSchema):
        def upgrade_1_to_2(self):
            self.add_index(self.table.c.name)
        def upgrade_2_to_3(self):
            self.drop_index(self.table.c.name)
            self.alter_column(Column('name',
                                     IbidUnicode(64, case_insensitive=True),
                                     nullable=False, unique=True, index=True),
                              force_rebuild=True)
            self.add_index(self.table.c.name)

    __table__.versioned_schema = FactpackSchema(__table__, 3)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return u'<Factpack %s>' % (self.name,)

action_re = re.compile(r'^\s*<action>\s*')
reply_re = re.compile(r'^\s*<reply>\s*')
escape_like_re = re.compile(r'([%_#])')

def get_factoid(session, name, number, pattern, is_regex, all=False,
                literal=False):
    """session: SQLAlchemy session
    name: Factoid name (can contain arguments unless literal query)
    number: If not None, restrict to factoid[number] (or factoid[number:] for literal queries)
    pattern: If not None, restrict to factoids matching this pattern (cannot be used in conjuction with number)
    is_regex: Pattern is a real regex
    all: Return a random factoid from the set if False
    literal: Match factoid name literally (implies all)
    if all or literal, a list is returned; otherwise a single factoid is returned
    if nothing is found, either an empty list or None is returned
    """
    assert not (number and pattern), u'number and pattern cannot be used together'
    if literal:
        all = True # as mentioned in the docstring
    # First pass for exact matches, if necessary again for wildcard matches
    if literal:
        passes = (False,)
    else:
        passes = (False, True)
    for wild in passes:
        factoid = None
        query = session.query(Factoid)\
                .add_entity(FactoidName).join(Factoid.names)\
                .add_entity(FactoidValue).join(Factoid.values)
        if wild:
            # Reversed LIKE because factoid name contains SQL wildcards if
            # factoid supports arguments
            query = query.filter(
                    'lower(:fact) LIKE lower(name) ESCAPE :escape'
                ).params(fact=name, escape='\\')
        else:
            query = query.filter(FactoidName.name == escape_name(name))
        # For normal matches, restrict to the subset applicable
        if not literal:
            query = query.filter(FactoidName.wild == wild)

        if pattern:
            if is_regex:
                op = get_regexp_op(session)
                query = query.filter(op(FactoidValue.value, pattern))
            else:
                pattern = '%%%s%%' % escape_like_re.sub(r'#\1', pattern)
                query = query.filter(func.lower(FactoidValue.value)
                                     .like(pattern, escape='#'))

        if number is not None:
            number = max(0, int(number) - 1)
            try:
                # The .all() is to ensure the result is a list.
                # It gets len()ed later
                if literal:
                    return query.order_by(FactoidValue.id).all()[number:]
                else:
                    factoid = query.order_by(FactoidValue.id).all()[number]
            except IndexError:
                continue
        if all:
            if factoid is not None:
                return [factoid]
            else:
                factoid = query.all()
        else:
            factoid = factoid or query.order_by(func.random()).first()
        if factoid:
            return factoid
    if all:
        return []
    return None

class Utils(Processor):
    usage = u'literal <name> [( #<from number> | /<pattern>/[r] )]'
    feature = ('factoid',)

    @match(r'^literal\s+(.+?)(?:\s+#(\d+)|\s+(?:/(.+?)/(r?)))?$')
    def literal(self, event, name, number, pattern, is_regex):
        factoids = get_factoid(event.session, name, number, pattern, is_regex,
                literal=True)
        number = number and int(number) or 1
        if factoids:
            event.addresponse(u', '.join(u'%i: %s'
                % (index + number, value.value)
                  for index, (factoid, name, value) in enumerate(factoids)))
        else:
            factoids = get_factoid(event.session, name, None, pattern, is_regex,
                literal=True)
            if factoids:
                event.addresponse(u"I only know %(number)d things about %(name)s", {
                    u'number': len(factoids),
                    u'name': name,
                })


class Forget(Processor):
    usage = u"""forget <name> [( #<number> | /<pattern>/[r] )]
    <name> is the same as <other name>"""
    feature = ('factoid',)

    priority = 10
    permission = u'factoid'
    permissions = (u'factoidadmin',)

    @match(r'^forget\s+(.+?)(?:\s+#(\d+)|\s+(?:/(.+?)/(r?)))?$')
    @authorise(fallthrough=False)
    def forget(self, event, name, number, pattern, is_regex):
        factoids = get_factoid(event.session, name, number, pattern, is_regex, all=True, literal=True)
        if factoids:
            factoidadmin = auth_responses(event, u'factoidadmin')
            identities = get_identities(event)
            factoid = event.session.query(Factoid).get(factoids[0][0].id)

            if len(factoids) > 1 and pattern is not None:
                event.addresponse(u'Pattern matches multiple factoids, please be more specific')
                return

            if number or pattern:
                if factoids[0][2].identity_id not in identities and not factoidadmin:
                    return

                if event.session.query(FactoidValue).filter_by(factoid_id=factoid.id).count() == 1:
                    if len(filter(lambda x: x.identity_id not in identities, factoid.names)) > 0 and not factoidadmin:
                        return
                    id = factoid.id
                    event.session.delete(factoid)
                    event.session.commit()
                    log.info(u"Deleted factoid %s (%s) by %s/%s (%s)",
                            id, name, event.account, event.identity, event.sender['connection'])
                else:
                    id = factoids[0][2].id
                    event.session.delete(factoids[0][2])
                    event.session.commit()
                    log.info(u"Deleted value %s (%s) of factoid %s (%s) by %s/%s (%s)",
                            id, factoids[0][2].value, factoid.id, name,
                            event.account, event.identity, event.sender['connection'])

            else:
                if factoids[0][1].identity_id not in identities and not factoidadmin:
                    return

                if event.session.query(FactoidName).filter_by(factoid_id=factoid.id).count() == 1:
                    if len(filter(lambda x: x.identity_id not in identities, factoid.values)) > 0 and not factoidadmin:
                        return
                    id = factoid.id
                    event.session.delete(factoid)
                    event.session.commit()
                    log.info(u"Deleted factoid %s (%s) by %s/%s (%s)",
                            id, name, event.account, event.identity,
                            event.sender['connection'])
                else:
                    id = factoids[0][1].id
                    event.session.delete(factoids[0][1])
                    event.session.commit()
                    log.info(u"Deleted name %s (%s) of factoid %s (%s) by %s/%s (%s)",
                            id, factoids[0][1].name, factoid.id, factoids[0][0].names[0].name,
                            event.account, event.identity, event.sender['connection'])

            event.addresponse(True)
        else:
            factoids = get_factoid(event.session, name, None, pattern, is_regex, all=True, literal=True)
            if factoids:
                event.addresponse(u"I only know %(number)d things about %(name)s", {
                    u'number': len(factoids),
                    u'name': name,
                })
            else:
                event.addresponse(u"I didn't know about %s anyway", name)

    @match(r'^(.+)\s+is\s+the\s+same\s+as\s+(.+)$')
    @authorise(fallthrough=False)
    def alias(self, event, target, source):

        target = strip_name(target)

        if target == u'':
            event.addresponse(u"Sorry, I'm not interested in empty factoids")
            return

        if target.lower() == source.lower():
            event.addresponse(u"That makes no sense, they *are* the same")
            return

        factoid = event.session.query(Factoid).join(Factoid.names) \
                .filter(FactoidName.name==escape_name(source)).first()
        if factoid:
            target_factoid = event.session.query(FactoidName) \
                    .filter(FactoidName.name==escape_name(target)).first()
            if target_factoid:
                event.addresponse(u"I already know stuff about %s", target)
                return

            name = FactoidName(unicode(target), event.identity)
            factoid.names.append(name)
            event.session.save_or_update(factoid)
            event.session.commit()
            event.addresponse(True)
            log.info(u"Added name '%s' to factoid %s (%s) by %s/%s (%s)",
                    name.name, factoid.id, factoid.names[0].name,
                    event.account, event.identity, event.sender['connection'])
        else:
            event.addresponse(u"I don't know about %s", source)

class Search(Processor):
    usage = u'search [for] [<limit>] [(facts|values) [containing]] (<pattern>|/<pattern>/[r]) [from <start>]'
    feature = ('factoid',)

    limit = IntOption('search_limit', u'Maximum number of results to return', 30)
    default = IntOption('search_default', u'Default number of results to return', 10)

    regex_re = re.compile(r'^/(.*)/(r?)$')

    @match(r'^search\s+(?:for\s+)?(?:(\d+)\s+)?(?:(facts?|values?)\s+)?(?:containing\s+)?(.+?)(?:\s+from)?(?:\s+(\d+))?\s*$',
            version='deaddressed')
    def search(self, event, limit, search_type, pattern, start):
        limit = limit and min(int(limit), self.limit) or self.default
        start = start and max(int(start) - 1, 0) or 0

        search_type = search_type and search_type.lower() or u""

        origpattern = pattern
        m = self.regex_re.match(pattern)
        is_regex = False
        if m:
            pattern = m.group(1)
            is_regex = bool(m.group(2))

        # Hack: We replace $arg with _%, but this won't match a partial
        # "$arg" string
        if is_regex:
            filter_op = get_regexp_op(event.session)
            name_pattern = pattern.replace(r'\$arg', '_%')
        else:
            filter_op = lambda x, y: x.like(y, escape='#')
            pattern = '%%%s%%' % escape_like_re.sub(r'#\1', pattern)
            name_pattern = pattern.replace('$arg', '#_#%')

        query = event.session.query(Factoid)\
                             .join(Factoid.names).add_entity(FactoidName)\
                             .join(Factoid.values)

        if search_type.startswith('fact'):
            query = query.filter(filter_op(FactoidName.name, name_pattern))
        elif search_type.startswith('value'):
            query = query.filter(filter_op(FactoidValue.value, pattern))
        else:
            query = query.filter(or_(filter_op(FactoidName.name, name_pattern),
                                     filter_op(FactoidValue.value, pattern)))

        # Pre-evalute the iterable or the if statement will be True in SQLAlchemy 0.4. LP: #383286
        matches = [match for match in query.all()]

        bounded_matches = matches[start:start+limit]
        if bounded_matches:
            event.addresponse(u'; '.join(
                u'%s [%s]' % (fname.name, len(factoid.values))
                for factoid, fname in bounded_matches))
        elif len(matches):
            event.addresponse(u"I could only find %(number)d things that matched '%(pattern)s'", {
                u'number': len(matches),
                u'pattern': origpattern,
            })
        else:
            event.addresponse(u"I couldn't find anything that matched '%s'" % origpattern)

def _interpolate(message, event):
    "Expand factoid variables"
    utcnow = datetime.utcnow()
    now = utcnow.replace(tzinfo=tzutc()).astimezone(tzlocal())

    message = message.replace(u'$who', event.sender['nick'])
    message = message.replace(u'$channel', event.channel)
    message = message.replace(u'$year', unicode(now.year))
    message = message.replace(u'$month', unicode(now.month))
    message = message.replace(u'$day', unicode(now.day))
    message = message.replace(u'$hour', unicode(now.hour))
    message = message.replace(u'$minute', unicode(now.minute))
    message = message.replace(u'$second', unicode(now.second))
    message = message.replace(u'$date', format_date(utcnow, 'date'))
    message = message.replace(u'$time', format_date(utcnow, 'time'))
    message = message.replace(u'$dow', unicode(now.strftime('%A')))
    message = message.replace(u'$unixtime', unicode(utcnow.strftime('%s')))
    return message

class Get(Processor, RPC):
    usage = u'<factoid> [( #<number> | /<pattern>/[r] )]'
    feature = ('factoid',)

    priority = 200

    interrogatives = ListOption('interrogatives', 'Question words to strip', default_interrogatives)
    verbs = ListOption('verbs', 'Verbs that split name from value', default_verbs)

    def __init__(self, name):
        super(Get, self).__init__(name)
        RPC.__init__(self)

    def setup(self):
        self.get.im_func.pattern = re.compile(
                r'^(?:(?:%s)\s+(?:(?:%s)\s+)?)?(.+?)(?:\s+#(\d+))?(?:\s+/(.+?)/(r?))?$'
                  % ('|'.join(self.interrogatives),
                '|'.join(self.verbs)), re.I)

    @handler
    def get(self, event, name, number, pattern, is_regex):
        response = self.remote_get(name, number, pattern, is_regex, event)
        if response:
            event.addresponse(response)

    def remote_get(self, name, number=None, pattern=None, is_regex=None, event={}):
        factoid = get_factoid(event.session, name, number, pattern, is_regex)

        if factoid:
            (factoid, fname, fvalue) = factoid
            reply = fvalue.value
            oname = fname.name
            pattern = re.escape(fname.name).replace(r'\$arg', '(.*)')
            args = re.match(pattern, name, re.I | re.U).groups()

            for i, capture in enumerate(args):
                reply = reply.replace('$%s' % (i + 1), capture)
                oname = oname.replace('$arg', capture, 1)

            reply = _interpolate(reply, event)

            (reply, count) = action_re.subn('', reply)
            if count:
                return {'action': True, 'reply': reply}

            (reply, count) = reply_re.subn('', reply)
            if count:
                return {'address': False, 'reply': reply}

            reply = u'%s %s' % (oname, reply)
            return reply

class Set(Processor):
    usage = u"""<name> (<verb>|=<verb>=) [also] <value>
    last set factoid"""
    feature = ('factoid',)

    interrogatives = ListOption('interrogatives', 'Question words to strip', default_interrogatives)
    verbs = ListOption('verbs', 'Verbs that split name from value', default_verbs)

    priority = 800
    permission = u'factoid'
    last_set_factoid = None

    def setup(self):
        self.set_factoid.im_func.pattern = re.compile(
            r'^(no[,.: ]\s*)?(.+?)\s+(also\s+)?(?:=(\S+)=)?(?(4)|(%s))(\s+also)?\s+((?(3).+|(?!.*=\S+=).+))$'
            % '|'.join(self.verbs), re.I)
        self.set_factoid.im_func.message_version = 'deaddressed'

    @handler
    @authorise(fallthrough=False)
    def set_factoid(self, event, correction, name, addition1, verb1, verb2, addition2, value):
        verb = verb1 or verb2
        addition = addition1 or addition2

        name = strip_name(name)

        if name == u'':
            event.addresponse(u"Sorry, I'm not interested in empty factoids")
            return

        if name.lower() in self.interrogatives:
            event.addresponse(choice((
                u"I'm afraid I have no idea",
                u"Not a clue, sorry",
                u"Erk, dunno",
            )))
            return

        factoid = event.session.query(Factoid).join(Factoid.names)\
                .filter(FactoidName.name==escape_name(name)).first()
        if factoid:
            if correction:
                identities = get_identities(event)
                if not auth_responses(event, u'factoidadmin') and len(filter(lambda x: x.identity_id not in identities, factoid.values)) > 0:
                    return
                for fvalue in factoid.values:
                    event.session.delete(fvalue)
            elif not addition:
                event.addresponse(u'I already know stuff about %s', name)
                return
        else:
            factoid = Factoid()
            fname = FactoidName(unicode(name), event.identity)
            factoid.names.append(fname)
            event.session.save_or_update(factoid)
            event.session.flush()
            log.info(u"Creating factoid %s with name '%s' by %s", factoid.id, fname.name, event.identity)

        if not reply_re.match(value) and not action_re.match(value):
            value = '%s %s' % (verb, value)
        fvalue = FactoidValue(unicode(value), event.identity)
        factoid.values.append(fvalue)
        event.session.save_or_update(factoid)
        event.session.commit()
        self.last_set_factoid=factoid.names[0].name
        log.info(u"Added value '%s' to factoid %s (%s) by %s/%s (%s)",
                fvalue.value, factoid.id, factoid.names[0].name,
                event.account, event.identity, event.sender['connection'])
        event.addresponse(choice((
                u'If you say so',
                u'One learns a new thing every day',
                u"I'll remember that",
                u'Got it',
            )))

    @match(r'^(?:last\s+set\s+factoid|what\s+did\s+\S+\s+just\s+set)$')
    def last_set(self, event):
        if self.last_set_factoid is None:
            event.addresponse(u'Sorry, nobody has taught me anything recently')
        else:
            event.addresponse(u'It was: %s', self.last_set_factoid)

class Modify(Processor):
    usage = u"""<name> [( #<number> | /<pattern>/[r] )] += <suffix>
    <name> [( #<number> | /<pattern>/[r] )] ~= ( s/<regex>/<replacement>/[g][i][r] | y/<source>/<dest>/ )"""
    feature = ('factoid',)

    permission = u'factoid'
    permissions = (u'factoidadmin',)
    priority = 190

    @match(r'^(.+?)(?:\s+#(\d+)|\s+/(.+?)/(r?))?\s*\+=(.+)$', version='deaddressed')
    @authorise(fallthrough=False)
    def append(self, event, name, number, pattern, is_regex, suffix):
        name = strip_name(name)
        factoids = get_factoid(event.session, name, number, pattern, is_regex, all=True, literal=True)
        if len(factoids) == 0:
            if pattern:
                event.addresponse(u"I don't know about any %(name)s matching %(pattern)s", {
                    'name': name,
                    'pattern': pattern,
                })
            else:
                factoids = get_factoid(event.session, name, None, pattern, is_regex, all=True)
                if factoids:
                    event.addresponse(u"I only know %(number)d things about %(name)s", {
                        u'number': len(factoids),
                        u'name': name,
                    })
                else:
                    event.addresponse(u"I don't know about %s", name)
        elif len(factoids) > 1 and number is None:
            event.addresponse(u"Pattern matches multiple factoids, please be more specific")
        else:
            factoidadmin = auth_responses(event, u'factoidadmin')
            identities = get_identities(event)
            factoid = factoids[0]

            if factoid[2].identity_id not in identities and not factoidadmin:
                return

            oldvalue = factoid[2].value
            factoid[2].value += suffix
            event.session.save_or_update(factoid[2])
            event.session.commit()

            log.info(u"Appended '%s' to value %s of factoid %s (%s) by %s/%s (%s)",
                    suffix, factoid[2].id, factoid[0].id, oldvalue, event.account,
                    event.identity, event.sender['connection'])
            event.addresponse(True)

    @match(r'^(.+?)(?:\s+#(\d+)|\s+/(.+?)/(r?))?\s*(?:~=|=~)\s*([sy](?P<sep>.).+(?P=sep).*(?P=sep)[gir]*)$')
    @authorise(fallthrough=False)
    def modify(self, event, name, number, pattern, is_regex, operation, separator):
        factoids = get_factoid(event.session, name, number, pattern, is_regex, all=True)
        if len(factoids) == 0:
            if pattern:
                event.addresponse(u"I don't know about any %(name)s matching %(pattern)s", {
                    'name': name,
                    'pattern': pattern,
                })
            else:
                event.addresponse(u"I don't know about %s", name)
        elif len(factoids) > 1:
            event.addresponse(u"Pattern matches multiple factoids, please be more specific")
        else:
            factoidadmin = auth_responses(event, u'factoidadmin')
            identities = get_identities(event)
            factoid = factoids[0]

            if factoid[2].identity_id not in identities and not factoidadmin:
                return

            # Not very pythonistic, but escaping is a nightmare.
            parts = [[]]
            pos = 0
            while pos < len(operation):
                char = operation[pos]
                if char == separator:
                    parts.append([])
                elif char == u"\\":
                    if pos < len(operation) - 1:
                        if operation[pos+1] == u"\\":
                            parts[-1].append(u"\\")
                            pos += 1
                        elif operation[pos+1] == separator:
                            parts[-1].append(separator)
                            pos += 1
                        else:
                            parts[-1].append(u"\\")
                    else:
                        parts[-1].append(u"\\")
                else:
                    parts[-1].append(char)
                pos += 1

            parts = [u"".join(x) for x in parts]

            if len(parts) != 4:
                event.addresponse(u"That operation makes no sense. Try something like s/foo/bar/")
                return

            oldvalue = factoid[2].value
            op, search, replace, flags = parts
            flags = flags.lower()
            if op == "s":
                if "r" in flags:
                    if "i" in flags:
                        search += "(?i)"
                    try:
                        factoid[2].value = re.sub(search, replace, oldvalue, int("g" not in flags))
                    except:
                        event.addresponse(u"That operation makes no sense. Try something like s/foo/bar/")
                        return
                else:
                    newvalue = oldvalue.replace(search, replace, "g" in flags and -1 or 1)
                    if newvalue == oldvalue:
                        event.addresponse(u"I couldn't find '%(terms)s' in '%(oldvalue)s'. If that was a proper regular expression, append the 'r' flag", {
                            'terms': search,
                            'oldvalue': oldvalue,
                        })
                        return
                    factoid[2].value = newvalue

            elif op == "y":
                if len(search) != len(replace):
                    event.addresponse(u"That operation makes no sense. The source and destination must be the same length")
                    return
                try:
                    table = dict((ord(x), ord(y)) for x, y in zip(search, replace))
                    factoid[2].value = oldvalue.translate(table)

                except:
                    event.addresponse(u"That operation makes no sense. Try something like y/abcdef/ABCDEF/")
                    return

            event.session.save_or_update(factoid[2])
            event.session.commit()

            log.info(u"Applying '%s' to value %s of factoid %s (%s) by %s/%s (%s)",
                    operation, factoid[2].id, factoid[0].id, oldvalue, event.account, event.identity, event.sender['connection'])

            event.addresponse(True)

greetings = (
        u'lo', u'ello', u'hello', u'hi', u'hi there', u'howdy', u'hey',
        u'heya', u'hiya', u'hola', u'salut', u'bonjour', u'sup', u'wussup',
        u'hoezit', u'wotcha', u'wotcher', u'yo', u'word', u'good day',
        u'wasup', u'wassup', u'howzit', u'howsit', u'buon giorno',
        u'hoe lyk it', u'hoe gaan dit', u'good morning', u'morning',
        u'afternoon', u'evening',
)
static_default = {
    'greet': {
        'matches': [r'\b(' + '|'.join(list(greetings) +
            [g.replace(' ', '') for g in greetings if ' ' in g]) + r')\b'],
        'responses': greetings,
    },
    'reward': {
        'matches': [r'\bbot(\s+|\-)?snack\b'],
        'responses': [u'thanks, $who', u'$who: thankyou!', u':)'],
    },
    'praise': {
        'matches': [r'\bgood(\s+fuckin[\'g]?)?\s+(lad|bo(t|y)|g([ui]|r+)rl)\b', r'\byou\s+(rock|rocks|rewl|rule|are\s+so+\s+co+l)\b'],
        'responses': [u'thanks, $who', u'$who: thankyou!', u':)'],
    },
    'thanks': {
        'matches': [r'\bthank(s|\s*you)\b', r'^\s*ta\s*$', r'^\s*shot\s*$'],
        'responses': [u'no problem, $who', u'$who: my pleasure', u'sure thing, $who', u'no worries, $who', u'$who: np', u'no probs, $who', u'$who: no problemo', u'$who: not at all'],
    },
    'criticism': {
        'matches': [r'\b((kak|bad|st(u|oo)pid|dumb)(\s+fuckin[\'g]?)?\s+(bo(t|y)|g([ui]|r+)rl))|(bot(\s|\-)?s(mack|lap))\b'],
        'responses': [u'*whimper*', u'sorry, $who :(', u':(', u'*cringe*'],
    },
}

class StaticFactoid(Processor):
    priority = 900

    extras = Option('static', 'List of static factoids using regexes', {})

    def setup(self):
        self.factoids = static_default.copy()
        self.factoids.update(self.extras)

    @handler
    def static(self, event):
        for factoid in self.factoids.values():
            for match in factoid['matches']:
                if re.search(match, event.message['stripped'], re.I|re.DOTALL):
                    event.addresponse(_interpolate(choice(factoid['responses']), event),
                            address=False)
                    return

# vi: set et sta sw=4 ts=4:
