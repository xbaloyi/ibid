import logging

from configobj import ConfigObj, Section
from validate import Validator

def monkeypatch(self, name):
    if self.has_key(name):
        return self[name]
    super(ConfigObj, self).__getattr__(name)

ConfigObj.__getattr__ = monkeypatch

def StaticConfig():
    local = dict(name='local', type='irc', server='localhost', nick='Ibid', channels=['#cocoontest'])
    atrum = dict(type='irc', server='za.atrum.org', nick='Ibid', channels=['#ibid'])
    jabber = dict(type='jabber', server='jabber.org', ssl=True, jid='ibidbot@jabber.org/source', password='ibiddev')
    myjabber = dict(name='jabber', type='jabber', server='gorven.za.net', ssl=True, jid='ibid@gorven.za.net/source', password='z1VdLdxgunupGSju')
    telnet = dict(type='telnet', port=3000)
    timer = dict(type='timer', step=5)
    
    config = dict(name = 'Ibid',
                  sources = dict(local=local, atrum=atrum, jabber=jabber, telnet=telnet, clock=timer),
                  databases = dict(ibid=dict(uri='sqlite:///ibid.db')),
                  processors = ['core.Addressed', 'irc.Actions', 'core.Ignore', 'admin.ListModules', 'admin.LoadModules', 'basic.Greet', 'info.DateTime', 'basic.SayDo', 'test.Delay', 'basic.Complain', 'core.Responses', 'log.Log'],
                  modules = {
                    'core.Addressed': dict(names = ['Ibid', 'bot', 'ant']),
                    'core.Ignore': dict(ignore = ['NickServ']),
                    'ping': dict(type='dbus.Proxy', bus_name='org.ibid.module.Ping', object_path='/org/ibid/module/Ping', pattern='^ping$'),
                    'log.Log': dict(logfile='/tmp/ibid.log')})
    return ConfigObj(config)

def FileConfig(filename):
    configspec = ConfigObj('configspec.ini', list_values=False, encoding='utf-8')
    config = ConfigObj(filename, configspec=configspec, interpolation='Template', encoding='utf-8')
    config.validate(Validator())
    logging.getLogger('core.config').info(u"Loaded configuration from %s", filename)
    return config

# vi: set et sta sw=4 ts=4:
