import re

from caoscommandinfo import *
from caoslexer import *


class ParserState:
    __slots__ = ["p", "tokens"]

    def __init__(self, tokens):
        self.tokens = tokens
        self.p = 0

    def peekmatch(self, newp, toktypes):
        if not isinstance(toktypes, (tuple, list, set)):
            toktypes = (toktypes,)
        if self.tokens[newp][0] not in toktypes:
            raise Exception("Expected %r, got %s\n" % (toktypes, self.tokens[newp][0]))


def caosliteral(value, token):
    return {"type": "Literal", "value": value, "token": token}


def caosvariable(value, token):
    return {"type": "Variable", "value": value, "token": token}


def caoscondition(args, start_token):
    end_token = args[-1].get("end_token") or args[-1].get("token")
    return {
        "type": "Condition",
        "args": args,
        "start_token": start_token,
        "end_token": end_token,
    }


def caosconditionkeyword(value):
    return {"type": "ConditionKeyword", "value": value}


def maybe_eat_whitespace(state):
    ate_whitespace = False
    while state.tokens[state.p][0] in (TOK_COMMENT, TOK_WHITESPACE, TOK_NEWLINE):
        ate_whitespace = True
        state.p += 1
    return ate_whitespace


def eat_whitespace(state):
    if not maybe_eat_whitespace(state):
        raise Exception(
            "Expected whitespace or comment, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )


def parse_condition(state):
    left = parse_value(state)

    eat_whitespace(state)

    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception(
            "Expected comparison, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )
    startp = state.p
    comparison = state.tokens[state.p][1]
    state.p += 1
    if comparison not in ("eq", "lt", "gt", "ne", "=", "<>", ">", ">=", "<", "<="):
        raise Exception("Unknown comparison operator '%s'" % comparison)

    eat_whitespace(state)

    right = parse_value(state)

    ate_whitespace = maybe_eat_whitespace(state)
    if (
        ate_whitespace
        and state.tokens[state.p][0] == TOK_WORD
        and state.tokens[state.p][1] in ("and", "or")
    ):
        combiner = state.tokens[state.p][1]
        state.p += 1
        remainder = parse_condition(state)
        return caoscondition(
            [
                left,
                caosconditionkeyword(comparison),
                right,
                caosconditionkeyword(combiner),
            ]
            + remainder["args"],
            startp,
        )
    else:
        return caoscondition([left, caosconditionkeyword(comparison), right], startp)


def parse_directive(state):
    startp = state.p
    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception(
            "Expected directive name, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )

    directive_name = state.tokens[state.p][1].lower()
    if directive_name == "object_variable":
        state.p += 1
        eat_whitespace(state)
        if state.tokens[state.p][0] != TOK_WORD or state.tokens[state.p][1][0] != "$":
            raise Exception(
                "Expected variable name, got %s %s"
                % (state.tokens[state.p][0], state.tokens[state.p][1])
            )
        args = [state.tokens[state.p][1]]
        state.p += 1
        eat_whitespace(state)
        if state.tokens[state.p][0] != TOK_WORD:
            raise Exception(
                "Expected variable command, got %s %s"
                % (state.tokens[state.p][0], state.tokens[state.p][1])
            )
        args.append(state.tokens[state.p][1])
        state.p += 1

        return {
            "type": "Directive",
            "name": "object_variable",
            "args": args,
            "start_token": startp,
            "end_token": state.p - 1,
        }
    else:
        raise Exception(
            "Expected directive name, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )


def parse_command(state, is_toplevel):
    startp = state.p
    dotcommand = False

    if state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1][0] == "$":
        if state.tokens[state.p + 1][0] != TOK_DOT:
            value = state.tokens[state.p][1]
            state.p += 1
            state.peekmatch(
                state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE)
            )
            return caosvariable(value, startp)
        dotcommand = True
        namespace = ""
        targ = state.tokens[state.p][1].lower()
        state.p += 2
        command = state.tokens[state.p][1].lower()
    elif state.tokens[state.p][0] == TOK_WORD:
        if is_toplevel and state.tokens[state.p][1].lower() in ("object_variable",):
            return parse_directive(state)

        if state.tokens[state.p][1].lower() in COMMAND_NAMESPACES:
            namespace = state.tokens[state.p][1].lower()
            state.p += 1
            eat_whitespace(state)
            command = state.tokens[state.p][1].lower()
        elif state.tokens[state.p + 1][0] == TOK_DOT:
            dotcommand = True
            namespace = ""
            targ = state.tokens[state.p][1].lower()
            # TODO: check it's a valid command
            state.p += 2
            command = state.tokens[state.p][1].lower()
        else:
            namespace = ""
            command = state.tokens[state.p][1].lower()
    else:
        raise Exception(
            "Expected command name, got %s %s"
            % (state.tokens[state.p][0], state.tokens[state.p][1])
        )

    commandnormalized = command
    if re.match(r"(?i)^va\d\d$", command):
        commandnormalized = "vaxx"
    if re.match(r"(?i)^ov\d\d$", command):
        commandnormalized = "ovxx"
    if re.match(r"(?i)^mv\d\d$", command):
        commandnormalized = "mvxx"

    commandinfos = [
        _
        for _ in COMMAND_INFO_C3.values()
        if _.get("namespace", "").lower() == namespace
        and _.get("match", "").lower() == commandnormalized
        and (
            (is_toplevel and _.get("type") == "command")
            or (not is_toplevel and _.get("type") != "command")
        )
    ]
    if not commandinfos:
        raise Exception(
            "Unknown command '%s'" % ((namespace + " " if namespace else "") + command)
        )
    assert len(commandinfos) == 1
    state.p += 1

    args = []
    for _ in commandinfos[0]["arguments"]:
        eat_whitespace(state)
        if _["type"] == "condition":
            args.append(parse_condition(state))
        elif _["type"] == "label":
            if state.tokens[state.p][0] != TOK_WORD:
                raise Exception("Expected label, got %s '%s'\n" % (t[0], t[1]))
            args.append(
                {"type": "Label", "value": state.tokens[state.p][1], "token": state.p}
            )
            state.p += 1
        else:
            args.append(parse_value(state))

    end_token = state.p - 1

    if dotcommand:
        return {
            "type": "DotCommand",
            "targ": targ,
            "command": command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "commandret": commandinfos[0]["type"],
            "args": args,
            "start_token": startp,
            "end_token": end_token,
        }
    else:
        return {
            "type": "Command",
            "name": (namespace + " " if namespace else "") + command,
            "commandtype": ("statement" if is_toplevel else "expression"),
            "args": args,
            "start_token": startp,
            "end_token": end_token,
        }


def parse_toplevel(state):
    maybe_eat_whitespace(state)
    return parse_command(state, True)


def parse_value(state):
    maybe_eat_whitespace(state)

    startp = state.p

    if state.tokens[state.p][0] == TOK_WORD:
        return parse_command(state, False)
    elif state.tokens[state.p][0] == TOK_INTEGER:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return caosliteral(value, startp)
    elif state.tokens[state.p][0] == TOK_STRING:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI, TOK_NEWLINE))
        return caosliteral(value, startp)
    else:
        raise Exception("Unimplemented token type %s" % state.tokens[state.p][0])


def parse(tokens):
    state = ParserState(tokens)
    fst = []
    while True:
        maybe_eat_whitespace(state)
        if state.tokens[state.p][0] == TOK_EOI:
            break
        fst.append(parse_toplevel(state))
    return fst
