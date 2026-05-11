# eFLINT Unit Tester
A wrapper around the [`eflint-repl`](https://gitlab.com/eflint/haskell-implementation) interpreter in order to execute eFLINT files as if they are unit tests.


## Usage
The tool works by defining a special class of comments in eFLINT files that define what output to expect from the reasoner. For example:
```eflint
+person(Amy).
//#assert person(Amy).

//#assert !person(Bob).

Invariant foo When False.
//#violated foo.

Invariant bar When True.
//#violated !bar.
```

The tool works by submitting any phrases to the eFLINT reasoner one-by-one, and then inspecting its output to derive whether some instance has been created most recently or violated.

Concretely, there are two types of special comments:
- `//#assert [!]<instance>.`: inspect the knowledge base and assert that certain facts are true (default) or false (when `!` is given before the instance).
    - Note that the tool assumes that if an obfuscation (`~`) is the most recent update for an instance, it equates falsity.
- `//#violated [!]<instance>.`: check if a violation of an instance occurs (or _not_ occurs, if `!` is given before the instance).
    - Note that the tool does not distinguish between phrases in this case; so if the violation has occurred _anywhere_ before the comment, it is interpreted as violating, even if it has been un-violated later.

If any of the assertions in a file fails, then the script will warn the user and fail with a non-zero exit code. This allows tests in eFLINT to be automated.

> NOTE: Because the assertions are sequential, they are not supported within eFLINT's phrase groups. There, they are just comments.

### Wildcards
Since v0.2.0, the tool also supports using _wildcards_. This can be used to assert that instances or violations of a certain shape have occurred, e.g.,:
```eflint
+person(Amy).
//#assert person(*).
```
will check for any person. Similarly,
```eflint
+friend-of(Amy, Bob).
//#assert friend-of(Amy, *).
```
will check if Amy has at least one friend.


## Installation
To use the tool, make sure that you have installed [Python](https://python.org) on your system (at least version 3.9). Also make sure that you have some `eflint-repl`-binary available. The easiest is to install it by following the instructions on the [Haskell implementation](https://gitlab.com/eflint/haskell-implementation)-repository.

Then, you can download the tool by downloading it from the latest release, i.e.,
```bash
curl -o ./eflint-test.py https://gitlab.com/eflint/tools/unit-tester/-/raw/main/eflint-test.py
```

Then, either make the file executable and call it directly...
```bash
chmod +x ./eflint-test.py
./eflint-test.py <ARGS...>
```
...or call with `python`:
```bash
# Windows
python ./eflint-test.py <ARGS...>

# Unix
python3 ./eflint-test.py <ARGS...>
```

As arguments, simply give a list of files or directories to test. The tool will run to completion and return with exit code 0 if all files succeed, or else display which assertion failed and return a non-zero exit code.

> If your `eflint-repl` is not accessible as such, you can manually specify it by using the `--exec`-flag. E.g.,
> ```bash
> ./eflint-test.py --exec /some/other/eflint-repl <ARGS...>
> ```

If you give a directory, then the tester will recursively find all files in it and any nested directories and test those. Which files are matched is controlled by the `--extension`-option.


## Examples
The following projects incorporate the `eflint-test`er:
- [DMI Afsprakenstelsel Formalisation](https://gitlab.com/eflint/formalisations/dmi-afsprakenstelsel)


## Contribution
Contributions to this project are welcome! Feel free to create an [issue](https://gitlab.com/eflint/tools/unit-tester/issues) if you want to discuss something, have a suggestion or encountered a bug; or create a [merge request](https://gitlab.com/eflint/tools/unit-tester/merge_requests) if you already have some implemented change.


## License
This project is licensed under Apache 2.0. See [LICENSE](./LICENSE) for more information.