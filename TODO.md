TODO:
- Macros as expressions (not just statements)
- Proper short-circuit semantics on doifs/elifs when using explicit targ (don't execute parts of condition until previous parts have succeeded, and definitely don't execute parts of elif until the doif condition fails)
- Teach parser about macros
- Better way to make sure macro variables don't override user variables (not just prefixing with macro_MacroName)
- reduce total number of variables used, especially when there's a lot of explicit targ
- "=" for assigning to variables
- support NAME variables in object variables