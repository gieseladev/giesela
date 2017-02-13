"""An unofficial library to access the Cleverbot API."""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import collections
import hashlib
from builtins import object  # pylint: disable=redefined-builtin
from builtins import str  # pylint: disable=redefined-builtin

import requests
from future.backports.html import parser
from requests.compat import urlencode

# Only use the instance method `unescape` of entity_parser. (I wish it was a
# static method or public function; it never uses `self` anyway)
entity_parser = parser.HTMLParser()


class Cleverbot(object):
    """Handles a conversation with Cleverbot.
    Example usage:
       >>> from cleverbot import Cleverbot
       >>> cb = Cleverbot()
       >>> cb.ask("Hi. How are you?")
       "I'm good, thanks. How are you?"
    """
    HOST = "www.boibot.com"
    PROTOCOL = "http://"
    RESOURCE = "/webservicemin?uc=777&botapi=see%20www.cleverbot.com%2Fapis&t=18205"
    API_URL = PROTOCOL + HOST + RESOURCE

    headers = ***REMOVED***
        'User-Agent': 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.0)',
        'Accept': 'text/html,application/xhtml+xml,'
                  'application/xml;q=0.9,*/*;q=0.8',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
        'Accept-Language': 'en-us,en;q=0.8,en-us;q=0.5,en;q=0.3',
        'Cache-Control': 'no-cache',
        'Host': HOST,
        'Referer': PROTOCOL + HOST + '/',
        'Pragma': 'no-cache'
    ***REMOVED***

    def __init__(self):
        """ The data that will get passed to Cleverbot's web API """
        self.data = collections.OrderedDict(
            (
                # must be the first pairs
                ('stimulus', ''),
                ('cb_settings_language', ''),
                ('cb_settings_scripting', 'no'),
                ('islearning', 1),  # Never modified
                ('icognoid', 'wsf'),  # Never modified
                ('icognocheck', ''),

                ('start', 'y'),  # Never modified
                ('sessionid', ''),
                ('vText8', ''),
                ('vText7', ''),
                ('vText6', ''),
                ('vText5', ''),
                ('vText4', ''),
                ('vText3', ''),
                ('vText2', ''),
                ('fno', 0),  # Never modified
                ('prevref', ''),
                ('emotionaloutput', ''),  # Never modified
                ('emotionalhistory', ''),  # Never modified
                ('asbotname', ''),  # Never modified
                ('ttsvoice', ''),  # Never modified
                ('typing', ''),  # Never modified
                ('lineref', ''),
                ('sub', 'Say'),  # Never modified
                ('cleanslate', False),  # Never modified
            )
        )

        # the log of our conversation with Cleverbot
        self.conversation = []

        # get the main page to get a cookie (see bug #13)
        self.session = requests.Session()
        self.session.get(Cleverbot.PROTOCOL + Cleverbot.HOST)

    def ask(self, question):
        """Asks Cleverbot a question.
        Maintains message history.
        :param question: The question to ask
        :return Cleverbot's answer
        """

        # Set the current question
        self.data['stimulus'] = question

        # Connect to Cleverbot's API and remember the response
        resp = self._send()

        # Add the current question to the conversation log
        self.conversation.append(question)

        parsed = self._parse(resp.text)

        # Set data as appropriate
        if self.data['sessionid'] != '':
            self.data['sessionid'] = parsed['conversation_id']

        # Add Cleverbot's reply to the conversation log
        self.conversation.append(parsed['answer'])

        return parsed['answer'].encode('latin-1').decode('utf-8')

    def _send(self):
        """POST the user's question and all required information to the
        Cleverbot API
        Cleverbot tries to prevent unauthorized access to its API by
        obfuscating how it generates the 'icognocheck' token. The token is
        currently the md5 checksum of the 10th through 36th characters of the
        encoded data. This may change in the future.
        TODO: Order is not guaranteed when urlencoding dicts. This hasn't been
        a problem yet, but let's look into ordered dicts or tuples instead.
        """
        # Set data as appropriate
        if self.conversation:
            linecount = 1
            for line in reversed(self.conversation):
                linecount += 1
                self.data['vText' + str(linecount)] = line
                if linecount == 8:
                    break

        # Generate the token
        enc_data = urlencode(self.data)
        digest_txt = enc_data[9:35]
        token = hashlib.md5(digest_txt.encode('utf-8')).hexdigest()
        self.data['icognocheck'] = token

        # POST the data to Cleverbot's API and return
        return self.session.post(Cleverbot.API_URL,
                                 data=self.data,
                                 headers=Cleverbot.headers)

    @staticmethod
    def _parse(resp_text):
        """Parses Cleverbot's response"""
        resp_text = entity_parser.unescape(resp_text)

        parsed = [
            item.split('\r') for item in resp_text.split('\r\r\r\r\r\r')[:-1]
        ]

        if parsed[0][1] == 'DENIED':
            raise CleverbotAPIError()

        parsed_dict = ***REMOVED***
            'answer': parsed[0][0],
            'conversation_id': parsed[0][1],
        ***REMOVED***
        try:
            parsed_dict['unknown'] = parsed[1][-1]
        except IndexError:
            parsed_dict['unknown'] = None
        return parsed_dict


class CleverbotAPIError(Exception):
    """Cleverbot returned an error (it probably recognized us as a bot)"""
