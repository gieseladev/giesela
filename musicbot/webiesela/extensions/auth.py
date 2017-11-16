import logging
import time

from ..extension import Extension, request
from ..models.webiesela_user import WebieselaUser

log = logging.getLogger(__name__)


class Token:
    def __init__(self, webiesela_user, token, created_at, expires_at):
        self.webiesela_user = webiesela_user
        self.token = token
        self.created_at = created_at
        self.expires_at = expires_at

    @classmethod
    async def from_dict(cls, data):
        webiesela_user = await WebieselaUser.from_dict(data.get("webiesela_user")).update()
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
    expired_tokens = []

    @classmethod
    def setup(cls, config):
        cls.token_lifespan = config.token_lifespan
        cls.max_expired_tokens = config.max_expired_tokens
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
    async def register(self, connection):
        pass

    async def on_disconnect(self, connection):
        if connection.registered:
            tokens[connection].expires_at = time.time() + self.token_lifespan
            log.debug("extended {}'s token".format(connection))

            self.save_tokens()
