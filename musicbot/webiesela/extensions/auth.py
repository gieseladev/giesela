import asyncio
import logging
import random
import secrets  # new python 3.6 module
import string
import time

from ..extension import Extension, request
from ..models.webiesela_user import WebieselaUser

log = logging.getLogger(__name__)


class RegistrationToken:
    def __init__(self, connection, token, future, created_at, expires_at):
        self.connection = connection
        self.token = token
        self.future = future
        self.created_at = created_at
        self.expires_at = expires_at

    def __str__(self):
        return "<RegToken {} by {}>".format(self.token, self.connection)

    def to_dict(self):
        return {
            "token": self.token,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }

    def register(self, token):
        self.future.set_result(token)


class Token:
    def __init__(self, webiesela_user, token, created_at, expires_at):
        self.webiesela_user = webiesela_user
        self.token = token
        self.created_at = created_at
        self.expires_at = expires_at

    def __str__(self):
        return "<Token for {}>".format(self.connection)

    @classmethod
    async def from_dict(cls, data):
        webiesela_user = WebieselaUser.from_dict(data.get("webiesela_user"))
        return cls(**data)

    def to_dict(self):
        return {
            "webiesela_user": self.webiesela_user.to_dict(),
            "token": self.token,
            "created_at": self.created_at,
            "expires_at": self.expires_at
        }


class Auth(Extension):
    tokens = {}
    registration_tokens = {}
    expired_tokens = []

    @classmethod
    def setup(cls, config):
        cls.token_lifespan = config.token_lifespan
        cls.registration_token_lifespan = config.registration_token_lifespan
        cls.max_expired_tokens = config.max_expired_tokens
        cls.token_length = config.token_length
        cls.registration_token_length = config.registration_token_length
        cls.tokens_file = config.tokens_file
        cls.expired_tokens_file = config.expired_tokens_file

    @classmethod
    async def load_tokens(cls):
        try:
            with open(cls.tokens_file, "r") as f:
                data = json.load(f)

            for token in data:
                t = await Token.from_dict(token)

                # token not yet expired
                if t.expires_at > time.time():
                    cls.tokens[t.token] = t
                else:
                    log.info("{} expired!".format(t))
                    cls.expired_tokens.insert(0, t.token)
        except FileNotFoundError:
            log.warning("Didn't find a tokens file")

        try:
            with open(cls.expired_tokens_file, "r") as f:
                cls.expired_tokens = f.readlines()[:cls.max_expired_tokens]
        except FileNotFoundError:
            log.warning("Didn't find an expired tokens file")

        log.debug("loaded tokens and expired tokens")

    @classmethod
    def save_tokens(cls):
        try:
            with open(cls.tokens_file, "w+") as f:
                json.dump(f, [t.to_dict() for t in cls.tokens.items()])
        except:
            log.error("Couldn't save tokens")

        try:
            with open(cls.expired_tokens_file, "w+") as f:
                f.writelines(cls.expired_tokens)
        except:
            log.error("Couldn't save expired tokens")

        log.info("saved tokens and expired tokens")

    @classmethod
    def generate_registration_token(cls):
        existing_tokens = cls.registration_tokens.keys()

        while True:
            token = "".join(random.choice(string.ascii_lowercase) for _ in range(cls.registration_token_length))
            if token not in existing_tokens:
                return token

    @classmethod
    async def member_register(cls, member, code):
        if code in cls.registration_tokens:
            registration_token = cls.registration_tokens[code]

            if registration_token.expires_at > time.time():
                pass  # still valid
            else:
                pass
        else:
            return None

    async def on_load(self):
        self.setup(self.bot.config)
        await self.load_tokens()

    @request("authorise", require_registration=False)
    async def authorise(self, connection, token):
        log.debug("{} authorising with token {}".format(connection, token))
        # not already authorised
        if not connection.registered:
            if token in self.tokens:
                t = self.tokens[token]
                connection.register(t)

                log.info("{} authorised".format(connection))

                # TODO response
            else:
                if token in self.expired_tokens:
                    # TODO response
                    log.info("{} tried to authorise with an expired token")
                else:
                    # TODO return error!
                    log.info("{} tried to authorise with unknown token {}".format(connection, token))

    @request("register", require_registration=False)
    async def register(self, message, connection):
        log.info("{} requests registration!".format(connection))

        registered = asyncio.Future()

        token = self.generate_registration_token()
        now = time.time()

        registration_token = RegistrationToken(connection, token, registered, now, now + self.registration_token_lifespan)
        self.registration_tokens[token] = registration_token
        log.debug("generated registration token {}".format(registration_token))

        # TODO send token!

        try:
            result = await asyncio.wait_for(registered, self.registration_token_lifespan)
        except asyncio.TimeoutError:
            log.info("{}'s registration token expired".format(connection))

            # TODO maybe tell them?
            return

    async def on_disconnect(self, connection):
        if connection.registered:
            tokens[connection].expires_at = time.time() + self.token_lifespan
            log.debug("extended {}'s token".format(connection))

            self.save_tokens()
