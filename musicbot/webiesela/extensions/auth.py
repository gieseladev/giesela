"""The module which handles the registration/authorisation of a Webiesela user."""

import asyncio
import json
import logging
import random
import secrets  # new python 3.6 module
import string
import time

from ..extension import Extension, request
from ..models.exceptions import TokenExpired, TokenUnknown
from ..models.webiesela_user import WebieselaUser

log = logging.getLogger(__name__)


class RegistrationToken:
    """Class representing a token which the user must use to register."""

    def __init__(self, connection, token, future, created_at, expires_at):
        """Create a new such token."""
        self.connection = connection
        self.token = token
        self.future = future
        self.created_at = created_at
        self.expires_at = expires_at

    def __str__(self):
        """Printable version."""
        return "<RegToken {} by {}>".format(self.token, self.connection)

    def to_dict(self):
        """Serialise data to a dict."""
        return {
            "token": self.token,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }

    def register(self, token):
        """Call when user has registered."""
        self.future.set_result(token)


class Token:
    """Represent the authorisation bound to a token and a user which allows said user to interact with Giesela."""

    def __init__(self, webiesela_user, token, created_at, expires_at):
        """Instantiate such a token."""
        self.webiesela_user = webiesela_user
        self.token = token
        self.created_at = created_at
        self.expires_at = expires_at

    def __str__(self):
        """Representation of a token."""
        return "<Token for {}>".format(self.connection)

    @classmethod
    def from_dict(cls, data):
        """Create instance from serialised dict."""
        data["webiesela_user"] = WebieselaUser.from_dict(data.get("webiesela_user"))
        return cls(**data)

    @classmethod
    def create(cls, member, token_length, lifespan):
        """Create a new token for a member."""
        webiesela_user = WebieselaUser.from_member(member)
        token = secrets.token_hex(token_length)
        now = time.time()

        return cls(webiesela_user, token, now, now + lifespan)

    def to_dict(self):
        """Serialise token to a dict."""
        return {
            "webiesela_user": self.webiesela_user.to_dict(),
            "token": self.token,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }


class Auth(Extension):
    """Extension for authorisation."""

    tokens = {}
    registration_tokens = {}
    expired_tokens = []

    @classmethod
    def setup(cls, config):
        """Get needed values from the config."""
        cls.token_lifespan = config.token_lifespan
        cls.registration_token_lifespan = config.registration_token_lifespan
        cls.max_expired_tokens = config.max_expired_tokens
        cls.token_length = config.token_length
        cls.registration_token_length = config.registration_token_length
        cls.tokens_file = config.tokens_file
        cls.expired_tokens_file = config.expired_tokens_file

    @classmethod
    async def load_tokens(cls):
        """Load all the tokens from file."""
        try:
            with open(cls.tokens_file, "r") as f:
                data = json.load(f)

            for token in data:
                t = Token.from_dict(token)

                # token not yet expired
                if t.expires_at > time.time():
                    cls.tokens[t.token] = t
                else:
                    log.info("{} expired!".format(t))
                    cls.expired_tokens.insert(0, t.token)
        except json.JSONDecodeError:
            log.warning("Couldn't parse tokens file")
        except FileNotFoundError:
            log.warning("Didn't find a tokens file")
        except Exception:
            log.error("Couldn't load tokens file", exc_info=True)

        try:
            with open(cls.expired_tokens_file, "r") as f:
                cls.expired_tokens = f.readlines()[:cls.max_expired_tokens]
        except FileNotFoundError:
            log.warning("Didn't find an expired tokens file")

        log.debug("loaded tokens and expired tokens")

    @classmethod
    def save_tokens(cls):
        """Save tokens to file."""
        try:
            with open(cls.tokens_file, "w+") as f:
                json.dump([t.to_dict() for t in cls.tokens.values()], f, indent=2)
        except Exception:
            log.error("Couldn't save tokens")

        try:
            with open(cls.expired_tokens_file, "w+") as f:
                f.writelines(cls.expired_tokens)
        except Exception:
            log.error("Couldn't save expired tokens")

        log.info("saved tokens and expired tokens")

    @classmethod
    def generate_registration_token(cls):
        """Generate new registration token which is unique."""
        existing_tokens = cls.registration_tokens.keys()

        while True:
            token = "".join(random.choice(string.ascii_lowercase) for _ in range(cls.registration_token_length))
            if token not in existing_tokens:
                return token

    @classmethod
    async def member_register(cls, member, code):
        """Bind member to a registration token."""
        if code in cls.registration_tokens:
            registration_token = cls.registration_tokens[code]

            if registration_token.expires_at > time.time():
                t = Token.create(member, cls.token_length, cls.token_lifespan)
                registration_token.register(t)
                return True
            else:
                log.debug("{} is already expired".format(registration_token))
                return False
        else:
            log.debug("{} isn't a token".format(code))
            return None

    async def on_load(self):
        """When ready, load all the tokens."""
        cls = type(self)

        cls.setup(self.bot.config)
        await cls.load_tokens()

    @request("authorise", require_auth=False)
    async def authorise(self, connection, message, token):
        """Endpoint to authorise with a token."""
        cls = type(self)

        log.debug("{} authorising with token {}".format(connection, token))
        # not already authorised
        if not connection.registered:
            if token in cls.tokens:
                t = cls.tokens[token]

                if time.time() > t.expires_at:
                    log.info("{} expired!".format(t))
                    cls.tokens.pop(token)
                    cls.expired_tokens.insert(0, t.token)

                    log.info("{} tried to authorise with an expired token")
                    raise TokenExpired("This token has expired")

                connection.register(t)

                log.info("{} authorised".format(connection))

                await message.answer({"token": t.to_dict()}, success=True)
            else:
                if token in cls.expired_tokens:
                    log.info("{} tried to authorise with an expired token")
                    raise TokenExpired("This token has expired")
                else:
                    log.info("{} tried to authorise with unknown token {}".format(connection, token))
                    raise TokenUnknown("This token is unknown")

    @request("register", require_auth=False)
    async def register(self, connection, message):
        """Endpoint to request registration.

        Generates a new registration token and sends it over to Webiesela.
        """
        cls = type(self)

        log.info("{} requests registration!".format(connection))

        registered = asyncio.Future()

        token = cls.generate_registration_token()
        now = time.time()

        registration_token = RegistrationToken(connection, token, registered, now, now + cls.registration_token_lifespan)
        cls.registration_tokens[token] = registration_token
        log.debug("generated registration token {}".format(registration_token))

        await message.answer({"registration_token": registration_token.to_dict()})

        try:
            token = await asyncio.wait_for(registered, cls.registration_token_lifespan)

            cls.tokens[token.token] = token
            cls.save_tokens()

            # TODO also authorise

            await message.answer({"token": token.to_dict()})
        except asyncio.TimeoutError:
            log.info("{}'s registration token expired".format(connection))

            raise TokenExpired("The registration token has expired")
        finally:
            cls.registration_tokens.pop(registration_token.token)

    async def on_disconnect(self, connection):
        """Extend token's lifespan when disconnecting."""
        cls = type(self)

        if connection.registered:
            connection.token.expires_at = time.time() + cls.token_lifespan
            log.debug("extended {}'s token".format(connection))

            cls.save_tokens()
