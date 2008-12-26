from fnmatch import fnmatch
from time import time, sleep
from traceback import print_exc

from sqlalchemy import Column, Integer, Unicode, DateTime, or_
from sqlalchemy.ext.declarative import declarative_base
from twisted.internet import reactor

import ibid

Base = declarative_base()
class Token(Base):
    __tablename__ = 'auth'

    id = Column(Integer, primary_key=True)
    user = Column(Unicode)
    source = Column(Unicode)
    method = Column(Unicode)
    token = Column(Unicode)

    def __init__(self, user, source, method, token):
        self.user = user
        self.source = source
        self.method = method
        self.token = token

class Permission(Base):
    __tablename__ = 'permissions'

    id = Column(Integer, primary_key=True)
    user = Column(Unicode)
    permission = Column(Unicode)

    def __init__(self, user, permission):
        self.user = user
        self.permission = permission

class Auth(object):

    def __init__(self):
        self.cache = {}
        self.irc = {}

    def authenticate(self, event, password=None):

        if 'user' not in event:
            return

        config = ibid.config.auth
        methods = []
        if 'auth' in ibid.config.sources[event.source]:
            methods.extend(ibid.config.sources[event.source]['auth'])
        methods.extend(config['methods'])

        if event.sender in self.cache:
            timestamp = self.cache[event.sender]
            if time() - timestamp < ibid.config.auth['timeout']:
                event.authenticated = True
                return True
            else:
                del self.cache[event.sender]

        for method in methods:
            if hasattr(self, method):
                try:
                    if getattr(self, method)(event, password):
                        self.cache[event.sender] = time()
                        event.authenticated = True
                        return True
                except:
                    print_exc()

        return False

    def authorise(self, event, permission):

        if 'authenticated' not in event:
            return False

        session = ibid.databases.ibid()
        if session.query(Permission).filter_by(user=event.user).filter_by(permission=permission).first():
            return True

        return False

    def implicit(self, event, password = None):
        return True

    def hostmask(self, event, password = None):
        if ibid.config.sources[event.source]['type'] != 'irc':
            return

        session = ibid.databases.ibid()
        for token in session.query(Token).filter_by(method='hostmask').filter_by(user=event.user).filter(or_(Token.source == event.source, Token.source == None)).all():
            if fnmatch(event.sender, token.token):
                return True

    def password(self, event, password):
        if password is None:
            return False

        session = ibid.databases.ibid()
        for token in session.query(Token).filter_by(method='password').filter_by(user=event.user).filter(or_(Token.source == event.source, Token.source == None)).all():
            if token.token == password:
                return True

    def _irc_auth_callback(self, nick, result):
        self.irc[nick] = result

    def nickserv(self, event, password):
        if ibid.config.sources[event.source]['type'] != 'irc':
            return

        reactor.callFromThread(ibid.sources[event.source].proto.authenticate, event.who, self._irc_auth_callback)
        for i in xrange(150):
            if event.who in self.irc:
                break
            sleep(0.1)

        if event.who in self.irc:
            result = self.irc[event.who]
            del self.irc[event.who]
            return result
        
# vi: set et sta sw=4 ts=4: