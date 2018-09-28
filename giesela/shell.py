import abc
import asyncio
import contextlib
import functools
import logging
import pprint
import sys
from asyncio import subprocess
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Type, Union

import aiohttp
import js2py
from discord.ext.commands import Context

from .bot import Giesela

log = logging.getLogger(__name__)


class _EmptyResult:
    def __hash__(self) -> int:
        return hash(None)

    def __bool__(self) -> bool:
        return False


EmptyResult = _EmptyResult()


class ShellException(Exception):
    def __init__(self, msg: str, original: BaseException = None, **kwargs) -> None:
        self.msg = msg
        self.original = original
        self.data = kwargs

    def __repr__(self) -> str:
        return f"{type(self).__name__}: {self.msg} | {self.data!r}"

    def __str__(self) -> str:
        if self.original:
            return str(self.original)
        else:
            return repr(self)


class InterpreterUnavailable(ShellException, OSError):
    pass


class UploadAdapter(metaclass=abc.ABCMeta):
    NAME: str

    def __init__(self, **kwargs) -> None:
        pass

    @classmethod
    def filter_history(cls, history: List["ShellLine"], *, skip_errors: bool = True) -> List["ShellLine"]:
        if skip_errors:
            history = [line for line in history if not line.error]
        return history

    def prepare_text(self, history: List["ShellLine"], **kwargs):
        history = self.filter_history(history, **kwargs)
        return "\n".join(map(str, history))

    @abc.abstractmethod
    async def upload(self, history: List["ShellLine"], *, skip_errors: bool = True) -> str:
        pass


class HastebinUpload(UploadAdapter):
    NAME = "Hastebin"

    HASTEBIN_URL = "https://hastebin.com"
    HASTEBIN_UPLOAD = f"{HASTEBIN_URL}/documents"
    HASTEBIN_DOCUMENT = f"{HASTEBIN_URL}/{{key}}"

    _aiosession: Optional[aiohttp.ClientSession]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        ctx = kwargs.get("ctx")
        if ctx:
            aiosession = getattr(ctx.bot, "aiosession", None)
        else:
            aiosession = None
        self._aiosession = aiosession

    @contextlib.asynccontextmanager
    async def get_aiosession(self) -> aiohttp.ClientSession:
        if self._aiosession:
            yield self._aiosession
        else:
            with aiohttp.ClientSession() as session:
                yield session

    async def upload(self, history: List["ShellLine"], *, skip_errors: bool = True) -> str:
        data = self.prepare_text(history, skip_errors=skip_errors)
        async with self.get_aiosession() as aiosession:
            async with aiosession.post(self.HASTEBIN_UPLOAD, data=data.encode()) as resp:
                resp_data = await resp.json()
        url = self.HASTEBIN_DOCUMENT.format(key=resp_data["key"])
        return url


class ShellInterpreter(metaclass=abc.ABCMeta):
    language_name: str
    highlight_language = ""

    variables: Dict[str, Any]

    def __init__(self, **kwargs) -> None:
        self.variables = {}
        self.variables.update(kwargs)

    def __repr__(self) -> str:
        return f"{type(self).__name__}"

    @property
    def context(self) -> Dict[str, Any]:
        return self.variables

    @abc.abstractmethod
    async def run(self, code: str) -> Any:
        pass

    def ensure_available(self) -> None:
        pass

    async def stop(self):
        pass


INTERPRETERS: Dict[str, Type[ShellInterpreter]] = {}


def register_interpreter(*aliases: str) -> Callable[[Type[ShellInterpreter]], Type[ShellInterpreter]]:
    def decorator(cls: Type[ShellInterpreter]) -> Type[ShellInterpreter]:
        for alias in aliases:
            INTERPRETERS[alias.lower()] = cls
        return cls

    return decorator


