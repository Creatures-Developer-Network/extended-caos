import collections
import json
import re
import string
import sys

from caoslexer import *
from caoscommandinfo import *

def peek(s, index):
    if index < len(s):
        return s[index]
    return None

class ParserState:
    __slots__ = ['p', 'tokens']
    def __init__(self, tokens):
        self.tokens = tokens
        self.p = 0
    
    def peekmatch(self, newp, toktypes):
        if not isinstance(toktypes, (tuple, list, set)):
            toktypes = (toktypes,)
        if self.tokens[newp][0] not in toktypes:
            raise Exception("Expected %r, got %s\n" % (toktypes, self.tokens[newp][0]))

def caosliteral(value, token):
    return collections.OrderedDict([("type", "Literal"), ("value", value), ("token", token)])

def caosvariable(value, token):
    return collections.OrderedDict([("type", "Variable"), ("value", value), ("token", token)])

def caoscondition(children, start_token):
    end_token = children[-1].get("end_token") or children[-1].get("token")
    return collections.OrderedDict([("type", "Condition"), ("children", children), ("start_token", start_token), ("end_token", end_token)])

def caosconditionkeyword(value):
    return collections.OrderedDict([("type", "ConditionKeyword"), ("value", value)])

def maybe_eat_whitespace(state):
    ate_whitespace = False
    while state.tokens[state.p][0] in (TOK_COMMENT, TOK_WHITESPACE):
        ate_whitespace = True
        state.p += 1
    return ate_whitespace
        
