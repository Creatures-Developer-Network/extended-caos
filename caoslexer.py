import string
import functools


def peek(s, index):
    if index < len(s):
        return s[index]
    return None


class TokenType:
    __slots__ = ["name"]

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


TOK_CHARACTER = TokenType("TOK_CHARACTER")
TOK_COMMENT = TokenType("TOK_COMMENT")
TOK_INTEGER = TokenType("TOK_INTEGER")
TOK_FLOAT = TokenType("TOK_FLOAT")
TOK_BYTESTRING = TokenType("TOK_BYTESTRING")
TOK_BINARY_LITERAL = TokenType("TOK_BINARY_LITERAL")
TOK_STRING = TokenType("TOK_STRING")
TOK_NEWLINE = TokenType("TOK_NEWLINE")
TOK_WHITESPACE = TokenType("TOK_WHITESPACE")
TOK_WORD = TokenType("TOK_WORD")
TOK_DOT = TokenType("TOK_DOT")
TOK_EOI = TokenType("TOK_EOI")


def tokens_to_string(tokens):
    out = ""
    for t in tokens:
        out += str(t[1])
    return out


def listify(fn):
    def listify_return(fn):
        @functools.wraps(fn)
        def listify_helper(*args, **kw):
            return list(fn(*args, **kw))

        return listify_helper

    return listify_return(fn)


@listify
def lexcaos(s):
    p = 0

    while True:
        basep = p
        if p >= len(s):
            yield (TOK_EOI, "")
            return
        if s[p] == "\n":
            p += 1
            yield (TOK_NEWLINE, "\n")
        elif s[p] == "\r":
            p += 1
            if not (peek(s, p) and peek(s, p) == "\n"):
                raise Exception("Expected '\n' after '\r', got '%s'" % peek(s, p))
            p += 1
            yield (TOK_NEWLINE, "\r\n")
        elif s[p] in (" ", "\t"):
            while peek(s, p) in (" ", "\t"):
                p += 1
            yield (TOK_WHITESPACE, s[basep:p])
        elif s[p] == ".":
            p += 1
            yield (TOK_DOT, ".")
        elif s[p] in string.ascii_letters + "_":
            while (
                peek(s, p)
                and peek(s, p) in string.ascii_letters + string.digits + ":_+"
            ):
                p += 1
            yield (TOK_WORD, s[basep:p])
        elif s[p] == "-":
            p += 1
            if peek(s, p) is None:
                raise Exception("While parsing negative number, got unexpected EOI")
            if peek(s, p) not in string.digits:
                raise Exception(
                    "Expected digit after '-', got '%s' (%02x)"
                    % (peek(s, p), ord(peek(s, p)))
                )
            while peek(s, p) and peek(s, p) in string.digits:
                p += 1
            yield (TOK_INTEGER, int(s[basep:p]))
        elif s[p] in string.digits:
            while peek(s, p) and peek(s, p) in string.digits:
                p += 1
            if peek(s, p) == ".":
                p += 1
                while peek(s, p) and peek(s, p) in string.digits:
                    p += 1
                yield (TOK_FLOAT, s[basep:p])
            else:
                yield (TOK_INTEGER, s[basep:p])
        elif s[p] == "%":
            p += 1
            if not peek(s, p) or not peek(s, p) in string.digits:
                raise Exception(
                    "Expected digit after '%', got %r %s"
                    % (peek(s, p), ord(peek(s, p)))
                )
            while peek(s, p) and peek(s, p) in string.digits:
                p += 1
            yield (TOK_BINARY_LITERAL, s[basep:p])
        elif s[p] == '"':
            p += 1
            while True:
                if p >= len(s):
                    raise Exception("While parsing string, got unexpected EOI")
                if s[p] == '"':
                    p += 1
                    yield (TOK_STRING, s[basep:p])
                    break
                elif s[p] == "\\":
                    p += 2
                else:
                    p += 1
        elif s[p] == "[":
            p += 1
            while True:
                if p >= len(s):
                    raise Exception("While parsing bytestring, got unexpected EOI")
                if s[p] == "]":
                    p += 1
                    yield (TOK_BYTESTRING, s[basep:p])
                    break
                else:
                    p += 1
        elif s[p] == "'":
            p += 1
            if peek(s, p) == "\\":
                p += 1
            p += 1
            if not peek(s, p) or peek(s, p) != "'":
                raise Exception(
                    "While parsing literal character, expected single quote but got %r %x"
                    % (peek(s, p), ord(peek(s, p)))
                )
            p += 1
            yield (TOK_CHARACTER, s[basep:p])
        elif s[p] == "<" and peek(s, p + 1) == ">":
            p += 2
            yield (TOK_WORD, "<>")
        elif s[p] == ">" and peek(s, p + 1) == "=":
            p += 2
            yield (TOK_WORD, ">=")
        elif s[p] == "<" and peek(s, p + 1) == "=":
            p += 2
            yield (TOK_WORD, "<=")
        elif s[p] == "=":
            p += 1
            yield (TOK_WORD, "=")
        elif s[p] == ">":
            p += 1
            yield (TOK_WORD, ">")
        elif s[p] == "<":
            p += 1
            yield (TOK_WORD, "<")
        elif s[p] == "*":
            p += 1
            while peek(s, p) and peek(s, p) not in ("\r", "\n"):
                p += 1
            yield (TOK_COMMENT, s[basep:p])
        elif s[p] == "$":  # nonstandard
            p += 1
            if peek(s, p) is None:
                raise Exception("While parsing dollar var, got unexpected EOI")
            if peek(s, p) not in (string.ascii_letters + string.digits + "_"):
                raise Exception(
                    "Expected variable name after '$', got '%s' (%02x)"
                    % (peek(s, p), ord(peek(s, p)))
                )
            while (
                peek(s, p)
                and peek(s, p) in string.ascii_letters + string.digits + "*:_"
            ):
                p += 1
            yield (TOK_WORD, s[basep:p])
        elif s[p] == ":":  # nonstandard
            p += 1
            if peek(s, p) is None:
                raise Exception("While parsing constant symbol, got unexpected EOI")
            if peek(s, p) not in (string.ascii_letters + string.digits + "_"):
                raise Exception(
                    "Expected constant name after ':', got '%s' (%02x)"
                    % (peek(s, p), ord(peek(s, p)))
                )
            while (
                peek(s, p) and peek(s, p) in string.ascii_letters + string.digits + "_"
            ):
                p += 1
            yield (TOK_WORD, s[basep:p])
        else:
            raise Exception("Unexpected character '%s' (%02x)" % (s[p], ord(s[p])))