@register_interpreter("sh", "bash", "cmd", "os")
class BashInterpreter(ShellInterpreter):
    language_name = "Bash"
    highlight_language = "bash"

    process: Optional[subprocess.Process]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.process = None

    def ensure_available(self) -> None:
        if sys.platform == "win32":
            raise InterpreterUnavailable("Unavailable on Windows")
        raise InterpreterUnavailable("Too unstable right now, sorry")

    async def get_process(self) -> subprocess.Process:
        if not self.process:
            executable = "/bin/bash"
            self.process = await asyncio.create_subprocess_exec(executable, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.process

    @classmethod
    async def read_out(cls, process: subprocess.Process) -> str:
        print("reading")
        stderr = await process.stderr.readline()
        stderr = stderr.decode().strip()
        print("got", stderr)
        if stderr:
            return stderr

        print("reading stdout")
        stdout = await process.stdout.read()
        return stdout.decode().strip()

    async def run(self, code: str) -> Any:
        process = await self.get_process()
        process.stdin.write(code.encode())
        await process.stdin.drain()
        process.stdin.close()

        out = await self.read_out(process)
        print("out:", out)

        return out

    async def stop(self):
        if self.process:
            await self.process.terminate()


# noinspection PyAbstractClass
class GieselaInterpreter(ShellInterpreter, metaclass=abc.ABCMeta):
    ctx: Context
    bot: Giesela

    def __init__(self, *, ctx: Context, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ctx = ctx
        self.bot = ctx.bot

    @property
    def context(self) -> Dict[str, Any]:
        context = super().context
        context.update(ctx=self.ctx, bot=self.bot, interpreter=self)

        cogs = self.bot.cogs
        context.update(cogs)
        return context


@register_interpreter("js", "javascript")
class JavascriptInterpreter(GieselaInterpreter):
    language_name = "Javascript"
    highlight_language = "js"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.eval_js = js2py.EvalJs(super().context)

    @property
    def context(self) -> Dict[str, Any]:
        return self.eval_js.__dict__

    async def run(self, code: str) -> Any:
        result = self.eval_js.eval(code)
        if result is None:
            result = EmptyResult
        return result


@register_interpreter("py", "python")
class PythonInterpreter(GieselaInterpreter):
    language_name = "Python"
    highlight_language = "py"

    WRAP_TEMPLATE = "async def func({{args}}):\n" \
                    "{code}"

    @classmethod
    def wrap_code(cls, code: str, return_last: bool = True) -> str:
        if return_last:
            *lines, last_line = code.splitlines()
        else:
            lines = code.splitlines()
            last_line = "None"

        last_line = f"return {last_line}, locals()"

        code = "\n".join(f"\t{line}" for line in lines)
        code = prepare_code(f"{code}\n\t{last_line}")

        return cls.WRAP_TEMPLATE.format(code=code)

    @classmethod
    def _compile_wrap(cls, code: str, context: Dict[str, Any]) -> Optional[Callable]:
        args = list(context)
        # TODO escape {} in code
        code = code.format(args=",".join(args))
        try:
            _scope: Dict[str, Any] = {}
            exec(code, context.copy(), _scope)
        except SyntaxError:
            return None
        else:
            func = _scope.get("func")
            return functools.partial(func, **context)

    @classmethod
    def get_compiled(cls, code: str, context: Dict[str, Any]) -> Callable:
        with_return = cls.wrap_code(code)

        func = cls._compile_wrap(with_return, context)
        if func:
            func._returns = True
            return func

        no_return = cls.wrap_code(code, return_last=False)
        func = cls._compile_wrap(no_return, context)

        if func:
            func._returns = False
            return func

        try:
            compile(code, "<GieselaShell>", "exec")
        except SyntaxError as e:
            raise ShellException("Syntax error", original=e, code=code)

        raise ShellException("Couldn't compile line")

    async def run(self, code: str) -> Any:
        func = self.get_compiled(code, self.context)
        result, local_vars = await func()

        self.variables.update(local_vars)

        if not getattr(func, "_returns", True) and result is None:
            result = EmptyResult

        return result


def is_one_line(s: str) -> bool:
    return s.splitlines()[0] == s


class ShellLine(NamedTuple):
    interpreter: ShellInterpreter
    code: str
    result: Any = EmptyResult
    error: Optional[ShellException] = None

    def __str__(self) -> str:
        s = f">>> {self.code}"
        result = self.result_str
        if result:
            s = f"{s}\n{result}"

        return s

    @property
    def oneliner(self) -> bool:
        return is_one_line(self.code)

    @property
    def result_str(self) -> Optional[str]:
        if self.error:
            return str(self.error)
        if self.result is None or self.result is EmptyResult:
            return None
        return str(self.result)


def prepare_code(code: str) -> str:
    return code.strip(" \n")


class GieselaShell:
    interpreter: ShellInterpreter
    upload_adapter: UploadAdapter
    history: List[ShellLine]

    def __init__(self, interpreter: ShellInterpreter, upload_adapter: UploadAdapter) -> None:
        interpreter.ensure_available()
        self.interpreter = interpreter
        self.upload_adapter = upload_adapter

        self.history = []

    @classmethod
    def python(cls, upload_adapter: Type[UploadAdapter] = HastebinUpload, **kwargs) -> "GieselaShell":
        return cls.find_interpreter("python", upload_adapter, **kwargs)

    @classmethod
    def find_interpreter(cls, alias: str, upload_adapter_type: Type[UploadAdapter] = HastebinUpload, **kwargs) -> Optional["GieselaShell"]:
        interpreter_cls = INTERPRETERS.get(alias.lower())
        if not interpreter_cls:
            return None
        interpreter = interpreter_cls(**kwargs)

        if not isinstance(upload_adapter_type, UploadAdapter):
            upload_adapter = upload_adapter_type(**kwargs)
        else:
            upload_adapter = upload_adapter_type

        return cls(interpreter, upload_adapter)

    def prettify(self, line: Union[int, ShellLine] = None, **kwargs) -> ShellLine:
        if isinstance(line, int):
            line = self.history[line]
        elif line is None:
            line = self.history[-1]

        obj_of_interest = line.error or line.result

        if obj_of_interest:
            error = None
            _kwargs = dict(depth=2)
            _kwargs.update(kwargs)
            pretty: Optional[str] = pprint.pformat(obj_of_interest, **_kwargs)
        else:
            error = ShellException("Nothing to prettify!")
            pretty = None

        shell_line = ShellLine(line.interpreter, "PRETTIFY", pretty, error)
        self.history.append(shell_line)
        return shell_line

    async def run(self, code: str, *, timeout: float = None) -> ShellLine:
        code = prepare_code(code)
        result = None
        error = None

        coro = self.interpreter.run(code)

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            error = ShellException("Timed out!")
        except ShellException as e:
            error = e
        except BaseException as e:
            # TODO don't even log these...
            log.exception("Something unexpected happened", extra=dict(report=False))
            error = ShellException("An unhandled error occurred", original=e)

        line = ShellLine(self.interpreter, code, result, error)
        self.history.append(line)
        return line

    async def stop(self):
        await self.interpreter.stop()

    async def upload(self, *, skip_errors=True) -> str:
        return await self.upload_adapter.upload(self.history, skip_errors=skip_errors)