def eat_whitespace(state):
    if not maybe_eat_whitespace(state):
        raise Exception("Expected whitespace or comment, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))

def parse_condition(state):
    left = parse_value(state)
    
    eat_whitespace(state)
    
    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception("Expected comparison, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))
    startp = state.p
    comparison = state.tokens[state.p][1]
    state.p += 1
    if comparison not in ('eq', 'lt', 'gt', 'ne', '='):
        raise Exception("Unknown comparison operator '%s'" % comparison)
        
    eat_whitespace(state)
    
    right = parse_value(state)
    
    ate_whitespace = maybe_eat_whitespace(state)
    if ate_whitespace and state.tokens[state.p][0] == TOK_WORD and state.tokens[state.p][1] in ("and", "or"):
        combiner = state.tokens[state.p][1]
        state.p += 1
        remainder = parse_condition(state)
        return caoscondition([left, caosconditionkeyword(comparison), right, caosconditionkeyword(combiner)] + remainder["children"], startp)
    else:
        return caoscondition([left, caosconditionkeyword(comparison), right], startp)

def parse_directive(state):
    startp = state.p
    if state.tokens[state.p][0] != TOK_WORD:
        raise Exception("Expected directive name, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))
    
    directive_name = state.tokens[state.p][1].lower()
    if directive_name == "object_variable":
        state.p += 1
        eat_whitespace(state)
        if state.tokens[state.p][0] != TOK_DOLLARWORD:
            raise Exception("Expected variable name, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))
        args = [state.tokens[state.p][1]]
        state.p += 1
        eat_whitespace(state)
        if state.tokens[state.p][0] != TOK_WORD:
            raise Exception("Expected variable command, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))
        args.append(state.tokens[state.p][1])
        state.p += 1
        
        return {"type": "Directive", "name": "object_variable", "args": args, "start_token": startp, "end_token": state.p - 1}
    else:
        raise Exception("Expected directive name, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))

def parse_command(state, is_toplevel):
    startp = state.p
    dotcommand = False

    if state.tokens[state.p][0] == TOK_WORD:
        if is_toplevel and state.tokens[state.p][1].lower() in ('object_variable',):
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
    elif state.tokens[state.p][0] == TOK_DOLLARWORD:
        if state.tokens[state.p + 1][0] != TOK_DOT:
            value = state.tokens[state.p][1]
            state.p += 1
            state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI))
            return caosvariable(value, startp)
        dotcommand = True
        namespace = ""
        targ = state.tokens[state.p][1].lower()
        state.p += 2
        command = state.tokens[state.p][1].lower()
    else:
        raise Exception("Expected command name, got %s %s" % (state.tokens[state.p][0], state.tokens[state.p][1]))

    commandnormalized = command
    if re.match(r"(?i)^va\d\d$", command):
        commandnormalized = "vaxx"
    if re.match(r"(?i)^ov\d\d$", command):
        commandnormalized = "ovxx"
    if re.match(r"(?i)^mv\d\d$", command):
        commandnormalized = "mvxx"
    
    commandinfos = [
        _ for _ in COMMAND_INFO_C3.values()
        if
            _.get("namespace", "").lower() == namespace
            and _.get("match", "").lower() == commandnormalized
            and ((is_toplevel and _.get("type") == "command") or (not is_toplevel and _.get("type") != "command"))
    ]
    if not commandinfos:
        raise Exception("Unknown command '%s'" % ((namespace + " " if namespace else "") + command))
    assert len(commandinfos) == 1
    state.p += 1

    if commandinfos[0]["arguments"]:
        eat_whitespace(state)
    
    args = []
    for _ in commandinfos[0]["arguments"]:
        if _["type"] == "condition":
            args.append(parse_condition(state))
        else:
            args.append(parse_value(state))
    
    if args:
        end_token = args[-1].get("end_token") or args[-1].get("token")
    else:
        end_token = startp
    
    if dotcommand:
        return collections.OrderedDict([
            ("type", "DotCommand"),
            ("targ", targ),
            ("command", command),
            ("commandtype", ("statement" if is_toplevel else "expression")),
            ("commandret", commandinfos[0]["type"]),
            ("args", args),
            ("start_token", startp),
            ("end_token", end_token)
        ])
    else:
        return collections.OrderedDict([
            ("type", "Command"),
            ("name", (namespace + " " if namespace else "") + command),
            ("commandtype", ("statement" if is_toplevel else "expression")),
            ("args", args),
            ("start_token", startp),
            ("end_token", end_token)
        ])

def parse_toplevel(state):
    maybe_eat_whitespace(state)
    return parse_command(state, True)

def parse_value(state):
    maybe_eat_whitespace(state)
    
    startp = state.p
    
    if state.tokens[state.p][0] in (TOK_WORD, TOK_DOLLARWORD):
        return parse_command(state, False)
    elif state.tokens[state.p][0] == TOK_INTEGER:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI))
        return caosliteral(value, startp)
    elif state.tokens[state.p][0] == TOK_STRING:
        value = state.tokens[state.p][1]
        state.p += 1
        state.peekmatch(state.p, (TOK_WHITESPACE, TOK_COMMENT, TOK_EOI))
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

def visit_worddotcommands(t):
    if t["type"] in ("Command",):
        prefix = []
        newargs = []
        for a in t["args"]:
            more_prefix, arg = visit_worddotcommands(a)
            prefix += more_prefix
            newargs.append(arg)
        
        t = dict(t)
        t["args"] = newargs
        # if prefix:
        #     prefix[0]["preceding_tokens"] = t.get("preceding_tokens", []) + prefix[0].get("preceding_tokens", [])
        if prefix and t["commandtype"] == "statement":
            ws = ""
            for pt in reversed(t.get("preceding_tokens", [])):
                if pt[0] == TOK_WHITESPACE:
                    ws = pt[1] + ws
                else:
                    break
            ws = ws.split("\n")[-1]
            ws = ws.replace("\r", "")
            # print("indent '%s'" % ws)
            for p in prefix:
                p["preceding_tokens"] = p.get("preceding_tokens", []) + [(TOK_WHITESPACE, ws)]
        return (prefix, t)
    elif t["type"] in ("Condition",):
        prefix = []
        newchildren = []
        for a in t["children"]:
            more_prefix, child = visit_worddotcommands(a)
            prefix += more_prefix
            newchildren.append(child)
        
        t = dict(t)
        t["children"] = newchildren
        return (prefix, t)
    elif t["type"] in ("DotCommand",):
        if t["commandtype"] == "expression":
            if t["targ"][0] == "$":
                varname = t["targ"] + "_" + t["command"]
            else:
                varname = "$" + t["targ"] + "_" + t["command"]
            prefix = [
                {"type": "Command", "name": "seta", "args": [
                    {"type": "Variable", "value": "$__saved_targ"},
                    {"type": "Command", "name": "targ", "args": []}
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
                {"type": "Command", "name": "targ", "args": [
                    {"type": "Command", "name": t["targ"], "args": []}
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
                {"type": "Command", "name": "setv", "args": [
                    {"type": "Variable", "value": varname},
                    {"type": "Command", "name": t["command"], "args": t["args"]},
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
                {"type": "Command", "name": "targ", "args": [
                    {"type": "Variable", "value": "$__saved_targ"}
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
            ]
            t = {"type": "Variable", "value": varname}
        elif t["commandtype"] == "statement":
            prefix = [
                {"type": "Command", "name": "seta", "args": [
                    {"type": "Variable", "value": "$__saved_targ"},
                    {"type": "Command", "name": "targ", "args": []}
                ], "preceding_tokens": t.get("preceding_tokens", [])},
                {"type": "Command", "name": "targ", "args": [
                    {"type": "Command", "name": t["targ"], "args": []}
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
                {"type": "Command", "name": t["command"], "args": t["args"],
                   "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
                {"type": "Command", "name": "targ", "args": [
                    {"type": "Variable", "value": "$__saved_targ"}
                ], "preceding_tokens": [("TOK_WHITESPACE", "\n")]},
            ]
            t = {}
        
        return (prefix, t)
    else:
        return ([], t)

def print_node(t):
    if not t:
        return
    if t.get("preceding_tokens"):
        for pt in t["preceding_tokens"]:
            sys.stdout.write(str(pt[1]))
    if t["type"] == "Command":
        sys.stdout.write(t["name"])
        for a in t["args"]:
            sys.stdout.write(" ")
            print_node(a)
    elif t["type"] == "Literal":
        sys.stdout.write(str(t["value"]))
    elif t["type"] == "ConditionKeyword":
        sys.stdout.write(str(t["value"]))
    elif t["type"] == "Variable":
        sys.stdout.write(t["value"])
    elif t["type"] == "Condition":
        for a in t["children"]:
            print_node(a)
            sys.stdout.write(" ")
    elif t["type"] == "DotCommand":
        sys.stdout.write(t["targ"] + "." + t["command"])
        for a in t["args"]:
            sys.stdout.write(" ")
            print_node(a)
    elif t["type"] == "Directive":
        sys.stdout.write(t["name"])
        for a in t["args"]:
            sys.stdout.write(" " + a)
    else:
        raise Exception("unhandled node type %s" % t["type"])

def move_comments_to_own_line(tokens):
    tokens = tokens[:]

    newline_style = '\n'
    for nt in tokens:
        if nt[0] == TOK_NEWLINE:
            newline_style = nt[1]
            break

    i = 0
    last_newline = -1 # hack if we haven't seen a newline yet
    last_indent = ''
    while i < len(tokens):
        t = tokens[i]
        if t[0] == TOK_EOI:
            break
        # bookkeeping for newlines and indentation
        if t[0] == TOK_NEWLINE and i + 1 < len(tokens):
            if tokens[i+1][0] == TOK_WHITESPACE:
                last_indent = tokens[i+1][1]
            else:
                last_indent = ''
        if i == 0 and t[0] == TOK_WHITESPACE:
            last_indent = t[1]
        if t[0] == TOK_NEWLINE:
            last_newline = i
            i += 1
            continue
        # only care about comments
        if t[0] != TOK_COMMENT:
            i += 1
            continue
        # already at beginning of line
        if i == 0 or tokens[i - 1][0] == TOK_NEWLINE:
            i += 1
            continue
        # already on own line
        if tokens[i-1][0] == TOK_WHITESPACE and (i == 1 or tokens[i-2][0] == TOK_NEWLINE):
            i += 1
            continue
        # need to move to previous line
        # delete from here, and delete preceding whitespace
        del tokens[i]
        if i >= 1 and tokens[i-1][0] == TOK_WHITESPACE:
            del tokens[i-1]
        # figure out where to put it
        i = last_newline + 1
        if last_indent:
            tokens.insert(i, (TOK_WHITESPACE, last_indent))
            i += 1
        tokens.insert(i, t)
        tokens.insert(i + 1, (TOK_NEWLINE, newline_style))
        i += 1 # on the newline we added, to do newline bookkeeping
    return tokens

class script:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.vaxx_vars = []
        self.dollar_vars = []

def namedvariables_to_vaxx(tokens):
    tokens = tokens[:]
    scripts = [script(0, 0)]

    # find script extents
    # TODO: expose this elsewhere too?
    for i, t in enumerate(tokens):
        if t[0] == TOK_WORD and t[1].lower() in ("scrp", "rscr"):
            scripts.append(script(i, i))
            continue
        if t[0] == TOK_WORD and re.match(r"(?i)^va\d\d$", t[1]):
            if t[1].lower() not in scripts[-1].vaxx_vars:
                scripts[-1].vaxx_vars.append(t[1].lower())
        if t[0] == TOK_DOLLARWORD:
            if t[1] not in scripts[-1].dollar_vars:
                scripts[-1].dollar_vars.append(t[1])
        scripts[-1].end = i

    # for each script, map named variables to actual variables, then replace the
    # tokens
    for s in scripts:
        var_mapping = {}
        for d in s.dollar_vars:
            possibles = ["va{:02}".format(i) for i in range(100) if "va{:02}".format(i) not in (list(s.vaxx_vars) + var_mapping.values())]
            if not possibles:
                raise Exception("Couldn't allocate variable for '%s'" % d)
            var_mapping[d] = possibles[0]
        for i in range(s.start, s.end):
            if tokens[i][0] == TOK_DOLLARWORD:
                tokens[i] = (TOK_WORD, var_mapping[tokens[i][1]])
    
    return tokens

def extendedcaos_to_caos(s):
    tokens = list(lexcaos(s))    
    tokens = move_comments_to_own_line(tokens)
    tokens = namedvariables_to_vaxx(tokens)
    
    # parse(tokens)
    
    out = ""
    for t in tokens:
        out += str(t[1])
    return out

def main():
    if len(sys.argv) == 2:
        with open(sys.argv[1], 'rb') as f:
            text = f.read()
    elif len(sys.argv) == 1:
        sys.stderr.write("Reading from stdin...")
        text = sys.stdin.read()
    else:
        sys.stderr.write("USAGE: %s [FILE]" % sys.argv[0])
        exit(1)

    tokens = list(lexcaos(text))
    
    fst = parse(tokens)
    print(json.dumps(fst, indent=2))
    
    tokenp = 0
    for toplevel in fst:
        toplevel["preceding_tokens"] = []
        while tokenp < toplevel["start_token"]:
            toplevel["preceding_tokens"].append(tokens[tokenp])
            tokenp += 1
        tokenp = toplevel["end_token"] + 1
    
    object_variables = {}
    i = 0
    while i < len(fst):
        t = fst[i]
        if t["type"] == "Directive" and t["name"] == "object_variable":
            object_variables[t["args"][0]] = t["args"][1]
            
            del fst[i]
        else:
            i += 1
    
    newfst = []
    for toplevel in fst:
        prefix, t = visit_worddotcommands(toplevel)
        newfst += prefix
        newfst.append(t)
    
    # i = 0
    # while i < len(newfst):
    #     t0 = newfst[i]
    #     a0 = peek(t0.get("args", []), 0)
    #     t1 = peek(newfst, i + 1)
    #     if (
    #         t0
    #         and t0["type"] == "Command"
    #         and t0["name"] == "targ"
    #         and a0["type"] == "Variable"
    #         and a0["value"] == "$__saved_targ"
    #         and t1
    #         and t1["type"] == "Command"
    #         and t1["name"] == "seta"
    #         and t1["args"][0]["type"] == "Variable"
    #         and t1["args"][0]["value"] == "$__saved_targ"
    #         and t1["args"][1]["type"] == "Command"
    #         and t1["args"][1]["name"] == "targ"
    #     ):
    #         del newfst[i]
    #     else:
    #         i += 1
    
    for toplevel in newfst:
        print_node(toplevel)
    
    exit()

    scripts = [script(0, 0, set(), set())]

    for i, t in enumerate(tokens):
        if t[0] == TOK_WORD and t[1].lower() in ("scrp", "rscr"):
            scripts.append(script(i, i, set(), set()))
            continue
        if t[0] == TOK_WORD and re.match(r"(?i)^va\d\d$", t[1]):
            scripts[-1].vaxx_vars.add(t[1].lower())
        if t[0] == TOK_DOLLARWORD:
            scripts[-1].dollar_vars.add(t[1])
        scripts[-1].end = i

    for s in scripts:
        var_mapping = {}
        for d in s.dollar_vars:
            possibles = ["va{:02}".format(i) for i in range(100) if "va{:02}".format(i) not in (list(s.vaxx_vars) + var_mapping.values())]
            if not possibles:
                raise Exception("Couldn't allocate variable for '%s'" % d)
            var_mapping[d] = possibles[0]
        
        print_mapped_line = False
        line = []
        for t in tokens[s.start:s.end]:
            if (t[0] == TOK_WHITESPACE and "\n" in t[1]) or (t[0] == TOK_COMMENT):
                if print_mapped_line:
                    sys.stdout.write(" * ")
                    for lt in line:
                        sys.stdout.write(str(lt[1]))
                    print_mapped_line = False
                line = []
            else:
                line.append(t)
            if t[0] == TOK_DOLLARWORD:
                print_mapped_line = True
                sys.stdout.write(var_mapping[t[1]])
            else:
                sys.stdout.write(str(t[1]))

if __name__ == '__main__':
    main()