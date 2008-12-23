import random

from ibid.module import Module
from ibid.decorators import *

class Greet(Module):

    @addressedmessage('^\s*(?:hi|hello|hey)\s*$')
    def process(self, event):
        response = u'Hi %s' % event.user
        event.addresponse(response)
        return event

class SayDo(Module):

    @addressed
    @notprocessed
    @match('^\s*(say|do)\s+(\S+)\s+(.*)\s*$')
    def process(self, event, action, where, what):
        if (event.user != u"Vhata"):
            reply = u"No!  You're not the boss of me!"
            if action.lower() == "say":
                event['responses'].append({'target': where, 'reply': u"Ooooh! %s was trying to make me say '%s'!" % (event.user, what)})
            else:
                event['responses'].append({'target': where, 'reply': u"refuses to do '%s' for '%s'" % (what, event.user), 'action': True})
        else:
            if action.lower() == u"say":
                reply = {'target': where, 'reply': what}
            else:
                reply = {'target': where, 'reply': what, 'action': True}

        event.addresponse(reply)
        return event

complaints = (u'Huh?', u'Sorry...', u'?', u'Excuse me?')

class Complain(Module):

    @addressedmessage()
    def process(self, event):
        reply = complaints[random.randrange(len(complaints))]
        if event.public:
            reply = u'%s: %s' % (event.user, reply)

        event.addresponse(reply)
        return event

# vi: set et sta sw=4 ts=4:
