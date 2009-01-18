import logging
import logging.config

import sys
sys.path.append("./lib/wokkel.egg")
sys.path.insert(0, './lib')

import twisted.python.log

import ibid.core
from ibid.config import FileConfig

sources = {}
config = {}
dispatcher = None
processors = []
reloader = None
databases = None
auth = None
service = None

def twisted_log(eventDict):
    log = logging.getLogger('twisted')
    if 'failure' in eventDict:
        log.error(eventDict['failure'].getTrackback())
    elif 'warning' in eventDict:
        log.warning(eventDict['warning'])
    else:
        log.debug(' '.join([str(m) for m in eventDict['message']]))

def setup(service=None):
    # Undo Twisted logging's redirection of stdout and stderr
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    logging.basicConfig(level=logging.INFO)

    # Get Twisted to log to Python logging
    for observer in twisted.python.log.theLogPublisher.observers:
        twisted.python.log.removeObserver(observer)
    twisted.python.log.addObserver(twisted_log)

    service = service
    ibid.config = FileConfig("ibid.ini")
    ibid.config.merge(FileConfig("local.ini"))

    if 'logging' in ibid.config:
        logging.getLogger('core').info(u'Loading log configuration from %s', ibid.config['logging'])
        logging.config.fileConfig(ibid.config['logging'])

    ibid.reload_reloader()
    ibid.reloader.reload_dispatcher()
    ibid.reloader.reload_databases()
    ibid.reloader.load_processors()
    ibid.reloader.load_sources(service)
    ibid.reloader.reload_auth()

def reload_reloader():
    try:
        reload(ibid.core)
        new_reloader = ibid.core.Reloader()
        ibid.reloader = new_reloader
        return True
    except:
        logging.getLogger('core').exception(u"Exception occured while reloading Reloader")
        return False

# vi: set et sta sw=4 ts=4:
