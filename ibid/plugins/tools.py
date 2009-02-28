import re
from random import random, randint
from subprocess import Popen, PIPE

from ibid.plugins import Processor, match
from ibid.config import Option

help = {}

help['retest'] = 'Checks whether a regular expression matches a given string.'
class ReTest(Processor):
    """does <pattern> match <string>"""
    feature = 'retest'

    @match('^does\s+(.+?)\s+match\s+(.+?)$')
    def retest(self, event, regex, string):
        event.addresponse(re.search(regex, string) and 'Yes' or 'No')

help['random'] = 'Generates random numbers.'
class Random(Processor):
    """random [ <max> | <min> <max> ]"""
    feature = 'random'

    @match('^rand(?:om)?(?:\s+(\d+)(?:\s+(\d+))?)?$')
    def random(self, event, begin, end):
        if not begin and not end:
            event.addresponse(str(random()))
        else:
            begin = int(begin)
            end = end and int(end) or 0
            event.addresponse(str(randint(min(begin,end), max(begin,end))))

help['units'] = 'Converts values between various units.'
class Units(Processor):
    """convert [<value>] <unit> to <unit>"""
    feature = 'units'
    priority = 10

    units = Option('units', 'Path to units executable', 'units')

    temp_scale_names = {
        'fahrenheit': 'tempF',
        'f': 'tempF',
        'celsius': 'tempC',
        'celcius': 'tempC',
        'c': 'tempC',
        'kelvin': 'tempK',
        'k': 'tempK',
        'rankine': 'tempR',
        'r': 'tempR',
    }

    temp_function_names = set(temp_scale_names.values())

    def format_temperature(self, unit):
        "Return the unit, and convert to 'tempX' format if a known temperature scale"

        lunit = unit.lower()
        if lunit in self.temp_scale_names:
            unit = self.temp_scale_names[lunit]
        elif lunit.startswith("deg") and " " in lunit and lunit.split(None, 1)[1] in self.temp_scale_names:
            unit = self.temp_scale_names[lunit.split(None, 1)[1]]
        return unit

    @match(r'^convert\s+(-?[0-9.]+)?\s*(.+)\s+to\s+(.+)$')
    def convert(self, event, value, frm, to):

        # We have to special-case temperatures because GNU units uses function notation
        # for direct temperature conversions
        if self.format_temperature(frm) in self.temp_function_names \
                and self.format_temperature(to) in self.temp_function_names:
            frm = self.format_temperature(frm)
            to = self.format_temperature(to)

        if value is not None:
            if frm in self.temp_function_names:
                frm = "%s(%s)" % (frm, value)
            else:
                frm = '%s %s' % (value, frm)

        units = Popen([self.units, '--verbose', '--', frm, to], stdout=PIPE, stderr=PIPE)
        output, error = units.communicate()
        code = units.wait()

        result = output.splitlines()[0].strip()

        if code == 0:
            event.addresponse(result)
        elif code == 1:
            if result == "conformability error":
                event.addresponse(u"I don't think %s can be converted to %s." % (frm, to))
            elif result.startswith("conformability error"):
                event.addresponse(u"I don't think %s can be converted to %s: %s" % (frm, to, result.split(":", 1)[1]))
            else:
                event.addresponse(u"I can't do that: %s" % result)

# vi: set et sta sw=4 ts=4:
