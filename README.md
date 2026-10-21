# TOTK-ipa

Build an iPhone/iPad IPA of Tears of the Kingdom from **your own** dump, without a Mac and without uploading your game
anywhere.

GitHub builds a game-free kit: the app shell (MacNativeGames' iOS app with empty space for the game) and the helper
tools. You download the kit and run its import script with your dump and `prod.keys`. The script makes the IPA on your
computer, and you sideload it.

- **Windows players:** download `TOTK-ipa-Setup.exe` from Releases and run it. The builder it installs asks for your
  game files and makes the IPA.
- **Linux and Mac players:** download the kit from Releases and follow [kit/README.md](kit/README.md).
- **Maintainers:** run the **Build TOTK-ipa kit** workflow in Actions to build and publish the kit.

Based on [MacNativeGames](https://github.com/ly05010419/MacNativeGames) (MIT). Not affiliated with Nintendo. You must
own the game; the IPA you make contains it and is for your own use only.
