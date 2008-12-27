from time import sleep

import ibid
from ibid.plugins import Processor, match, authorise

class Delay(Processor):

    @match('^\s*delay\s+(\d+\.?\d*)\s*$')
    def handler(self, event, delay):
        sleep(float(delay))
        event.addresponse('Done')
        return event

class Protected(Processor):

    @match('^protected$')
    @authorise('protected')
    def handler(self, event):
        event.addresponse('Executing protected command')

# vi: set et sta sw=4 ts=4: