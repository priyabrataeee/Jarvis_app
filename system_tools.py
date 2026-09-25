"""
Jarvis V2 — System Tools
Runs PowerShell commands on the local machine. Commands are classified as
read-only (run immediately) or changing (need spoken confirmation) by an
allowlist, never by the LLM: anything not clearly read-only needs a "yes".
"""

import asyncio
import os
import re
import subprocess

# Cmdlet verbs that only read or format data
SAFE_VERBS = {
    "get", "test", "measure", "select", "where", "sort", "format", "group",
    "compare", "resolve", "split", "join", "convertto", "convertfrom",
}
# Specific cmdlets allowed despite their verb
SAFE_CMDLETS = {"out-string", "write-output"}
# Open an app, file or folder, like double-clicking it
LAUNCHERS = {"start-process", "invoke-item", "ii", "explorer"}
# Read-only aliases and native programs
SAFE_COMMANDS = {
    "ls", "dir", "gci", "gc", "cat", "type", "pwd", "gi", "gp", "gps", "ps",
    "select", "where", "sort", "ft", "fl", "measure", "echo",
    "whoami", "hostname", "systeminfo", "tasklist", "ipconfig",
}
# Native programs that are read-only only with these arguments
NATIVE_ALLOWED_ARGS = {"ipconfig": {"", "/all"}}
# Opening these runs code, so launching them needs confirmation
SCRIPT_EXT = re.compile(r"\.(bat|cmd|ps1|vbs|vbe|js|jse|wsf|wsh|msi|reg|scr|hta|com|pif)\b", re.I)
INTERPRETERS = {"powershell", "pwsh", "cmd", "wscript", "cscript", "mshta", "rundll32",
                "regsvr32", "reg", "regedit", "bash", "wsl", "python", "py", "node", "msiexec"}

MAX_OUTPUT = 3000
TIMEOUT_SECONDS = 30


def _strip_strings(cmd: str) -> str:
    """Blank out quoted text so paths and search terms aren't mistaken for commands."""
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", cmd)


# Keys allowed in calculated properties: Select-Object @{Name='GB'; Expression={ $_.Size / 1GB }}
_HASHTABLE_KEY = re.compile(r"(?i)\b(name|n|label|l|expression|e)\s*=")


_INNERMOST_BLOCK = re.compile(r"\{([^{}]*)\}")
_TYPE_CAST = re.compile(r"\[[A-Za-z][\w.]*\]")  # [int], [math]; harmless alone, and :: / .Method() are blocked


def _braces_are_safe(stripped: str) -> bool:
    """Script blocks may only hold filters like { $_.Length -gt 1MB }: no bare words inside.
    Nested blocks are checked level by level, innermost first."""
    if stripped.count("{") != stripped.count("}"):
        return False
    while _INNERMOST_BLOCK.search(stripped):
        for block in _INNERMOST_BLOCK.findall(stripped):
            block = _TYPE_CAST.sub(" ", _HASHTABLE_KEY.sub("=", block))
            # A bare word is one not preceded by $ (variable), . (property) or - (operator)
            if re.search(r"(?<![\w$.\-])[A-Za-z_]\w*", block):
                return False
        stripped = _INNERMOST_BLOCK.sub(" 0 ", stripped)  # checked; collapse and look at the enclosing level
    return True


def _collapse_blocks(stripped: str) -> str:
    """Replace (already checked) script blocks with a placeholder so their ; don't split statements."""
    while _INNERMOST_BLOCK.search(stripped):
        stripped = _INNERMOST_BLOCK.sub(" 0 ", stripped)
    return stripped


def is_read_only(cmd: str) -> bool:
    """True only if every part of the command is on the read-only allowlist."""
    stripped = _strip_strings(cmd)

    # > writes files, :: calls .NET methods, $( and @( run subexpressions, ` escapes, & and . invoke code
    if re.search(r">|::|`|\$\(|@\(", stripped):
        return False
    # .Method() calls can change things, e.g. (Get-Item x).Delete()
    if re.search(r"\.\w+\s*\(", stripped):
        return False
    if re.search(r"(^|[;|(]\s*)[&.]\s", stripped):
        return False
    if not _braces_are_safe(stripped):
        return False

    # Every Verb-Noun word anywhere must use a read-only verb
    for m in re.finditer(r"(?<![\w-])([A-Za-z]+)-([A-Za-z]+)\b", stripped):
        if m.group(0).lower() not in SAFE_CMDLETS and m.group(1).lower() not in SAFE_VERBS \
                and m.group(0).lower() not in LAUNCHERS:
            return False

    # The first word of each statement and pipeline stage must be an allowed command.
    # Script block contents were fully checked above, so collapse them before splitting.
    for segment in re.split(r"[;|\n]", _collapse_blocks(stripped)):
        tokens = segment.strip().lstrip("(").split()
        if not tokens:
            continue
        if len(tokens) == 1 and re.fullmatch(r"\$\w+(\.\w+)*\)?(\.\w+)*", tokens[0]):
            continue  # just reading a variable or property, e.g. $files.Count
        if tokens[0].startswith("$"):
            # Only simple assignments: $x = <allowed command>
            if len(tokens) < 3 or tokens[1] != "=":
                return False
            tokens = tokens[2:]
        head = tokens[0].lower().removesuffix(".exe")
        args = [t.lower() for t in tokens[1:]]

        if head in LAUNCHERS:
            # Just a target: no -ArgumentList, -Verb RunAs etc., and not a script
            if any(a.startswith("-") and a not in ("-filepath", "-path") for a in args):
                return False
            if SCRIPT_EXT.search(cmd):
                return False
            # Check the original text: quoted paths are blanked out in `stripped`
            if re.search(r"\b(" + "|".join(INTERPRETERS) + r")(\.exe)?\b", cmd, re.I):
                return False
            # Opening a URL can send data off the machine (e.g. file contents in a query string)
            # Schemes are 2+ letters (https:, mailto:), unlike drive letters (C:); $env: is a variable
            if re.search(r"(?<![\w$])[a-z][\w+.-]+:", cmd, re.I):
                return False
        elif head in NATIVE_ALLOWED_ARGS:
            if " ".join(args) not in NATIVE_ALLOWED_ARGS[head]:
                return False
        elif head in SAFE_COMMANDS or head in SAFE_CMDLETS:
            pass
        elif "-" in head and head.split("-")[0] in SAFE_VERBS:
            pass
        else:
            return False
    return True


# Cmdlets that act on an item that must already exist, followed by a quoted absolute path
_EXISTING_ITEM = re.compile(
    r"\b(?:Rename-Item|Remove-Item|Move-Item|Copy-Item|Invoke-Item|Start-Process|Get-Content)\b[^|;]*?'([A-Za-z]:\\[^']*)'",
    re.I)


def missing_paths(cmd: str) -> list[str]:
    """Absolute paths the command acts on that don't exist, i.e. the LLM guessed a location."""
    return [p for p in _EXISTING_ITEM.findall(cmd)
            if not any(c in p for c in "*?[") and not os.path.exists(p)]


def _run_sync(cmd: str) -> str:
    wrapped = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + cmd
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped],
            capture_output=True, timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {TIMEOUT_SECONDS} seconds."
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    result = f"Exit code: {proc.returncode}\n"
    if out:
        result += f"Output:\n{out[:MAX_OUTPUT]}"
        if len(out) > MAX_OUTPUT:
            result += f"\n... ({len(out) - MAX_OUTPUT} more characters truncated)"
    else:
        result += "Output: (none)"
    if err:
        result += f"\nErrors:\n{err[:1000]}"
    return result


async def run_powershell(cmd: str) -> str:
    return await asyncio.to_thread(_run_sync, cmd)


# Fixed script (not LLM-written) that queries the Windows Search index, which answers in ~0.1s where a
# recursive Get-ChildItem over the user's folders takes minutes. The search words arrive via an
# environment variable, so they are only ever data, never code.
_FIND_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$words = $env:JARVIS_FIND -split '\s+' | Where-Object { $_ }
$conditions = foreach ($w in $words) {
    $w = $w.Replace("'", "''").Replace('[', '[[]').Replace('%', '[%]').Replace('_', '[_]').Replace('*', '%')
    "System.FileName LIKE '%$w%'"
}
$scope = 'file:' + $env:USERPROFILE.Replace('\', '/')
$sql = "SELECT TOP 60 System.ItemPathDisplay, System.DateModified FROM SYSTEMINDEX WHERE SCOPE='$scope' AND " + ($conditions -join ' AND ') + " ORDER BY System.DateModified DESC"
$conn = New-Object -ComObject ADODB.Connection
$conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$rs = $conn.Execute($sql)
$n = 0
while (-not $rs.EOF -and $n -lt 20) {
    $path = [string]$rs.Fields.Item('System.ItemPathDisplay').Value
    # Skip app data and hidden dot-folders: the user means their own files
    if ($path -notmatch '\\AppData\\|\\\.[^\\]+\\') {
        '{0}  (modified {1:yyyy-MM-dd})' -f $path, $rs.Fields.Item('System.DateModified').Value
        $n++
    }
    $rs.MoveNext()
}
$conn.Close()
if ($n -eq 0) { 'No matches in the Windows search index.' }
"""


def _find_sync(words: str) -> str:
    words = " ".join(words.replace('"', " ").split())[:100]
    if not words:
        return "No search words given."
    env = {**os.environ, "JARVIS_FIND": words}
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _FIND_SCRIPT],
            capture_output=True, timeout=TIMEOUT_SECONDS, env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Search timed out after {TIMEOUT_SECONDS} seconds."
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or (err and not out):
        return f"Search failed: {err[:500]}"
    return f"Files in the user's folders whose names contain: {words} (newest first)\n{out}"


async def find_files(words: str) -> str:
    return await asyncio.to_thread(_find_sync, words)


CONFIRM_WORDS = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|confirm(ed)?|proceed|go ahead|do it|affirmative)\b", re.I)


def is_confirmation(text: str) -> bool:
    return bool(CONFIRM_WORDS.search(text))
