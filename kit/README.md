# TOTK-ipa kit

Make a Tears of the Kingdom IPA for iPhone and iPad from **your own** game dump and keys, on Linux, Windows (WSL) or a
Mac. The kit is built by GitHub without any game file. Your dump and `prod.keys` stay on your computer.

It is built on [MacNativeGames](https://github.com/ly05010419/MacNativeGames), which does the real work: it rewrites the
game's code for Apple chips and rebuilds its graphics on Metal. This kit only moves the game-specific steps of its iOS
build from a Mac to your computer.

## What you need

- The kit for your computer, from this repository's Releases: `totk-ipa-kit-linux-x64.tar.gz` (Linux, or WSL on
  Windows) or `totk-ipa-kit-macos-arm64.tar.gz` (Apple silicon Mac).
- **Base game 1.0.0** (`.xci`, or `.nsp`) **and the 1.4.3 update** (`.nsp` or `.nsz`), dumped from your Switch.
  1.4.3 is the only version MacNativeGames has tested on iPhone and iPad.
- Your `prod.keys`, from the same Switch.
- An NSP base game only: the system fonts, as `--firmware <unpacked firmware NCAs>` or
  `--shared-fonts <folder with the six .bfttf files>`. An XCI has them.
- Python 3.14 or newer (`uv python install 3.14` gets it on any system).
- About 60 GB of free disk space.
- An iPhone 14 or newer (or a recent iPad) on iOS/iPadOS 26, and a sideloading tool: xtool, Sideloadly, AltStore…

## Make the IPA

```sh
tar xzf totk-ipa-kit-linux-x64.tar.gz
cd totk-ipa-kit-linux-x64
python3.14 totk_import.py ~/Games/totk.xci --update ~/Games/totk-1.4.3.nsp -k ~/keys/prod.keys -o ~/Games/TOTK.ipa
```

The import runs MacNativeGames' own steps on your files:

1. Check every file against the hashes of the supported versions.
2. Rewrite the code and decrypt the data (17 GB).
3. Prepare the startup shaders.

Then it puts the result into the app shell and writes the IPA. The IPA is about 18 GB. Running the command again reuses
the work already done; the work folder is `TOTK_ipa_build` next to the game file.

Sign and install the IPA with your sideloading tool, keeping its entitlements: the game needs the increased memory limit.

**The IPA contains the game made from your files. It is for your own use only: do not share it.**

## What is different from building on a Mac

- **Shaders compile on the phone.** A Mac precompiles the startup shaders with Apple's Metal compiler, which runs only on
  Apple systems. Without it, each shader compiles on the phone the first time it is used, so the first launches stutter
  more until the phone's shader cache fills.
- **Game data is loaded at startup.** The game's tables are read from `GameData/totk-late.bin` when the app starts,
  instead of being compiled into it.
- **The game code goes into reserved space.** It is placed into empty sections the shell reserved for it, and the
  executable is signed again (ad hoc) afterwards.
- **Checks still run on the phone.** The phone checks every patched instruction and the hash of every embedded code
  part when it starts, as it does with a Mac build. A mistake stops the start with a message rather than running wrong
  code.

## Building the kit (maintainers)

The kit is built by the **Build TOTK-ipa kit** workflow (Actions → Run workflow). It does three things:

- **App shell:** on a macOS 26 machine it builds MacNativeGames' iOS app with `kit/build_shell.py`.
- **Helper tools:** it builds hactool, SPIRV-Cross and the shader translator for Linux and macOS with `kit/build_tools.py`.
- **Self-tests:** they check that:
  - the Python port of the 1.4.3 code patches writes exactly what MacNativeGames' C code writes;
  - the filled executable passes `codesign --verify`;
  - the tables file round-trips through the app's reader.

It then publishes the two kits as a release.
